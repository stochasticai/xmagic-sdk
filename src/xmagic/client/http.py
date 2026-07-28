"""HTTP transport: httpx client with x-api-key auth, retries, and SSE support."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
from httpx_sse import connect_sse

from xmagic.config import Settings
from xmagic.errors import ConfigurationError, error_for_status

_RETRYABLE = {429, 500, 502, 503, 504}


def _parse_error(response: httpx.Response) -> tuple[str | None, str]:
    try:
        body = response.json()
        err = body.get("error", body)
        return err.get("error_code"), err.get("message", response.text)
    except (ValueError, AttributeError):
        # Body was not JSON (ValueError) or was JSON of an unexpected shape,
        # e.g. a list or bare string, so ``.get`` is absent (AttributeError).
        return None, response.text or response.reason_phrase


class HttpTransport:
    """Thin wrapper over httpx.Client with auth, retries, and SSE.

    Retries 429/5xx with exponential backoff, honoring ``Retry-After``.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise ConfigurationError(
                "No xMagic API key found. Set XMAGIC_API_KEY, run `xmagic configure`, "
                "or pass api_key= explicitly. Keys: https://xmagic.ai -> profile -> API keys."
            )
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers={"x-api-key": settings.api_key},
            timeout=settings.timeout,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Issue a request; return the parsed JSON body. Raises XMagicAPIError."""
        for attempt in range(self.settings.max_retries + 1):
            response = self._client.request(method, path, **kwargs)
            if response.status_code in _RETRYABLE and attempt < self.settings.max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2**attempt, 30)
                time.sleep(delay)
                continue
            break
        if response.is_error:
            error_code, message = _parse_error(response)
            raise error_for_status(response.status_code, error_code, message)
        if not response.content:
            return {}
        return response.json()

    def sse(self, method: str, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Stream Server-Sent Events, yielding parsed JSON payloads.

        Yields ``{"event": <name>, "data": <parsed json or str>}`` and stops at
        the ``[DONE]`` terminator.
        """
        with connect_sse(self._client, method, path, **kwargs) as source:
            for sse in source.iter_sse():
                if sse.data.strip() == "[DONE]":
                    yield {"event": "done", "data": ""}
                    return
                try:
                    data: Any = json.loads(sse.data)
                except json.JSONDecodeError:
                    data = sse.data
                yield {"event": sse.event or "message", "data": data}

    def close(self) -> None:
        self._client.close()
