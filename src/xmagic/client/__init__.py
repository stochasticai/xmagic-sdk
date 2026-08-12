"""xMagic API client, sync and async."""

from __future__ import annotations

from typing import Any, Self

from xmagic.client.chats import AsyncChatsAPI, ChatsAPI
from xmagic.client.drive import AsyncDriveAPI, DriveAPI
from xmagic.client.files import AsyncFilesAPI, FilesAPI
from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.worklists import AsyncWorklistsAPI, WorklistsAPI
from xmagic.config import Settings


def _overrides(api_key: str | None, base_url: str | None, kw: dict[str, Any]) -> dict[str, Any]:
    """Settings overrides, with the two named arguments omitted when unset.

    ``Settings.load`` applies every override as passed, so ``None`` reaches the
    field rather than being filtered out — that is what makes
    ``stream_timeout=None`` ("wait forever") expressible. These two arguments
    default to ``None`` to mean "not supplied", so they are dropped here rather
    than clobbering a key that the config file or environment provides.
    """
    named = {"api_key": api_key, "base_url": base_url}
    return {**{k: v for k, v in named.items() if v is not None}, **kw}


class XMagicClient:
    """Synchronous client for the xMagic API.

    Usage::

        client = XMagicClient()                 # env/config resolution
        client = XMagicClient(api_key="xm-...") # explicit
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kw: Any):
        self.settings = Settings.load(**_overrides(api_key, base_url, kw))
        self._transport = HttpTransport(self.settings)
        self.chats = ChatsAPI(self._transport)
        self.files = FilesAPI(self._transport)
        self.drive = DriveAPI(self._transport)
        self.worklists = WorklistsAPI(self._transport, self.chats)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncXMagicClient:
    """Async client mirroring :class:`XMagicClient` 1:1.

    Same resources, same arguments, same return types — every call is awaited
    and ``stream`` is an async iterator::

        async with AsyncXMagicClient() as client:
            chat = await client.chats.create(agent_id)
            async for event in client.chats.stream(agent_id, chat.id, "hi"):
                ...

    Construct it inside a running event loop. ``httpx.AsyncClient`` binds to the
    loop active when it is created, so a client built at import time and used
    later from a different loop will fail.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kw: Any):
        self.settings = Settings.load(**_overrides(api_key, base_url, kw))
        self._transport = AsyncHttpTransport(self.settings)
        self.chats = AsyncChatsAPI(self._transport)
        self.files = AsyncFilesAPI(self._transport)
        self.drive = AsyncDriveAPI(self._transport)
        self.worklists = AsyncWorklistsAPI(self._transport, self.chats)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


__all__ = ["AsyncXMagicClient", "XMagicClient"]
