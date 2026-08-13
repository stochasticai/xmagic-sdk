"""Workspace operations.

Endpoints (base: https://api.xmagic.ai/xmagic-backend/v1):

- GET  /users/workspaces
- POST /users/workspaces/switch?workspace_id=...
"""

from __future__ import annotations

from typing import Any

from xmagic.client.http import AsyncHttpTransport, HttpTransport, unwrap_data
from xmagic.client.models import WorkspaceState
from xmagic.errors import ResponseShapeError


def _state_from_body(body: dict[str, Any]) -> WorkspaceState:
    data = unwrap_data(body)
    if not isinstance(data, dict):
        raise ResponseShapeError("Unexpected workspace response shape")
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
