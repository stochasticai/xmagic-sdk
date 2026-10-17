"""The tool-calling execution loop — DESIGN.md §13, stage D.

One loop: send the conversation with `tools=`, run whatever the model asks
for, feed the results back, repeat until a turn answers in text. The scope is
deliberately the decided minimum (§13.8 Q1): a turn cap, dispatch by name to
the callables the `ToolDef`s were built from, errors fed back as tool results
unless the caller opts into raising, and the final `Completion` plus the full
history handed back. Handoffs, memory, planners and retry policy stay out.

Built entirely on `Provider.complete`, so it works for any adapter that
honours `tools=` — `openai:` and `litellm:` today (§13.4 D4). The `xmagic:`
adapter rejects per-call tools on the first turn with its usual error, which
is this loop's answer for unsupported providers: `capabilities()["tools"]`
cannot gate it, because LiteLLM reports `False` for any model its metadata
does not list.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_core import to_json

from xmagic.errors import ToolTurnsExceeded, XMagicError
from xmagic.providers.base import ChatMessage, Completion, Provider, ToolCall, ToolDef, Usage


@dataclass
class ToolRun:
    """What a finished `run_tools` loop hands back."""

    completion: Completion
    """The final turn: a text answer, its `tool_calls` empty."""
    messages: list[ChatMessage]
    """The input plus every assistant/tool turn, ending with the final answer.

    Resendable as-is: append the next user message and pass it back to
    `run_tools` (or `complete`) to continue the conversation.
    """
    usage: Usage | None = None
    """Token counts summed over every turn, where the provider reported them.

    `completion.usage` covers only the final model call; the intermediate
    turns' counts exist nowhere else, which is why the sum rides the result.
    """
    turns: int = field(default=0)
    """How many model calls the run made."""


def run_tools(
    provider: Provider,
    messages: list[ChatMessage],
    *,
    model: str,
    tools: list[ToolDef],
    max_turns: int = 10,
    raise_errors: bool = False,
    response_format: type[BaseModel] | None = None,
    **params: Any,
) -> ToolRun:
    """The blocking loop behind `Provider.run_tools`, which documents it."""
    by_name = _checked(tools, max_turns)
    for tool in tools:
        if inspect.iscoroutinefunction(tool.fn):
            raise TypeError(
                f"Tool '{tool.name}' is async. run_tools cannot await it; use arun_tools."
            )

    history = list(messages)
    usages: list[Usage] = []
    for turn in range(1, max_turns + 1):
        completion = provider.complete(
            history, model=model, tools=tools, response_format=response_format, **params
        )
        if completion.usage is not None:
            usages.append(completion.usage)
        if not completion.tool_calls:
            history.append(ChatMessage(role="assistant", content=completion.text))
            return ToolRun(
                completion=completion, messages=history, usage=_summed(usages), turns=turn
            )
        if turn == max_turns:
            raise _exceeded(completion, history, max_turns, usages)
        history.append(
            ChatMessage(
                role="assistant",
                content=completion.text or None,
                tool_calls=completion.tool_calls,
            )
        )
        for call in completion.tool_calls:
            result = _run_one(by_name, call, raise_errors)
            history.append(ChatMessage(role="tool", tool_call_id=call.id, content=result))
    raise AssertionError("unreachable: every path through the loop returns or raises")


async def arun_tools(
    provider: Provider,
    messages: list[ChatMessage],
    *,
    model: str,
    tools: list[ToolDef],
    max_turns: int = 10,
    raise_errors: bool = False,
    response_format: type[BaseModel] | None = None,
    **params: Any,
) -> ToolRun:
    """The async loop behind `Provider.arun_tools`, which documents it."""
    by_name = _checked(tools, max_turns)

    history = list(messages)
    usages: list[Usage] = []
    for turn in range(1, max_turns + 1):
        # `complete` is blocking and there is no async provider API yet; a
        # worker thread keeps the event loop serving while the model thinks.
        completion = await asyncio.to_thread(
            lambda: provider.complete(
                history, model=model, tools=tools, response_format=response_format, **params
            )
        )
        if completion.usage is not None:
            usages.append(completion.usage)
        if not completion.tool_calls:
            history.append(ChatMessage(role="assistant", content=completion.text))
            return ToolRun(
                completion=completion, messages=history, usage=_summed(usages), turns=turn
            )
        if turn == max_turns:
            raise _exceeded(completion, history, max_turns, usages)
        history.append(
            ChatMessage(
                role="assistant",
                content=completion.text or None,
                tool_calls=completion.tool_calls,
            )
        )
        for call in completion.tool_calls:
            result = await _arun_one(by_name, call, raise_errors)
            history.append(ChatMessage(role="tool", tool_call_id=call.id, content=result))
    raise AssertionError("unreachable: every path through the loop returns or raises")


def _checked(tools: list[ToolDef], max_turns: int) -> dict[str, ToolDef]:
    """The pre-flight checks shared by both loops: fail before spending tokens."""
    if max_turns < 1:
        raise ValueError(f"max_turns must be at least 1, not {max_turns}.")
    if not tools:
        raise ValueError(
            "run_tools needs at least one tool. For a plain completion, call complete()."
        )
    names = [tool.name for tool in tools]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"Tool names must be unique; duplicated: {', '.join(duplicates)}. "
            "The model addresses a tool by name alone."
        )
    for tool in tools:
        if tool.fn is None:
            raise TypeError(
                f"Tool '{tool.name}' carries no callable, so the loop has nothing "
                "to run. Build it with ToolDef.from_callable(fn); a hand-built "
                "ToolDef works with complete(), where the caller does the dispatch."
            )
    return {tool.name: tool for tool in tools}


def _exceeded(
    completion: Completion, history: list[ChatMessage], max_turns: int, usages: list[Usage]
) -> ToolTurnsExceeded:
    # The final turn's calls are deliberately not executed: their results
    # could never reach the model, and a side-effecting tool run whose output
    # goes nowhere is worse than one that never happened.
    names = ", ".join(call.name for call in completion.tool_calls)
    return ToolTurnsExceeded(
        f"The model was still calling tools ({names}) after {max_turns} "
        f"turn{'s' if max_turns != 1 else ''}. The unanswered calls are on "
        ".completion; .messages is resendable to continue with a fresh cap.",
        completion=completion,
        messages=history,
        usage=_summed(usages),
    )


def _run_one(by_name: dict[str, ToolDef], call: ToolCall, raise_errors: bool) -> str:
    """One tool call to one result string, errors becoming results unless asked."""
    try:
        tool, kwargs = _resolve(by_name, call)
        value = tool.fn(**kwargs)  # type: ignore[misc]  # _checked rejected fn=None
        if inspect.isawaitable(value):
            # A sync wrapper that forgot to await. Closing it beats a
            # "never awaited" warning at garbage collection, and this is a
            # programming error, not something the model can correct.
            getattr(value, "close", lambda: None)()
            raise TypeError(
                f"Tool '{call.name}' returned an awaitable from a sync call; "
                "declare it async and use arun_tools."
            )
        return _as_text(call.name, value)
    except Exception as e:  # noqa: BLE001 -- a tool may raise anything, and feeding
        # the error back as the tool result is this surface's contract.
        return _reported(call, e, raise_errors)


async def _arun_one(by_name: dict[str, ToolDef], call: ToolCall, raise_errors: bool) -> str:
    try:
        tool, kwargs = _resolve(by_name, call)
        value = tool.fn(**kwargs)  # type: ignore[misc]  # _checked rejected fn=None
        if inspect.isawaitable(value):
            value = await value
        return _as_text(call.name, value)
    except Exception as e:  # noqa: BLE001 -- same contract as _run_one.
        return _reported(call, e, raise_errors)


def _resolve(by_name: dict[str, ToolDef], call: ToolCall) -> tuple[ToolDef, dict[str, Any]]:
    """The tool a call names and the kwargs to invoke it with.

    Arguments go through the tool's argument model when `from_callable` built
    one, which is what coerces `"3"` to `3` and hands a nested pydantic
    parameter over as an instance; `call.arguments` alone would pass a dict to
    a function whose signature names a model.
    """
    tool = by_name.get(call.name)
    if tool is None:
        raise XMagicError(f"unknown tool '{call.name}'. Available: {', '.join(by_name)}")
    if tool.arguments_model is None:
        return tool, dict(call.arguments)
    instance = tool.arguments_model.model_validate(call.arguments)
    return tool, {name: getattr(instance, name) for name in type(instance).model_fields}


def _reported(call: ToolCall, e: Exception, raise_errors: bool) -> str:
    """An error as the model will see it — or not, when the caller wants it raised.

    `TypeError` from the awaitable check raises under both settings: it is the
    caller's bug, and no re-phrasing by the model fixes a missing `await`.
    """
    if raise_errors or (isinstance(e, TypeError) and "returned an awaitable" in str(e)):
        raise e
    if isinstance(e, ValidationError):
        # In pydantic's words: field by field, what failed and why, which is
        # exactly the shape a model corrects itself from.
        return f"Error: arguments for '{call.name}' failed validation: {e}"
    return f"Error: {type(e).__name__}: {e}"


def _as_text(name: str, value: Any) -> str:
    """A tool's return value as the string the wire wants."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    try:
        return to_json(value).decode()
    except Exception as e:
        raise XMagicError(
            f"Tool '{name}' returned a value that does not serialize to JSON "
            f"({type(value).__name__}): {e}"
        ) from e


def _summed(usages: list[Usage]) -> Usage | None:
    """Every turn's counts folded into one, `None` when no turn reported any."""
    if not usages:
        return None

    def total(attr: str) -> int | None:
        counted = [count for usage in usages if (count := getattr(usage, attr)) is not None]
        return sum(counted) if counted else None

    return Usage(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        total_tokens=total("total_tokens"),
    )
