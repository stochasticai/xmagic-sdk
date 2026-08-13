"""Typed error hierarchy mirroring the xMagic API error contract.

The API returns errors as ``{"error_code": ..., "message": ...}`` with HTTP
status codes 400 (invalid input), 401 (auth), 404 (not found), 429 (rate limit).
Statuses the reference does not document still arrive typed: 403 as
:class:`PermissionDeniedError`, and any 5xx as :class:`ServerError`, so callers
can tell a backend fault from their own mistake without reading ``status_code``.

Failures that never produced a response — DNS, TCP, TLS, timeouts — raise
:class:`APIConnectionError` rather than leaking ``httpx`` exceptions, so callers
can catch :class:`XMagicError` alone and not depend on our transport.
"""

from __future__ import annotations

import httpx

# Checked in order. None of these is documented; the lookup is best-effort, and
# ``request_id`` is None when the response carries no header we recognize.
_REQUEST_ID_HEADERS = ("x-request-id", "request-id", "x-correlation-id")


class XMagicError(Exception):
    """Base class for all SDK errors."""


class ConfigurationError(XMagicError):
    """Missing/invalid configuration (e.g. no API key)."""


class APIConnectionError(XMagicError):
    """The request never produced a response (DNS, TCP, TLS, or timeout).

    The underlying ``httpx`` exception stays reachable as ``__cause__``. Retries
    are driven by HTTP status codes only, so this surfaces on the first failure
    rather than after the retry schedule.
    """


class APITimeoutError(APIConnectionError):
    """A request, or the gap between two stream events, exceeded its timeout.

    A subclass so that ``except APIConnectionError`` still covers it, since a
    timeout and an unreachable host usually call for the same handling.
    """


class XMagicAPIError(XMagicError):
    """An error response from the xMagic API.

    ``response`` is the raw ``httpx.Response`` when one is available, and is the
    source for :attr:`headers`, :attr:`body`, and :attr:`request_id`. It is
    optional because streamed error frames arrive inside an HTTP 200 body, where
    there is no error response to attach.
    """

    def __init__(
        self,
        status_code: int,
        error_code: str | None,
        message: str,
        *,
        response: httpx.Response | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.response = response
        super().__init__(f"[{status_code}{f'/{error_code}' if error_code else ''}] {message}")

    @property
    def headers(self) -> httpx.Headers | None:
        """Response headers, or None when the error carries no response."""
        return None if self.response is None else self.response.headers

    @property
    def body(self) -> str | None:
        """Raw response body as text, for errors whose shape we did not expect.

        None when there is no response, or when the body was never read — a
        streaming response that failed before being consumed has nothing to show.
        """
        if self.response is None:
            return None
        try:
            return self.response.text
        except httpx.ResponseNotRead:
            return None

    @property
    def request_id(self) -> str | None:
        """Server-side request id, when the response carries a header we know."""
        if self.response is None:
            return None
        for header in _REQUEST_ID_HEADERS:
            value: str | None = self.response.headers.get(header)
            if value:
                return value
        return None


class BadRequestError(XMagicAPIError):
    """400 — invalid input."""


class AuthenticationError(XMagicAPIError):
    """401 — invalid or missing x-api-key."""


class PermissionDeniedError(XMagicAPIError):
    """403 — authenticated, but not allowed to touch this resource."""


class NotFoundError(XMagicAPIError):
    """404 — unknown agent/chat/message."""


class RateLimitError(XMagicAPIError):
    """429 — plan rate limit exceeded (Free 20rpm / Pro 100 / Business 500)."""


class ServerError(XMagicAPIError):
    """5xx — a fault on the backend, raised once retries are exhausted."""


_STATUS_MAP: dict[int, type[XMagicAPIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    429: RateLimitError,
}


def error_for_status(
    status_code: int,
    error_code: str | None,
    message: str,
    *,
    response: httpx.Response | None = None,
) -> XMagicAPIError:
    """Map an HTTP status to the matching typed exception.

    Unmapped 5xx statuses become :class:`ServerError`; anything else unmapped
    falls back to :class:`XMagicAPIError`, so a status we have never seen is
    still catchable by the base class.
    """
    cls = _STATUS_MAP.get(status_code)
    if cls is None:
        cls = ServerError if status_code >= 500 else XMagicAPIError
    return cls(status_code, error_code, message, response=response)
