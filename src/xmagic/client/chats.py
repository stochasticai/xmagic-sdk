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
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.client.http import HttpTransport
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
        payload: dict[str, Any] = {"chat_type": str(getattr(chat_type, "value", chat_type))}
        if title:
            payload["title"] = title
        body = self._t.request("POST", f"/agents/{agent_id}/chats", json=payload)
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
        payload: dict[str, Any] = {"query": query, "is_stream": False, **extra}
        if uploaded_files:
            payload["uploaded_files"] = uploaded_files
        body = self._t.request("POST", f"/agents/{agent_id}/chats/{chat_id}/query", json=payload)
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
        payload: dict[str, Any] = {"query": query, "is_stream": True, **extra}
        if uploaded_files:
            payload["uploaded_files"] = uploaded_files
        for raw in self._t.sse("POST", f"/agents/{agent_id}/chats/{chat_id}/query", json=payload):
            data = raw["data"]
            if raw.get("event") == "done":
                yield StreamEvent(type="done", text="", raw={})
                continue

            payload_type = data.get("type") if isinstance(data, dict) else None
            event = payload_type if payload_type in _STREAM_TYPES else "response"
            text = data if isinstance(data, str) else data.get("text", "")
            yield StreamEvent(
                type=event,  # type: ignore[arg-type]
                text=text,
                raw=data if isinstance(data, dict) else {"data": data},
            )

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
        payload: dict[str, Any] = {"query": query, "webhook_url": webhook_url, **extra}
        if uploaded_files:
            payload["uploaded_files"] = uploaded_files
        return self._t.request(
            "POST", f"/agents/{agent_id}/chats/{chat_id}/async_query", json=payload
        )

    def get_message(self, agent_id: str, chat_id: str, message_id: str) -> Message:
        """Retrieve full message data, including downloadable outputs."""
        body = self._t.request("GET", f"/agents/{agent_id}/chats/{chat_id}/message/{message_id}")
        return Message.model_validate(body["data"])

    def delete_message(self, agent_id: str, chat_id: str, message_id: str) -> None:
        """Delete a specific message."""
        self._t.request("DELETE", f"/agents/{agent_id}/chats/{chat_id}/message/{message_id}")
