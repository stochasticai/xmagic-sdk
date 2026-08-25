"""Timeout behavior for streamed responses.

An agent that thinks for a while between tokens must not look like a network
fault. `settings.timeout` bounds a whole unary call; on a stream the read
timeout applies to the gap between events, so the two cannot be the same number.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.client.http import _stream_timeout
from xmagic.config import DEFAULT_BASE_URL, Settings
from xmagic.errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    XMagicAPIError,
    XMagicError,
)

QUERY_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query"


def _client(**kw: object) -> XMagicClient:
    return XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL, **kw)


def test_stream_timeout_relaxes_only_the_read_bound() -> None:
    timeout = _stream_timeout(Settings(api_key="k", timeout=60.0, stream_timeout=300.0))

    assert timeout.read == 300.0
    # Connecting and writing are not the slow part; they keep the normal bound.
    assert timeout.connect == 60.0
    assert timeout.write == 60.0
    assert timeout.pool == 60.0


def test_stream_timeout_of_none_waits_forever() -> None:
    timeout = _stream_timeout(Settings(api_key="k", timeout=60.0, stream_timeout=None))

    assert timeout.read is None
    assert timeout.connect == 60.0


def test_default_stream_timeout_is_longer_than_the_request_timeout() -> None:
    """The regression this guards: streams inheriting the 60s request timeout."""
    settings = Settings(api_key="k")

    assert settings.stream_timeout is not None
    assert settings.stream_timeout > settings.timeout


@respx.mock
def test_stream_sends_the_stream_timeout(sse_body: str) -> None:
    captured: list[dict[str, float | None]] = []

    def _record(request: httpx.Request) -> Response:
        captured.append(request.extensions["timeout"])
        return Response(200, headers={"content-type": "text/event-stream"}, text=sse_body)

    respx.post(QUERY_URL).mock(side_effect=_record)

    with _client(stream_timeout=120.0) as client:
        list(client.chats.stream("agent-1", "chat-1", "hello"))

    # httpx normalizes Timeout into an extensions dict of per-phase seconds.
    assert captured == [{"connect": 60.0, "read": 120.0, "write": 60.0, "pool": 60.0}]


@respx.mock
def test_a_unary_request_keeps_the_ordinary_read_deadline() -> None:
    """The other half of the invariant, and the half nothing was pinning.

    Relaxing the read bound is only correct for streams: one request/response
    still has to finish inside `timeout`. Without this, `_stream_timeout`
    leaking onto the unary path would fail no test — recovered from the closed
    #25, whose fix was superseded by #26 but whose reasoning here was not.
    """
    captured: list[dict[str, float | None]] = []

    def _record(request: httpx.Request) -> Response:
        captured.append(request.extensions["timeout"])
        return Response(200, json={"data": {"chat": {"id": "chat-1"}}})

    respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats").mock(side_effect=_record)

    with _client(timeout=7.0, stream_timeout=300.0) as client:
        client.chats.create("agent-1")

    assert captured == [{"connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0}]


@respx.mock
def test_mid_stream_timeout_is_typed_and_names_stream_timeout() -> None:
    """The failure this whole setting exists for, reported in the caller's terms."""
    respx.post(QUERY_URL).mock(side_effect=httpx.ReadTimeout("no data"))

    with _client() as client, pytest.raises(APITimeoutError) as exc:
        list(client.chats.stream("agent-1", "chat-1", "hello"))

    assert "stream_timeout" in str(exc.value)


@pytest.mark.parametrize(
    ("failure", "knob"),
    [
        (httpx.ReadTimeout("no data"), "stream_timeout"),
        (httpx.ConnectTimeout("no route"), "timeout"),
        (httpx.PoolTimeout("no free connection"), "timeout"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
@respx.mock
def test_a_stream_timeout_names_the_knob_that_governs_it(
    failure: httpx.TimeoutException, knob: str
) -> None:
    """Only `read` uses `stream_timeout`; connect/write/pool stay on `timeout`.

    Naming `stream_timeout` for a connect timeout would send the caller to a
    setting that cannot affect it, however long they make it.
    """
    respx.post(QUERY_URL).mock(side_effect=failure)

    with _client() as client, pytest.raises(APITimeoutError) as exc:
        list(client.chats.stream("agent-1", "chat-1", "hello"))

    assert f"Raise {knob} " in str(exc.value)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (429, RateLimitError),
        (503, ServerError),
    ],
)
def test_error_status_on_a_stream_raises_the_same_error_as_a_unary_call(
    status: int, expected: type[XMagicAPIError]
) -> None:
    """A stream that fails before it starts is an API error, not a network one.

    `connect_sse` checks only the content type, so these used to arrive as
    `SSEError` complaining about `application/json` -- the symptom, from the
    wrong exception tree. A 401 is a 401 whether or not you asked for a stream.
    """
    with respx.mock:
        respx.post(QUERY_URL).mock(
            return_value=Response(status, json={"message": "denied"}),
        )
        with _client(max_retries=0) as client, pytest.raises(expected) as exc:
            list(client.chats.stream("agent-1", "chat-1", "hello"))

    assert exc.value.status_code == status
    assert "denied" in str(exc.value)
    assert exc.value.body is not None  # the body was read despite streaming


@respx.mock
def test_error_status_on_a_stream_is_not_reported_as_unreachable() -> None:
    """Guards the specific mislabel: an auth failure claiming we never connected."""
    respx.post(QUERY_URL).mock(return_value=Response(401, json={"message": "bad key"}))

    with _client(max_retries=0) as client, pytest.raises(XMagicAPIError) as exc:
        list(client.chats.stream("agent-1", "chat-1", "hello"))

    assert not isinstance(exc.value, APIConnectionError)
    assert "Could not reach" not in str(exc.value)


@respx.mock
def test_a_2xx_that_is_not_an_event_stream_says_so() -> None:
    """The server kept its status contract and broke its content one."""
    respx.post(QUERY_URL).mock(return_value=Response(200, json={"data": "not a stream"}))

    with _client() as client, pytest.raises(XMagicError) as exc:
        list(client.chats.stream("agent-1", "chat-1", "hello"))

    assert not isinstance(exc.value, APIConnectionError)
    assert "non-SSE body" in str(exc.value)


async def test_async_stream_reports_error_statuses_the_same_way() -> None:
    """The two transports must not disagree about what a failed stream is."""
    with respx.mock:
        respx.post(QUERY_URL).mock(return_value=Response(401, json={"message": "bad key"}))
        async with AsyncXMagicClient(
            api_key="test-key", base_url=DEFAULT_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(AuthenticationError) as exc:
                [event async for event in client.chats.stream("agent-1", "chat-1", "hello")]

    assert exc.value.status_code == 401
    assert "bad key" in str(exc.value)


@pytest.fixture
def sse_body() -> str:
    return 'event: message\ndata: {"type": "response", "content": "hi"}\n\ndata: [DONE]\n\n'
