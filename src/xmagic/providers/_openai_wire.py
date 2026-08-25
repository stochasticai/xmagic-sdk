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

from xmagic.errors import XMagicError
from xmagic.providers.base import ChatMessage, ContentPart, ToolCall, ToolDef

STREAMING_TOOLS_UNSUPPORTED = (
    "Streaming tool calls are not implemented yet (DESIGN.md §13.6, stage B): "
    "arguments arrive as JSON fragments that have to be accumulated across "
    "deltas. Use complete() with tools=, or drop tools= to stream text."
)


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
