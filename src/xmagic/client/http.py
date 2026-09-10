"""HTTP transport: httpx client with x-api-key auth, retries, and SSE support.

Sync and async transports are deliberately kept side by side in this module and
share their auth, retry, and SSE-decoding logic, so the two cannot drift apart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import random
import time
from collections.abc import AsyncGenerator, Generator
from typing import Any, cast

import httpx
from httpx_sse import SSEError, aconnect_sse, connect_sse

from xmagic._version import __version__
from xmagic.config import Settings
from xmagic.errors import (
    _REQUEST_ID_HEADERS,
    APIConnectionError,
    APITimeoutError,
    ConfigurationError,
    XMagicAPIError,
    XMagicError,
    error_for_status,
)

log = logging.getLogger("xmagic.http")

_RETRYABLE = {429, 500, 502, 503, 504}

USER_AGENT = (
    f"xmagic-sdk/{__version__} python/{platform.python_version()} httpx/{httpx.__version__}"
)
"""Sent on every request, so the server can tell which SDK version is talking."""

_MISSING_KEY = (
    "No xMagic API key found. Set XMAGIC_API_KEY, run `xmagic configure`, "
    "or pass api_key= explicitly. Keys: https://xmagic.ai -> profile -> API keys."
)


def _backoff(attempt: int) -> float:
    """Exponential backoff with equal jitter, capped at 30s.

    Returns a delay drawn uniformly from the upper half of the schedule —
    ``[ceiling/2, ceiling]`` — so clients that failed together do not retry in
    lockstep, while the delay still grows and still never exceeds the cap.
    Equal jitter rather than full jitter (``uniform(0, ceiling)``) keeps the
    first retry from landing almost immediately.
    """
    ceiling = float(min(2**attempt, 30))
    half = ceiling / 2
    return half + random.uniform(0, half)


def unwrap_data(body: dict[str, Any]) -> Any:
    """Return the API payload, whether it is wrapped in a ``data`` key or not."""
    return body.get("data", body)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before the next attempt.

    Prefers the server's ``Retry-After``, falling back to jittered exponential
    backoff. ``Retry-After`` is honored verbatim and deliberately *not* jittered:
    the server named a time, and second-guessing it is how you get told off
    twice. RFC 9110 permits ``Retry-After`` to carry an HTTP-date as well as a
    delay in seconds; we do not parse dates, so anything we cannot read as a
    number degrades to the backoff schedule rather than raising mid-retry. A
    non-positive value is treated the same way.
    """
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            seconds = float(raw)
        except ValueError:
            return _backoff(attempt)
        if seconds > 0:
            return seconds
    return _backoff(attempt)


def _stream_api_error(response: httpx.Response) -> XMagicAPIError:
    """The typed error for an error status on a streaming request.

    ``connect_sse`` validates only the content type, so without this check a 401
    on a stream surfaces as ``SSEError("Expected ... 'text/event-stream', got
    'application/json'")`` — a description of the symptom, from the wrong
    exception tree, for what is really an auth failure.
    """
    error_code, message = _parse_error(response)
    return error_for_status(response.status_code, error_code, message, response=response)


def _stream_error(response: httpx.Response) -> None:
    """Raise if a streaming response carries an error status.

    The body has to be read explicitly: a streaming response has buffered
    nothing yet, so ``_parse_error`` would have no content to work with.
    """
    if not response.is_error:
        return
    response.read()
    raise _stream_api_error(response)


async def _astream_error(response: httpx.Response) -> None:
    """Async mirror of :func:`_stream_error`; only the body read differs."""
    if not response.is_error:
        return
    await response.aread()
    raise _stream_api_error(response)


def _protocol_error(exc: SSEError, base_url: str) -> XMagicError:
    """A 2xx that is not an event stream — the server broke the contract.

    Distinct from :class:`APIConnectionError`, which would claim we never got
    through when in fact we got a perfectly good response of the wrong kind.
    """
    return XMagicError(f"{base_url} answered a stream request with a non-SSE body: {exc}")


