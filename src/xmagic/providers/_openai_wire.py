"""Translation between this SDK's neutral types and the OpenAI wire shape.

Shared by the OpenAI and LiteLLM adapters, which is the point rather than a
coincidence: LiteLLM normalizes every vendor it reaches onto this same shape
(DESIGN.md §13.2), so one mapping covers roughly 150 providers and the native
OpenAI path at once. Anthropic's own API disagrees on every detail — parsed
arguments, results in a *user* message keyed by `tool_use_id` — and that
divergence is LiteLLM's problem, not this module's.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from xmagic.errors import XMagicError
from xmagic.providers.base import ChatMessage, ContentPart, ToolCall, ToolDef, claim_strict


def _content_to_wire(content: str | list[ContentPart] | None) -> Any:
    """`None` survives as `None`: an assistant turn that only called tools."""
    if content is None or isinstance(content, str):
        return content
    return [{"type": "text", "text": part.text} for part in content]


def message_to_wire(message: ChatMessage) -> dict[str, Any]:
    """One neutral message as the OpenAI chat-completions shape."""
    wire: dict[str, Any] = {"role": message.role, "content": _content_to_wire(message.content)}
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                # Back to a JSON string on the way out. The parsed dict is this
                # SDK's contract with its callers (D1), not the wire's.
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return wire


def messages_to_wire(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [message_to_wire(m) for m in messages]


def tools_to_wire(tools: list[ToolDef]) -> list[dict[str, Any]]:
    """Tool definitions as the vendor expects them.

    `strict` is sent only when true. It is not universally supported by the
    OpenAI-compatible backends reachable through `base_url`, and an unknown key
    set to its default is a needless thing to fail on.
    """
    wire: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, ToolDef):
            # Before `tools=` was a typed parameter, the only way to pass tools
            # was `**params` with raw vendor dicts. Those now bind to this
            # parameter and would fail as `AttributeError: 'dict' object has no
            # attribute 'name'` three frames down, which says nothing about what
            # to do.
            raise TypeError(
                f"tools= takes ToolDef, not {type(tool).__name__}. Build one with "
                "ToolDef(name=..., parameters=...) or ToolDef.from_callable(fn); "
                "raw vendor dicts are no longer passed through."
            )
        function: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        if tool.strict:
            function["strict"] = True
        wire.append({"type": "function", "function": function})
    return wire


def _arguments_to_dict(raw: Any, tool_name: str) -> dict[str, Any]:
    """Parse the vendor's arguments, whatever form they arrived in.

    OpenAI sends a JSON string; some compatible backends send an object
    already. A string that does not parse is raised rather than swallowed --
    with `strict` set it should not happen, and without it the caller is one
    `json.loads` away from a crash inside their own tool.
    """
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        raise XMagicError(
            f"The model returned unparseable arguments for tool {tool_name!r}: {raw!r}. "
            "Setting ToolDef.strict constrains generation to the schema where the "
            "vendor supports it."
        ) from e
    if not isinstance(parsed, dict):
        raise XMagicError(
            f"The model returned non-object arguments for tool {tool_name!r}: {raw!r}."
        )
    return parsed


def tool_calls_from_wire(message: Any) -> list[ToolCall]:
    """Read tool calls off a response message. Empty when the model made none."""
    calls = getattr(message, "tool_calls", None) or []
    found: list[ToolCall] = []
    for call in calls:
        function = getattr(call, "function", None)
        name = getattr(function, "name", None) or ""
        found.append(
            ToolCall(
                id=getattr(call, "id", "") or "",
                name=name,
                arguments=_arguments_to_dict(getattr(function, "arguments", None), name),
            )
        )
    return found


class ToolCallAccumulator:
    """Reassemble streamed tool calls from the fragments they arrive in.

    A streamed call is not one delta. The first carries the id and the function
    name; later ones carry `arguments` as JSON *string fragments* that are
    invalid JSON until every piece has landed. What ties them together is
    `index` -- not the id, which only the opening fragment has, and not arrival
    order, since a model calling two tools interleaves their fragments freely.

    Backends reachable through `base_url` are less disciplined than OpenAI
    about this, so `index` is treated as advisory: when it is missing, position
    within the delta stands in, which is right for the common single-call case
    and no worse than the alternative for the rest.
    """

    def __init__(self) -> None:
        # Insertion-ordered, so calls come back in the order the model opened
        # them rather than sorted by an index the vendor may not have sent.
        self._slots: dict[int, dict[str, Any]] = {}

    def add(self, delta: Any) -> None:
        """Fold one delta's fragments in. Deltas carrying none are no-ops."""
        for position, fragment in enumerate(getattr(delta, "tool_calls", None) or []):
            index = getattr(fragment, "index", None)
            if not isinstance(index, int) or isinstance(index, bool):
                index = position
            slot = self._slots.setdefault(index, {"id": "", "name": "", "arguments": ""})

            identifier = getattr(fragment, "id", None)
            if identifier:
                slot["id"] = identifier
            function = getattr(fragment, "function", None)
            name = getattr(function, "name", None)
            if name:
                # Some backends repeat the name on every fragment instead of
                # only the first; last-write-wins is the same value either way.
                slot["name"] = name

            arguments = getattr(function, "arguments", None)
            if isinstance(arguments, dict):
                # Already parsed, so there is nothing to concatenate -- the
                # non-streaming path tolerates this shape too.
                slot["arguments"] = arguments
            elif arguments and isinstance(slot["arguments"], str):
                slot["arguments"] += arguments

    @property
    def pending(self) -> bool:
        """Whether any fragment has arrived, complete or not."""
        return bool(self._slots)

    def finish(self) -> list[ToolCall]:
        """The completed calls. Empty when the model made none.

        Parsing happens here and nowhere earlier, because a fragment is not
        valid JSON on its own. A stream that ends mid-call therefore raises out
        of `_arguments_to_dict` rather than handing back a truncated call --
        which is the same promise the blocking path makes (D1).
        """
        return [
            ToolCall(
                id=slot["id"],
                name=slot["name"],
                arguments=_arguments_to_dict(slot["arguments"], slot["name"]),
            )
            for slot in self._slots.values()
        ]


