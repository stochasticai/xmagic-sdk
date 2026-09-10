"""Tool calling: hand the model typed Python functions, run what it asks for.

A tool is written once. `ToolDef.from_callable` turns the signature into JSON
Schema and the docstring into the description, the model answers with `ToolCall`s
whose `arguments` are already a parsed dict, and a `role="tool"` message carries
the result back. The loop that ties those together is a few lines and it is
yours to write -- this SDK deliberately ships no agent runtime (DESIGN.md §1).

Run:
    export OPENAI_API_KEY="sk-..."

    uv run python examples/07_tool_calling.py
    uv run python examples/07_tool_calling.py litellm:groq/llama-3.3-70b-versatile
    uv run python examples/07_tool_calling.py litellm:ollama/llama3.1   # no key at all

Needs no xMagic key. `tools=` works on `openai:` and `litellm:` refs; an `xmagic:`
ref rejects it, because an xMagic agent's tools are registered in the dashboard
and attached to the agent rather than passed per call.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from xmagic.errors import ConfigurationError, XMagicError
from xmagic.providers import ChatMessage, ModelRef, ToolDef, get_provider

DEFAULT_REF = "openai:gpt-5"


# --- The tools. Plain functions with type hints and a docstring; nothing else.


def get_weather(city: str) -> str:
    """Current weather in a city."""
    return {"osaka": "sunny, 24C", "kyoto": "light rain, 19C"}.get(city.lower(), "no data")


def convert_temperature(celsius: float, unit: str = "F") -> str:
    """Convert a Celsius reading to F or K."""
    if unit.upper() == "K":
        return f"{celsius + 273.15:.1f}K"
    return f"{celsius * 9 / 5 + 32:.1f}F"


TOOLS: dict[str, Callable[..., str]] = {
    get_weather.__name__: get_weather,
    convert_temperature.__name__: convert_temperature,
}
TOOL_DEFS = [ToolDef.from_callable(fn) for fn in TOOLS.values()]


def run_blocking(provider: Any, model: str) -> None:
    """The round trip on `complete()`: ask, run what was called, ask again."""
    messages = [
        ChatMessage(role="system", content="Use the tools. Answer in one sentence."),
        ChatMessage(role="user", content="What's the weather in Osaka, in Fahrenheit?"),
    ]

    # A model may need more than one turn: weather first, then the conversion
    # once it has a number to convert. Stop when it answers in text instead.
    for _ in range(4):
        completion = provider.complete(messages, model=model, tools=TOOL_DEFS)
        if not completion.tool_calls:
            print(f"answer: {completion.text}")
            return

        # The assistant turn that made the calls goes into history first, then
        # one `tool` message per call, matched by id. Send both or the next
        # request is rejected as a tool result with no call to answer.
        messages.append(
            ChatMessage(role="assistant", content=None, tool_calls=completion.tool_calls)
        )
        for call in completion.tool_calls:
            result = TOOLS[call.name](**call.arguments)  # arguments arrive parsed
            print(f"  {call.name}({call.arguments}) -> {result}")
            messages.append(ChatMessage(role="tool", tool_call_id=call.id, content=result))

    print("gave up: the model kept calling tools", file=sys.stderr)


def run_streaming(provider: Any, model: str) -> None:
    """The same thing on `stream()`.

    Text arrives as it is generated. A tool call does not: its arguments come
    as JSON fragments that mean nothing until the last one lands, so completed
    calls surface on the terminal chunk -- the one with `done=True`, where
    `usage` already lives. Nothing about the calls is visible before that.
    """
    messages = [ChatMessage(role="user", content="What's the weather in Kyoto?")]

    for chunk in provider.stream(messages, model=model, tools=TOOL_DEFS):
        if chunk.kind == "response":
            print(chunk.text, end="", flush=True)
        if chunk.done:
            for call in chunk.tool_calls:
                print(f"  {call.name}({call.arguments}) -> {TOOLS[call.name](**call.arguments)}")
    print()


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REF
    model = ModelRef.parse(ref).model

    for tool in TOOL_DEFS:
        # The schema came from the signature: `celsius` is a required number,
        # `unit` an optional string. `strict` is off here because `unit` has a
        # default, and strict mode requires every property to be required.
        print(f"tool {tool.name}: {sorted(tool.parameters['properties'])} strict={tool.strict}")
    print()

    try:
        provider = get_provider(ref)
    except (ConfigurationError, ImportError) as e:
        # No key for the OpenAI adapter, or the adapter's extra is not installed.
        print(e, file=sys.stderr)
        return 2

    # On the LiteLLM path this is read from model metadata, so `False` may mean
    # "no flag for this model" rather than "cannot". Try anyway if you know better.
    if not provider.capabilities().get("tools"):
        print(f"{ref} does not advertise tool support; trying anyway\n", file=sys.stderr)

    try:
        print("-- blocking --")
        run_blocking(provider, model)
        print("\n-- streaming --")
        run_streaming(provider, model)
    except XMagicError as e:
        # Includes unparseable arguments from the model, which raise rather
        # than crash inside your tool -- and, when streaming, a call the model
        # was cut off in the middle of.
        print(f"\n{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