def _transport_error(
    exc: httpx.RequestError, base_url: str, *, streaming: bool = False
) -> APIConnectionError:
    """Translate an httpx request failure into the SDK's own error type.

    Callers should not have to know we use httpx, nor catch two exception trees
    to handle "the request did not get through". The original stays as
    ``__cause__``.

    Typed from ``RequestError`` rather than ``TransportError`` because the two
    are not the same set: ``DecodingError`` (a corrupt compressed body) and
    ``TooManyRedirects`` are request errors but not transport errors, and
    catching only the latter let them escape as raw httpx exceptions.
    """
    detail = str(exc) or type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        return APITimeoutError(
            f"Timed out talking to {base_url} ({detail}). "
            f"Raise {_timeout_knob(exc, streaming=streaming)} if the agent "
            f"legitimately needs longer."
        )
    return APIConnectionError(f"Could not reach {base_url} ({detail}).")


def _timeout_knob(exc: httpx.TimeoutException, *, streaming: bool) -> str:
    """The setting that actually governs this timeout.

    Only the *read* deadline differs between streaming and unary requests
    (see :func:`_stream_timeout`); connect, write and pool stay on ``timeout``
    either way. Naming ``stream_timeout`` for a connect timeout would send the
    caller to a knob that cannot affect it.
    """
    if streaming and isinstance(exc, httpx.ReadTimeout):
        return "stream_timeout"
    return "timeout"


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
        "headers": {"x-api-key": settings.api_key, "User-Agent": USER_AGENT},
        "timeout": settings.timeout,
    }


def _log_request(method: str, path: str, *, streaming: bool = False) -> float:
    """One DEBUG line per attempt; returns the start time for the response line."""
    log.debug("%s %s%s", method, path, " (stream)" if streaming else "")
    return time.monotonic()


def _log_response(method: str, path: str, response: httpx.Response, started: float) -> None:
    """Status and elapsed time, plus the server's request id when it sent one.

    Never headers and never bodies: the request carries the API key and the
    response may carry the user's data, and neither belongs in a log file.
    """
    # The same lookup `XMagicAPIError.request_id` does, so a line here and an
    # error there name the same id.
    request_id = next(
        (response.headers[h] for h in _REQUEST_ID_HEADERS if response.headers.get(h)), None
    )
    log.debug(
        "%s %s -> %d in %.0fms%s",
        method,
        path,
        response.status_code,
        (time.monotonic() - started) * 1000,
        f" (request id {request_id})" if request_id else "",
    )


def _log_retry(
    method: str, path: str, response: httpx.Response, delay: float, attempt: int, max_retries: int
) -> None:
    """INFO rather than DEBUG: a retry is the one thing worth hearing about by default."""
    log.info(
        "%s %s returned %d; retrying in %.1fs (attempt %d of %d)",
        method,
        path,
        response.status_code,
        delay,
        attempt + 1,
        max_retries,
    )


def _stream_timeout(settings: Settings) -> httpx.Timeout:
    """Timeout for a streaming request.

    Streams need a different read timeout from unary calls: ``settings.timeout``
    bounds a whole request/response, but on a stream the read timeout applies to
    the gap *between events*, so an agent that thinks for longer than it would
    raise ``ReadTimeout`` mid-answer. Connect/write/pool keep the normal bound —
    only reading is allowed to be slow. ``stream_timeout=None`` waits forever.
    """
    return httpx.Timeout(settings.timeout, read=settings.stream_timeout)


def _result(response: httpx.Response) -> dict[str, Any]:
    """Raise a typed error for an error response, else return the parsed body."""
    if response.is_error:
        error_code, message = _parse_error(response)
        raise error_for_status(response.status_code, error_code, message, response=response)
    if not response.content:
        return {}
    # `.json()` is Any by construction; the shape is pinned by the contract tests
    # against recorded fixtures rather than by the type system.
    return cast("dict[str, Any]", response.json())


