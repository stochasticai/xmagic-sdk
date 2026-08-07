"""Workspace operations.

Endpoints (base: https://api.xmagic.ai/xmagic-backend/v1):

- GET  /users/workspaces
- POST /users/workspaces/switch?workspace_id=...
"""

from __future__ import annotations

from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import WorkspaceState


def _state_from_body(body: dict) -> WorkspaceState:
    data = body.get("data", body)
    return WorkspaceState.model_validate(data)


class WorkspacesAPI:
    """Workspace listing and switching for the current API key context."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def list(self) -> WorkspaceState:
        """Return all accessible workspaces and the current workspace id."""
        body = self._t.request("GET", "/users/workspaces")
        return _state_from_body(body)

    def switch(self, workspace_id: str) -> WorkspaceState:
        """Switch backend current workspace to ``workspace_id`` and return updated state."""
        body = self._t.request(
            "POST",
            "/users/workspaces/switch",
            params={"workspace_id": workspace_id},
        )
        return _state_from_body(body)


class AsyncWorkspacesAPI:
    """Async mirror of :class:`WorkspacesAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def list(self) -> WorkspaceState:
        """Return all accessible workspaces and the current workspace id."""
        body = await self._t.request("GET", "/users/workspaces")
        return _state_from_body(body)

    async def switch(self, workspace_id: str) -> WorkspaceState:
        """Switch backend current workspace to ``workspace_id`` and return updated state."""
        body = await self._t.request(
            "POST",
            "/users/workspaces/switch",
            params={"workspace_id": workspace_id},
        )
        return _state_from_body(body)