def response_format_to_wire(model_type: type[BaseModel]) -> dict[str, Any]:
    """A pydantic model as the vendor's `json_schema` response format.

    The same strict rule as tools: claimed only for a flat, fully-required
    schema, since strict mode constrains every level and a nested model would
    be rejected outright. Unlike tools, `strict` is always sent here -- the
    `json_schema` format is recent enough that every backend offering it knows
    the key, and a backend that does not offer it fails on the format itself.
    """
    if not (isinstance(model_type, type) and issubclass(model_type, BaseModel)):
        raise TypeError(
            f"response_format= takes a pydantic model class, not "
            f"{type(model_type).__name__}. Raw vendor dicts are not passed through; "
            "define `class Answer(BaseModel)` and pass `Answer`."
        )
    schema = model_type.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model_type.__name__,
            "schema": schema,
            "strict": claim_strict(schema),
        },
    }


def parse_structured(text: str, model_type: type[BaseModel], refusal: Any = None) -> BaseModel:
    """Validate the reply into the requested model, or say exactly why not.

    Raises rather than returning `None`: the caller asked for an instance, and a
    silent `None` looks like success to code that reaches for `.parsed.field`
    three lines later. A refusal is the vendor declining the request on safety
    grounds; it arrives in its own field with no JSON alongside, so it is the
    one case reported in the vendor's words rather than as a parse failure.
    """
    if refusal:
        raise XMagicError(
            f"The model refused to answer in the {model_type.__name__} schema: {refusal}"
        )
    try:
        return model_type.model_validate_json(text)
    except ValidationError as e:
        raise XMagicError(
            f"The model's reply did not validate as {model_type.__name__}: {e}. Reply was: {text!r}"
        ) from e
