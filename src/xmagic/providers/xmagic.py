"""xMagic provider: adapts agent-chat semantics to the Provider interface.

Here ``model`` is an xMagic ``agent_id``. A standard chat is created lazily
per provider instance (or pass ``chat_id=`` to reuse one).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.client import XMagicClient
from xmagic.client.models import ChatType
from xmagic.config import Settings
from xmagic.providers.base import ChatMessage, Completion, CompletionChunk, Provider


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
        for event in self._client.chats.stream(model, chat_id, _flatten(messages), **params):
            if event.type == "done":
                yield CompletionChunk(text="", done=True)
            elif event.type == "response":
                yield CompletionChunk(text=event.text)
            elif event.type == "reasoning":
                yield CompletionChunk(text=event.text, kind="reasoning")

    def capabilities(self) -> dict[str, bool]:
        return {"streaming": True, "tools": True, "vision": False}
