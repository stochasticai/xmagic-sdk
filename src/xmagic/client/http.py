"""HTTP transport: httpx client with x-api-key auth, retries, and SSE support.

Sync and async transports are deliberately kept side by side in this module and
share their auth, retry, and SSE-decoding logic, so the two cannot drift apart.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse, connect_sse

from xmagic.config import Settings
from xmagic.errors import APIConnectionError, ConfigurationError, error_for_status

_RETRYABLE = {429, 500, 502, 503, 504}

_MISSING_KEY = (
    "No xMagic API key found. Set XMAGIC_API_KEY, run `xmagic configure`, "
    "or pass api_key= explicitly. Keys: https://xmagic.ai -> profile -> API keys."
)


def _jittered(delay: float) -> float:
    """Spread retries so clients that failed together do not retry together.

    Equal jitter: half the delay, plus a random half. The result lands in
    ``[delay/2, delay]``, so a fleet that was rate-limited in lockstep comes
    back gradually rather than in one synchronised wave -- while never retrying
    *sooner* than half the nominal backoff, which full jitter would allow and
    which is the wrong direction to move against a server already saying no.

    Applied to our own backoff only. An explicit ``Retry-After`` is the server's
    instruction and is honoured exactly.
    """
    half = delay / 2
    return half + random.uniform(0, half)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before the next attempt.

    Prefers the server's ``Retry-After``, falling back to exponential backoff
    capped at 30s. RFC 9110 permits ``Retry-After`` to carry an HTTP-date as
    well as a delay in seconds; we do not parse dates, so anything we cannot
    read as a number degrades to the backoff schedule rather than raising
    mid-retry. A non-positive value is treated the same way.
    """
    backoff = _jittered(float(min(2**attempt, 30)))
    raw = response.headers.get("Retry-After")
    if not raw:
        return backoff
    try:
        seconds = float(raw)
    except ValueError:
        return backoff
    return seconds if seconds > 0 else backoff


_DONE = object()


def _decode_sse(data: str) -> Any:
    """Decode one SSE ``data:`` payload.

    Returns the ``_DONE`` sentinel for the ``[DONE]`` terminator, the parsed
    JSON object for a JSON frame, or the raw string otherwise.
    """
    if data.strip() == "[DONE]":
        return _DONE
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data


def _client_kwargs(settings: Settings) -> dict[str, Any]:
    if not settings.api_key:
        raise ConfigurationError(_MISSING_KEY)
    return {
        "base_url": settings.base_url,
        "headers": {"x-api-key": settings.api_key},
        "timeout": settings.timeout,
    }


def _stream_timeout(settings: Settings) -> httpx.Timeout:
    """Timeouts for a streaming request.

    `settings.timeout` is a *unary* budget: how long one request/response may
    take. Applying its read timeout to an SSE stream measures the gap between
    tokens instead, so an agent that thinks for longer than 60s -- entirely
    normal for a reasoning model -- kills its own stream mid-answer.

    Connect, write and pool stay bounded. Read is unbounded, because there is no
    defensible value for "the agent has gone quiet for too long"; the caller
    ends the stream by ending iteration.
    """
    return httpx.Timeout(
        connect=settings.timeout,
        write=settings.timeout,
        pool=settings.timeout,
        read=None,
    )


def _result(response: httpx.Response) -> dict[str, Any]:
    """Raise a typed error for an error response, else return the parsed body."""
    if response.is_error:
        error_code, message = _parse_error(response)
        raise error_for_status(response.status_code, error_code, message)
    if not response.content:
        return {}
    return response.json()


def _raw(response: httpx.Response) -> bytes:
    """Raise a typed error for an error response, else return the body bytes.

    The Drive ZIP export is the one documented endpoint that answers
    ``application/zip`` rather than JSON, so it cannot go through ``_result``.
    Error responses are still JSON, so error handling is unchanged.
    """
    if response.is_error:
        error_code, message = _parse_error(response)
        raise error_for_status(response.status_code, error_code, message)
    return response.content


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
        self.settings = settings
        self._client = httpx.Client(**_client_kwargs(settings))

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Issue a request; return the parsed JSON body. Raises XMagicAPIError."""
        return _result(self._send(method, path, **kwargs))

    def request_bytes(self, method: str, path: str, **kwargs: Any) -> bytes:
        """Issue a request; return the raw body. For non-JSON responses."""
        return _raw(self._send(method, path, **kwargs))

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """The retry loop, shared by every response shape."""
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.HTTPError as e:
                raise APIConnectionError(f"{type(e).__name__}: {e}") from e
            if response.status_code in _RETRYABLE and attempt < self.settings.max_retries:
                time.sleep(_retry_delay(response, attempt))
                continue
            break
        return response

    def sse(self, method: str, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Stream Server-Sent Events, yielding parsed JSON payloads.

        Yields ``{"event": <name>, "data": <parsed json or str>}`` and stops at
        the ``[DONE]`` terminator.
        """
        kwargs.setdefault("timeout", _stream_timeout(self.settings))
        with connect_sse(self._client, method, path, **kwargs) as source:
            for sse in source.iter_sse():
                data = _decode_sse(sse.data)
                if data is _DONE:
                    yield {"event": "done", "data": ""}
                    return
                yield {"event": sse.event or "message", "data": data}

    def close(self) -> None:
        self._client.close()


class AsyncHttpTransport:
    """Async mirror of :class:`HttpTransport`.

    Same auth, same retry schedule, same SSE decoding — only the awaiting
    differs. Backoff uses ``asyncio.sleep``, so waiting on a rate limit does not
    block the event loop.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(**_client_kwargs(settings))

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Issue a request; return the parsed JSON body. Raises XMagicAPIError."""
        return _result(await self._send(method, path, **kwargs))

    async def request_bytes(self, method: str, path: str, **kwargs: Any) -> bytes:
        """Issue a request; return the raw body. For non-JSON responses."""
        return _raw(await self._send(method, path, **kwargs))

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """The retry loop, shared by every response shape."""
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.HTTPError as e:
                raise APIConnectionError(f"{type(e).__name__}: {e}") from e
            if response.status_code in _RETRYABLE and attempt < self.settings.max_retries:
                await asyncio.sleep(_retry_delay(response, attempt))
                continue
            break
        return response

    async def sse(self, method: str, path: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Stream Server-Sent Events, yielding parsed JSON payloads.

        Yields ``{"event": <name>, "data": <parsed json or str>}`` and stops at
        the ``[DONE]`` terminator.
        """
        kwargs.setdefault("timeout", _stream_timeout(self.settings))
        async with aconnect_sse(self._client, method, path, **kwargs) as source:
            async for sse in source.aiter_sse():
                data = _decode_sse(sse.data)
                if data is _DONE:
                    yield {"event": "done", "data": ""}
                    return
                yield {"event": sse.event or "message", "data": data}

    async def aclose(self) -> None:
        await self._client.aclose()
