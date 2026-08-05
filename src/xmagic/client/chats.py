"""Chat and message operations.

Endpoints (base: https://api.xmagic.ai/xmagic-backend/v1):

- POST   /agents/{agent_id}/chats
- POST   /agents/{agent_id}/chats/{chat_id}/query        (is_stream -> SSE)
- POST   /agents/{agent_id}/chats/{chat_id}/async_query  (webhook delivery)
- GET    /agents/{agent_id}/chats/{chat_id}/message/{message_id}
- DELETE /agents/{agent_id}/chats/{chat_id}/message/{message_id}

Response envelopes below are confirmed against a live agent (2026-07-31), not
guessed.

- create:      ``{"data": {"chat": {...}}}``
- query:       ``{"data": {"message_id": ..., "text": ..., "reasoning": ...}}``
- get_message: ``{"data": {<flat message fields>}}``

:class:`ChatsAPI` and :class:`AsyncChatsAPI` build their paths and payloads
through the same module-level helpers, so the wire format cannot drift between
them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import Chat, ChatType, Message, QueryResponse, StreamEvent

_STREAM_TYPES = {
    "reasoning",
    "end_reasoning",
    "fast_response_simulation",
    "response",
    "end_response",
    "live_update",
    "ping",
    "error",
    "token_usage",
    "metadata",
    "done",
}


def _chats_path(agent_id: str) -> str:
    return f"/agents/{agent_id}/chats"


def _query_path(agent_id: str, chat_id: str) -> str:
    return f"/agents/{agent_id}/chats/{chat_id}/query"


def _async_query_path(agent_id: str, chat_id: str) -> str:
    return f"/agents/{agent_id}/chats/{chat_id}/async_query"


def _message_path(agent_id: str, chat_id: str, message_id: str) -> str:
    return f"/agents/{agent_id}/chats/{chat_id}/message/{message_id}"


def _create_payload(title: str | None, chat_type: ChatType | str) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_type": str(getattr(chat_type, "value", chat_type))}
    if title:
        payload["title"] = title
    return payload


def _query_payload(
    query: str,
    *,
    is_stream: bool,
    uploaded_files: list[str] | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "is_stream": is_stream, **extra}
    if uploaded_files:
        payload["uploaded_files"] = uploaded_files
    return payload


def _async_query_payload(
    query: str,
    *,
    webhook_url: str,
    uploaded_files: list[str] | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "webhook_url": webhook_url, **extra}
    if uploaded_files:
        payload["uploaded_files"] = uploaded_files
    return payload


def _stream_event(raw: dict[str, Any]) -> StreamEvent:
    """Turn one decoded SSE frame into a typed event.

    Event identity comes from ``payload["type"]``, not the SSE event name — the
    backend never sets an ``event:`` field (confirmed live 2026-07-31).
    """
    data = raw["data"]
    if raw.get("event") == "done":
        return StreamEvent(type="done", text="", raw={})

    payload_type = data.get("type") if isinstance(data, dict) else None
    event = payload_type if payload_type in _STREAM_TYPES else "response"
    text = data if isinstance(data, str) else data.get("text", "")
    return StreamEvent(
        type=event,  # type: ignore[arg-type]
        text=text,
        raw=data if isinstance(data, dict) else {"data": data},
    )


class ChatsAPI:
    """Chat lifecycle and querying."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def create(
        self,
        agent_id: str,
        *,
        title: str | None = None,
        chat_type: ChatType | str = ChatType.STANDARD,
    ) -> Chat:
        """Create a new chat session with an agent."""
        body = self._t.request(
            "POST", _chats_path(agent_id), json=_create_payload(title, chat_type)
        )
        return Chat.model_validate(body["data"]["chat"])

    def query(
        self,
        agent_id: str,
        chat_id: str,
        query: str,
        *,
        uploaded_files: list[str] | None = None,
        **extra: Any,
    ) -> QueryResponse:
        """Send a synchronous (blocking) query."""
        payload = _query_payload(query, is_stream=False, uploaded_files=uploaded_files, extra=extra)
        body = self._t.request("POST", _query_path(agent_id, chat_id), json=payload)
        return QueryResponse.model_validate(body["data"])

    def stream(
        self,
        agent_id: str,
        chat_id: str,
        query: str,
        *,
        uploaded_files: list[str] | None = None,
        **extra: Any,
    ) -> Iterator[StreamEvent]:
        """Send a streaming query; yields typed SSE events until [DONE]."""
        payload = _query_payload(query, is_stream=True, uploaded_files=uploaded_files, extra=extra)
        for raw in self._t.sse("POST", _query_path(agent_id, chat_id), json=payload):
            yield _stream_event(raw)

    def async_query(
        self,
        agent_id: str,
        chat_id: str,
        query: str,
        *,
        webhook_url: str,
        uploaded_files: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Submit a long-running query; result is delivered to ``webhook_url``."""
        payload = _async_query_payload(
            query, webhook_url=webhook_url, uploaded_files=uploaded_files, extra=extra
        )
        return self._t.request("POST", _async_query_path(agent_id, chat_id), json=payload)

    def get_message(self, agent_id: str, chat_id: str, message_id: str) -> Message:
        """Retrieve full message data, including downloadable outputs."""
        body = self._t.request("GET", _message_path(agent_id, chat_id, message_id))
        return Message.model_validate(body["data"])

    def delete_message(self, agent_id: str, chat_id: str, message_id: str) -> None:
        """Delete a specific message."""
        self._t.request("DELETE", _message_path(agent_id, chat_id, message_id))


class AsyncChatsAPI:
    """Async mirror of :class:`ChatsAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def create(
        self,
        agent_id: str,
        *,
        title: str | None = None,
        chat_type: ChatType | str = ChatType.STANDARD,
    ) -> Chat:
        """Create a new chat session with an agent."""
        body = await self._t.request(
            "POST", _chats_path(agent_id), json=_create_payload(title, chat_type)
        )
        return Chat.model_validate(body["data"]["chat"])

    async def query(
        self,
        agent_id: str,
        chat_id: str,
        query: str,
        *,
        uploaded_files: list[str] | None = None,
        **extra: Any,
    ) -> QueryResponse:
        """Send a synchronous (blocking) query."""
        payload = _query_payload(query, is_stream=False, uploaded_files=uploaded_files, extra=extra)
        body = await self._t.request("POST", _query_path(agent_id, chat_id), json=payload)
        return QueryResponse.model_validate(body["data"])

    async def stream(
        self,
        agent_id: str,
        chat_id: str,
        query: str,
        *,
        uploaded_files: list[str] | None = None,
        **extra: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Send a streaming query; yields typed SSE events until [DONE]."""
        payload = _query_payload(query, is_stream=True, uploaded_files=uploaded_files, extra=extra)
        async for raw in self._t.sse("POST", _query_path(agent_id, chat_id), json=payload):
            yield _stream_event(raw)

    async def async_query(
        self,
        agent_id: str,
        chat_id: str,
        query: str,
        *,
        webhook_url: str,
        uploaded_files: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Submit a long-running query; result is delivered to ``webhook_url``."""
        payload = _async_query_payload(
            query, webhook_url=webhook_url, uploaded_files=uploaded_files, extra=extra
        )
        return await self._t.request("POST", _async_query_path(agent_id, chat_id), json=payload)

    async def get_message(self, agent_id: str, chat_id: str, message_id: str) -> Message:
        """Retrieve full message data, including downloadable outputs."""
        body = await self._t.request("GET", _message_path(agent_id, chat_id, message_id))
        return Message.model_validate(body["data"])

    async def delete_message(self, agent_id: str, chat_id: str, message_id: str) -> None:
        """Delete a specific message."""
        await self._t.request("DELETE", _message_path(agent_id, chat_id, message_id))