def _raw(response: httpx.Response) -> bytes:
    """Raise a typed error for an error response, else return the body bytes.

    The Drive ZIP export is the one documented endpoint that answers
    ``application/zip`` rather than JSON, so it cannot go through ``_result``.
    Error responses are still JSON, so error handling is unchanged.
    """
    if response.is_error:
        error_code, message = _parse_error(response)
        raise error_for_status(response.status_code, error_code, message, response=response)
    return response.content


def _parse_error(response: httpx.Response) -> tuple[str | None, str]:
    try:
        body = response.json()
        err = body.get("error", body)
        if not isinstance(err, dict):
            return None, response.text
        detail = err.get("detail")
        message = err.get("message") or detail or response.text
        if isinstance(detail, list):
            message = "; ".join(str(item) for item in detail)
        return err.get("error_code"), str(message)
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
            started = _log_request(method, path)
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.RequestError as e:
                raise _transport_error(e, self.settings.base_url) from e
            _log_response(method, path, response, started)
            if response.status_code in _RETRYABLE and attempt < self.settings.max_retries:
                delay = _retry_delay(response, attempt)
                _log_retry(method, path, response, delay, attempt, self.settings.max_retries)
                time.sleep(delay)
                continue
            break
        return response

    def sse(self, method: str, path: str, **kwargs: Any) -> Generator[dict[str, Any], None, None]:
        """Stream Server-Sent Events, yielding parsed JSON payloads.

        Yields ``{"event": <name>, "data": <parsed json or str>}`` and stops at
        the ``[DONE]`` terminator. Typed as the generator it is, because its
        ``close()`` is part of the contract: it raises ``GeneratorExit`` at the
        suspended ``yield``, which exits the ``with`` below and closes the
        response at that moment (see ``client/streaming.py``).
        """
        kwargs.setdefault("timeout", _stream_timeout(self.settings))
        started = _log_request(method, path, streaming=True)
        try:
            with connect_sse(self._client, method, path, **kwargs) as source:
                _log_response(method, path, source.response, started)
                _stream_error(source.response)
                for sse in source.iter_sse():
                    data = _decode_sse(sse.data)
                    if data is _DONE:
                        yield {"event": "done", "data": ""}
                        return
                    yield {"event": sse.event or "message", "data": data}
        except SSEError as e:  # a RequestError subclass, so it must come first
            raise _protocol_error(e, self.settings.base_url) from e
        except httpx.RequestError as e:
            raise _transport_error(e, self.settings.base_url, streaming=True) from e

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
            started = _log_request(method, path)
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.RequestError as e:
                raise _transport_error(e, self.settings.base_url) from e
            _log_response(method, path, response, started)
            if response.status_code in _RETRYABLE and attempt < self.settings.max_retries:
                delay = _retry_delay(response, attempt)
                _log_retry(method, path, response, delay, attempt, self.settings.max_retries)
                await asyncio.sleep(delay)
                continue
            break
        return response

    async def sse(
        self, method: str, path: str, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream Server-Sent Events, yielding parsed JSON payloads.

        Yields ``{"event": <name>, "data": <parsed json or str>}`` and stops at
        the ``[DONE]`` terminator.
        """
        kwargs.setdefault("timeout", _stream_timeout(self.settings))
        started = _log_request(method, path, streaming=True)
        try:
            async with aconnect_sse(self._client, method, path, **kwargs) as source:
                _log_response(method, path, source.response, started)
                await _astream_error(source.response)
                async for sse in source.aiter_sse():
                    data = _decode_sse(sse.data)
                    if data is _DONE:
                        yield {"event": "done", "data": ""}
                        return
                    yield {"event": sse.event or "message", "data": data}
        except SSEError as e:  # a RequestError subclass, so it must come first
            raise _protocol_error(e, self.settings.base_url) from e
        except httpx.RequestError as e:
            raise _transport_error(e, self.settings.base_url, streaming=True) from e

    async def aclose(self) -> None:
        await self._client.aclose()
