"""The error contract callers actually program against.

Three things are pinned here: which status maps to which class, that a failure
which never reached the server is still an `XMagicError`, and that the response
behind an error stays reachable for debugging.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

import xmagic
from xmagic import XMagicClient
from xmagic.config import DEFAULT_BASE_URL
from xmagic.errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    XMagicAPIError,
    XMagicError,
    error_for_status,
)

URL = f"{DEFAULT_BASE_URL}/agents/agent-1/chats"


def _client(**kw: object) -> XMagicClient:
    return XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL, max_retries=0, **kw)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (429, RateLimitError),
        (500, ServerError),
        (502, ServerError),
        (503, ServerError),
        (504, ServerError),
    ],
)
def test_status_maps_to_its_typed_error(status: int, expected: type[XMagicAPIError]) -> None:
    assert type(error_for_status(status, None, "boom")) is expected


def test_unmapped_4xx_falls_back_to_the_base_class() -> None:
    """A status we have never seen must still be catchable, not a KeyError."""
    error = error_for_status(418, None, "teapot")

    assert type(error) is XMagicAPIError
    assert error.status_code == 418


def test_unmapped_5xx_is_a_server_error() -> None:
    """The map lists no 507, but a backend fault should still read as one."""
    assert isinstance(error_for_status(507, None, "insufficient storage"), ServerError)


@respx.mock
def test_403_reaches_the_caller_as_permission_denied() -> None:
    respx.post(URL).mock(return_value=Response(403, json={"message": "not your workspace"}))

    with _client() as client, pytest.raises(PermissionDeniedError) as exc:
        client.chats.create("agent-1")

    assert exc.value.status_code == 403
    assert "not your workspace" in str(exc.value)


@respx.mock
def test_exhausted_5xx_retries_raise_server_error() -> None:
    """Previously a bare XMagicAPIError, which no caller could single out."""
    respx.post(URL).mock(return_value=Response(503, json={"message": "upstream down"}))

    with _client() as client, pytest.raises(ServerError) as exc:
        client.chats.create("agent-1")

    assert exc.value.status_code == 503


@respx.mock
def test_api_error_exposes_the_response_for_debugging() -> None:
    respx.post(URL).mock(
        return_value=Response(
            400,
            headers={"x-request-id": "req-abc123"},
            json={"error_code": "INVALID_AGENT", "message": "no such agent"},
        )
    )

    with _client() as client, pytest.raises(BadRequestError) as exc:
        client.chats.create("agent-1")

    error = exc.value
    assert error.error_code == "INVALID_AGENT"
    assert error.message == "no such agent"
    assert error.request_id == "req-abc123"
    assert error.headers is not None
    assert error.headers["x-request-id"] == "req-abc123"
    assert error.body is not None
    assert "no such agent" in error.body
    assert error.response is not None
    assert error.response.status_code == 400


def test_response_details_are_none_when_there_is_no_response() -> None:
    """Streamed error frames arrive inside a 200 body, with no error response."""
    error = XMagicAPIError(200, "STREAM_ERROR", "agent failed mid-answer")

    assert error.response is None
    assert error.headers is None
    assert error.body is None
    assert error.request_id is None


@respx.mock
def test_request_id_is_none_when_no_known_header_is_present() -> None:
    respx.post(URL).mock(return_value=Response(400, json={"message": "nope"}))

    with _client() as client, pytest.raises(BadRequestError) as exc:
        client.chats.create("agent-1")

    assert exc.value.request_id is None


@respx.mock
def test_timeouts_are_typed_and_name_the_setting_to_raise() -> None:
    """A timeout should tell the caller which knob to turn."""
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("timed out"))

    with _client() as client, pytest.raises(APITimeoutError) as exc:
        client.chats.create("agent-1")

    assert isinstance(exc.value, APIConnectionError)  # catchable as the broader case
    assert "timeout" in str(exc.value)


def test_every_public_error_is_exported_at_the_package_root() -> None:
    """`from xmagic import ...` must cover the errors callers have to catch.

    ConfigurationError especially: it is what `XMagicClient()` raises on the
    most likely first-run failure, a missing API key.
    """
    for name in (
        "XMagicError",
        "XMagicAPIError",
        "ConfigurationError",
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "RateLimitError",
        "ServerError",
        "APIConnectionError",
        "APITimeoutError",
        "ChatType",
    ):
        assert name in xmagic.__all__, f"{name} missing from xmagic.__all__"
        assert getattr(xmagic, name, None) is not None


def test_configuration_error_is_catchable_from_the_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path) + "/absent.toml")

    with pytest.raises(xmagic.ConfigurationError):
        XMagicClient()


def test_every_sdk_error_derives_from_xmagic_error() -> None:
    """One `except XMagicError` should be enough to contain the SDK."""
    for cls in (
        xmagic.XMagicAPIError,
        xmagic.ConfigurationError,
        xmagic.APIConnectionError,
        xmagic.APITimeoutError,
        xmagic.ServerError,
    ):
        assert issubclass(cls, XMagicError)
