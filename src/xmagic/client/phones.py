"""Phone number listing and association helpers.

Current backend contracts used here:

- GET  /phones
- POST /phones/{phone_id}
"""

from __future__ import annotations

from typing import Any

from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import PhoneSummary


def _unwrap_data(body: dict[str, Any]) -> Any:
    return body.get("data", body)


class PhonesAPI:
    """Phone number listing and association operations."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def list(self) -> list[PhoneSummary]:
        """List phone numbers belonging to the current organisation.

        Explicitly requests the organisation scope and ignores shared phone
        numbers returned by the endpoint.
        """
        body = self._t.request("GET", "/phones", params={"scope": "org"})
        data = _unwrap_data(body)
        if not isinstance(data, dict):
            raise ValueError("Unexpected /phones response shape")
        phones: list[dict[str, Any]] = data.get("org_phone_numbers", [])
        return [PhoneSummary.model_validate(p) for p in phones]

    def associate(
        self,
        phone_id: str,
        persona_id: str,
        subagent_id: str | None = None,
    ) -> None:
        """Associate ``phone_id`` with an agent, optionally scoped to a subagent.

        Calls ``POST /phones/{phone_id}`` with the agent id and, when provided,
        the ``id_shared_between_versions`` of the chosen subagent.
        """
        self._t.request(
            "POST",
            f"/phones/{phone_id}",
            json={
                "persona_id_associated_to": persona_id,
                "subagent_id_associated_to": subagent_id,
            },
        )


class AsyncPhonesAPI:
    """Async mirror of :class:`PhonesAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def list(self) -> list[PhoneSummary]:
        """List phone numbers belonging to the current organisation."""
        body = await self._t.request("GET", "/phones", params={"scope": "org"})
        data = _unwrap_data(body)
        if not isinstance(data, dict):
            raise ValueError("Unexpected /phones response shape")
        phones: list[dict[str, Any]] = data.get("org_phone_numbers", [])
        return [PhoneSummary.model_validate(p) for p in phones]

    async def associate(
        self,
        phone_id: str,
        persona_id: str,
        subagent_id: str | None = None,
    ) -> None:
        """Associate ``phone_id`` with an agent, optionally scoped to a subagent."""
        await self._t.request(
            "POST",
            f"/phones/{phone_id}",
            json={
                "persona_id_associated_to": persona_id,
                "subagent_id_associated_to": subagent_id,
            },
        )
