"""Agent listing and configuration helpers.

Current backend contracts used here:

- GET   /agents
- GET   /agents/{agent_id}/configs/temporary
- GET   /agents/{agent_id}/configs/{config_id}/config
- PATCH /agents/{agent_id}/configs/temporary
- POST  /agents/{agent_id}/configs
- POST  /agents/{agent_id}/configs/{config_id}/deploy
- GET   /agents/{agent_id}/configs/{config_id}/jobs
"""

from __future__ import annotations

from typing import Any

from xmagic.client.http import AsyncHttpTransport, HttpTransport, unwrap_data
from xmagic.client.models import AgentSummary, SavedConfig, SubagentSummary
from xmagic.errors import ResponseShapeError


def config_id_from_temporary(payload: dict[str, Any]) -> str:
    """Extract the verified ``id`` field from a temporary config response."""
    value = payload.get("id")
    if isinstance(value, str) and value:
        return value
    raise ResponseShapeError("Temporary config response is missing the required string 'id' field")


class AgentsAPI:
    """Agent list and temporary config operations."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def list(self) -> list[AgentSummary]:
        """List accessible agents"""
        body = self._t.request("GET", "/agents")
        data = unwrap_data(body)
        if not isinstance(data, list):
            raise ResponseShapeError("Unexpected /agents response shape: expected a list")
        return [AgentSummary.model_validate(item) for item in data]

    def get(self, agent_id: str) -> dict[str, Any]:
        """Get an agent, including its owning ``organization_id``."""
        body = self._t.request("GET", f"/agents/{agent_id}")
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected agent response shape")
        return data

    def get_temporary_config(self, agent_id: str) -> dict[str, Any]:
        """Get the temporary configuration model payload for ``agent_id``."""
        body = self._t.request("GET", f"/agents/{agent_id}/configs/temporary")
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected temporary config response shape")
        return data

    def export_temporary_config(self, agent_id: str) -> dict[str, Any]:
        """Export temporary config JSON in the import-compatible shape."""
        temporary = self.get_temporary_config(agent_id)
        config_id = config_id_from_temporary(temporary)
        body = self._t.request(
            "GET", f"/agents/{agent_id}/configs/{config_id}/config?include_ids=true"
        )
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected exported config response shape")
        return data

    def update_temporary_config(self, agent_id: str, config_json: dict[str, Any]) -> dict[str, Any]:
        """Update temporary config using JSON payload produced from YAML."""
        return self._t.request(
            "PATCH",
            f"/agents/{agent_id}/configs/temporary",
            json={"config_json": config_json},
        )

    def save_config(self, agent_id: str, version_name: str) -> SavedConfig:
        """Save the current temporary config as a named version.

        Calls ``POST /agents/{agent_id}/configs`` and returns the persisted
        :class:`~xmagic.client.models.SavedConfig` whose ``id`` is needed for
        the subsequent deploy call.
        """
        body = self._t.request(
            "POST",
            f"/agents/{agent_id}/configs",
            json={"version_name": version_name},
        )
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected save config response shape")
        return SavedConfig.model_validate(data)

    def deploy_config(self, agent_id: str, config_id: str) -> None:
        """Deploy a saved config version.

        Calls ``POST /agents/{agent_id}/configs/{config_id}/deploy``.
        """
        self._t.request("POST", f"/agents/{agent_id}/configs/{config_id}/deploy")

    def list_subagents(self, agent_id: str, config_id: str) -> list[SubagentSummary]:
        """List subagents belonging to the given config.

        Calls ``GET /agents/{agent_id}/configs/{config_id}/jobs``.
        """
        body = self._t.request("GET", f"/agents/{agent_id}/configs/{config_id}/jobs")
        data = unwrap_data(body)
        if not isinstance(data, list):
            raise ResponseShapeError("Unexpected /jobs response shape: expected a list")
        return [SubagentSummary.model_validate(item) for item in data]


class AsyncAgentsAPI:
    """Async mirror of :class:`AgentsAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def list(self) -> list[AgentSummary]:
        """List accessible agents using backend fallback endpoint ``GET /agents``."""
        body = await self._t.request("GET", "/agents")
        data = unwrap_data(body)
        if not isinstance(data, list):
            raise ResponseShapeError("Unexpected /agents response shape: expected a list")
        return [AgentSummary.model_validate(item) for item in data]

    async def get(self, agent_id: str) -> dict[str, Any]:
        """Get an agent, including its owning ``organization_id``."""
        body = await self._t.request("GET", f"/agents/{agent_id}")
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected agent response shape")
        return data

    async def get_temporary_config(self, agent_id: str) -> dict[str, Any]:
        """Get the temporary configuration model payload for ``agent_id``."""
        body = await self._t.request("GET", f"/agents/{agent_id}/configs/temporary")
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected temporary config response shape")
        return data

    async def export_temporary_config(self, agent_id: str) -> dict[str, Any]:
        """Export temporary config JSON in the import-compatible shape."""
        temporary = await self.get_temporary_config(agent_id)
        config_id = config_id_from_temporary(temporary)
        body = await self._t.request(
            "GET", f"/agents/{agent_id}/configs/{config_id}/config?include_ids=true"
        )
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected exported config response shape")
        return data

    async def update_temporary_config(
        self, agent_id: str, config_json: dict[str, Any]
    ) -> dict[str, Any]:
        """Update temporary config using JSON payload produced from YAML."""
        return await self._t.request(
            "PATCH",
            f"/agents/{agent_id}/configs/temporary",
            json={"config_json": config_json},
        )

    async def save_config(self, agent_id: str, version_name: str) -> SavedConfig:
        """Save the current temporary config as a named version.

        Calls ``POST /agents/{agent_id}/configs`` and returns the persisted
        :class:`~xmagic.client.models.SavedConfig` whose ``id`` is needed for
        the subsequent deploy call.
        """
        body = await self._t.request(
            "POST",
            f"/agents/{agent_id}/configs",
            json={"version_name": version_name},
        )
        data = unwrap_data(body)
        if not isinstance(data, dict):
            raise ResponseShapeError("Unexpected save config response shape")
        return SavedConfig.model_validate(data)

    async def deploy_config(self, agent_id: str, config_id: str) -> None:
        """Deploy a saved config version.

        Calls ``POST /agents/{agent_id}/configs/{config_id}/deploy``.
        """
        await self._t.request("POST", f"/agents/{agent_id}/configs/{config_id}/deploy")

    async def list_subagents(self, agent_id: str, config_id: str) -> list[SubagentSummary]:
        """List subagents belonging to the given config.

        Calls ``GET /agents/{agent_id}/configs/{config_id}/jobs``.
        """
        body = await self._t.request("GET", f"/agents/{agent_id}/configs/{config_id}/jobs")
        data = unwrap_data(body)
        if not isinstance(data, list):
            raise ResponseShapeError("Unexpected /jobs response shape: expected a list")
        return [SubagentSummary.model_validate(item) for item in data]
