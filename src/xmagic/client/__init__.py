"""xMagic API client (sync; async mirror planned for Phase 1, see DESIGN.md)."""

from __future__ import annotations

from typing import Any

from xmagic.client.chats import ChatsAPI
from xmagic.client.drive import DriveAPI
from xmagic.client.files import FilesAPI
from xmagic.client.http import HttpTransport
from xmagic.config import Settings


class XMagicClient:
    """Synchronous client for the xMagic API.

    Usage::

        client = XMagicClient()                 # env/config resolution
        client = XMagicClient(api_key="xm-...") # explicit
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kw: Any):
        self.settings = Settings.load(api_key=api_key, base_url=base_url, **kw)
        self._transport = HttpTransport(self.settings)
        self.chats = ChatsAPI(self._transport)
        self.files = FilesAPI(self._transport)
        self.drive = DriveAPI(self._transport)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "XMagicClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncXMagicClient:
    """Async client mirroring :class:`XMagicClient` 1:1.

    Planned for Phase 1 (see DESIGN.md roadmap). Kept as a placeholder so the
    public import path is stable.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "AsyncXMagicClient lands in Phase 1 (see DESIGN.md). Use XMagicClient for now."
        )


__all__ = ["XMagicClient", "AsyncXMagicClient"]
