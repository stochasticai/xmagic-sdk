"""Typed error hierarchy mirroring the xMagic API error contract.

The API returns errors as ``{"error_code": ..., "message": ...}`` with HTTP
status codes 400 (invalid input), 401 (auth), 404 (not found), 429 (rate limit).
"""

from __future__ import annotations


class XMagicError(Exception):
    """Base class for all SDK errors."""


class ConfigurationError(XMagicError):
    """Missing/invalid configuration (e.g. no API key)."""


class XMagicAPIError(XMagicError):
    """An error response from the xMagic API."""

    def __init__(self, status_code: int, error_code: str | None, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(f"[{status_code}{f'/{error_code}' if error_code else ''}] {message}")


class BadRequestError(XMagicAPIError):
    """400 — invalid input."""


class AuthenticationError(XMagicAPIError):
    """401 — invalid or missing x-api-key."""


class NotFoundError(XMagicAPIError):
    """404 — unknown agent/chat/message."""


class RateLimitError(XMagicAPIError):
    """429 — plan rate limit exceeded (Free 20rpm / Pro 100 / Business 500)."""


_STATUS_MAP: dict[int, type[XMagicAPIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    404: NotFoundError,
    429: RateLimitError,
}


def error_for_status(status_code: int, error_code: str | None, message: str) -> XMagicAPIError:
    """Map an HTTP status to the matching typed exception."""
    cls = _STATUS_MAP.get(status_code, XMagicAPIError)
    return cls(status_code, error_code, message)
