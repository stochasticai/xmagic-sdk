"""xMagic provider: adapts agent-chat semantics to the Provider interface.

Here ``model`` is an xMagic ``agent_id``. A standard chat is created lazily
per provider instance (or pass ``chat_id=`` to reuse one).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.client import XMagicClient
from xmagic.client.models import ChatType, StreamEvent
from xmagic.config import Settings
from xmagic.errors import XMagicAPIError
from xmagic.providers.base import (
    ChatMessage,
    Completion,
    CompletionChunk,
    Provider,
    Usage,
)


def _usage_payload(event: StreamEvent) -> dict[str, Any]:
    """The usage body, wherever the frame happens to put it.

    Unconfirmed shape: `token_usage` comes from the backend's private
    ``TokenType`` enum, not the API reference, and no recorded live stream has
    contained one. So look in the two plausible places and accept either.
    """
    raw = event.raw if isinstance(event.raw, dict) else {}
    data = raw.get("data")
    return data if isinstance(data, dict) else raw


def _usage_from(event: StreamEvent) -> Usage | None:
    """Best-effort token counts. Never raises -- unknown shapes yield ``None``.

    Costing information is not worth failing a generation over.
    """
    payload = _usage_payload(event)

    def count(*names: str) -> int | None:
        for name in names:
            value = payload.get(name)
            if isinstance(value, bool):  # bools are ints; not a token count
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.lstrip("-").isdigit():
                return int(value)
        return None

    usage = Usage(
        input_tokens=count("input_tokens", "prompt_tokens"),
        output_tokens=count("output_tokens", "completion_tokens"),
        total_tokens=count("total_tokens"),
        raw=payload,
    )
    known = (usage.input_tokens, usage.output_tokens, usage.total_tokens)
    # A frame we could not read at all is worse than no frame: it would report
    # zero tokens as though that were measured.
    return usage if any(v is not None for v in known) else None


def _stream_error(event: StreamEvent) -> XMagicAPIError:
    """Turn an ``error`` frame into the same error type the HTTP layer raises."""
    payload = _usage_payload(event)
    message = (
        event.text
        or (payload.get("message") if isinstance(payload.get("message"), str) else None)
        or "The agent reported an error mid-stream."
    )
    code = payload.get("error_code")
    return XMagicAPIError(200, code if isinstance(code, str) else None, message)


def _flatten(messages: list[ChatMessage]) -> str:
    """Collapse a message list into a single query string.

    The chats API takes one query per turn; prior context lives server-side in
    the chat. System messages are prefixed as instructions.
    """
    parts = [f"[{m.role}] {m.content}" if m.role != "user" else m.content for m in messages]
    return "\n\n".join(parts)


class XMagicProvider(Provider):
    """Chat completions backed by an xMagic agent."""

    name = "xmagic"

    def __init__(
        self,
        api_key: str | None = None,
        settings: Settings | None = None,
        chat_id: str | None = None,
        chat_type: ChatType | str = ChatType.STANDARD,
        **options: Any,
    ) -> None:
        super().__init__(api_key=api_key, **options)
        self._client = (
            XMagicClient(api_key=api_key)
            if settings is None
            else XMagicClient(api_key=api_key or settings.api_key, base_url=settings.base_url)
        )
        self._chat_id = chat_id
        self._chat_type = chat_type

    @property
    def chat_id(self) -> str | None:
        """The chat backing this provider, once one has been created."""
        return self._chat_id

    def _ensure_chat(self, agent_id: str) -> str:
        """Create the chat on first use, then reuse it.

        Caching here is what gives an interactive session continuity: every turn
        through the same provider instance lands in the same chat, so the agent
        keeps its server-side history.
        """
        if self._chat_id is None:
            chat = self._client.chats.create(
                agent_id, title="xmagic-sdk session", chat_type=self._chat_type
            )
            self._chat_id = chat.id
        return self._chat_id

    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        chat_id = self._ensure_chat(model)
        resp = self._client.chats.query(model, chat_id, _flatten(messages), **params)
        return Completion(text=resp.text, model=f"xmagic:{model}", raw=resp.model_dump())

    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        chat_id = self._ensure_chat(model)
        usage: Usage | None = None
        for event in self._client.chats.stream(model, chat_id, _flatten(messages), **params):
            if event.type == "done":
                yield CompletionChunk(text="", done=True, usage=usage)
            elif event.type == "response":
                yield CompletionChunk(text=event.text)
            elif event.type == "reasoning":
                yield CompletionChunk(text=event.text, kind="reasoning")
            elif event.type == "error":
                # Previously ignored, which made a failed generation
                # indistinguishable from a short successful one: the caller got
                # whatever text arrived before the failure, and no error.
                raise _stream_error(event)
            elif event.type == "token_usage":
                usage = _usage_from(event)
            # `metadata`, `ping`, `live_update`, `end_response`, `end_reasoning`
            # and `fast_response_simulation` are deliberately ignored. Named here
            # so the next reader knows that is a decision rather than an
            # oversight -- note `metadata` carries `message_id`, so a streaming
            # caller still cannot learn the id of the message it just received.

    def capabilities(self) -> dict[str, bool]:
        return {"streaming": True, "tools": True, "vision": False}
