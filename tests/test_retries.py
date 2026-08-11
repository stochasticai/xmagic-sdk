"""Retry and backoff behavior for HttpTransport.

The README promises "retries 429 and 5xx with exponential backoff, honoring
Retry-After". These tests pin that contract. Sleeps are captured rather than
performed, so the suite stays fast and asserts on the *delays chosen*.

Backoff carries equal jitter, so the delays are ranges rather than exact values:
each one lands in ``[ceiling/2, ceiling]`` for that attempt's ceiling. Asserting
the ceilings alone would pass against un-jittered code, so
``test_backoff_jitter_varies_between_calls`` pins the spread too.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from xmagic import XMagicClient
from xmagic.client.http import _backoff
from xmagic.config import DEFAULT_BASE_URL
from xmagic.errors import APIConnectionError, BadRequestError, RateLimitError, XMagicAPIError

URL = f"{DEFAULT_BASE_URL}/agents/agent-1/chats"

# min(2**attempt, 30): doubles to 16, then flattens at the 30s ceiling.
CEILINGS = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def _assert_jittered(sleeps: list[float], ceilings: list[float]) -> None:
    """Assert one delay per ceiling, each in the upper half of its window."""
    assert len(sleeps) == len(ceilings), f"{sleeps} does not match {ceilings}"
    for delay, ceiling in zip(sleeps, ceilings, strict=True):
        assert ceiling / 2 <= delay <= ceiling, f"{delay} outside [{ceiling / 2}, {ceiling}]"


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture every backoff delay instead of sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr("xmagic.client.http.time.sleep", recorded.append)
    return recorded


def _client(**kw: object) -> XMagicClient:
    return XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL, **kw)


@respx.mock
def test_429_retries_and_then_succeeds(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            Response(429, json={"message": "slow down"}),
            Response(200, json={"data": {"chat": {"id": "chat-1"}}}),
        ]
    )

    with _client() as client:
        chat = client.chats.create("agent-1")

    assert chat.id == "chat-1"
    assert route.call_count == 2
    _assert_jittered(sleeps, CEILINGS[:1])


@respx.mock
def test_retry_after_header_overrides_exponential_backoff(sleeps: list[float]) -> None:
    respx.post(URL).mock(
        side_effect=[
            Response(429, headers={"Retry-After": "7"}, json={}),
            Response(200, json={"data": {"chat": {"id": "chat-1"}}}),
        ]
    )

    with _client() as client:
        client.chats.create("agent-1")

    # 7 from the header, not the 1s the backoff schedule would have chosen.
    assert sleeps == [7.0]


@respx.mock
def test_backoff_is_exponential_without_retry_after(sleeps: list[float]) -> None:
    respx.post(URL).mock(return_value=Response(503, json={}))

    with _client() as client, pytest.raises(XMagicAPIError) as exc:
        client.chats.create("agent-1")

    assert exc.value.status_code == 503
    # max_retries=3 -> 4 attempts, 3 sleeps, each window doubling.
    _assert_jittered(sleeps, CEILINGS[:3])


@respx.mock
def test_http_date_retry_after_falls_back_to_backoff(sleeps: list[float]) -> None:
    """RFC 9110 allows an HTTP-date in Retry-After, not only a delay in seconds.

    We do not parse dates; the contract is that an unparseable value degrades to
    the normal backoff schedule rather than raising ValueError mid-retry.
    """
    respx.post(URL).mock(
        side_effect=[
            Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, json={}),
            Response(200, json={"data": {"chat": {"id": "chat-1"}}}),
        ]
    )

    with _client() as client:
        chat = client.chats.create("agent-1")

    assert chat.id == "chat-1"
    _assert_jittered(sleeps, CEILINGS[:1])


@respx.mock
def test_retries_exhausted_raises_typed_error(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(
        return_value=Response(429, json={"message": "rate limit exceeded"})
    )

    with _client(max_retries=2) as client, pytest.raises(RateLimitError) as exc:
        client.chats.create("agent-1")

    assert exc.value.status_code == 429
    assert "rate limit exceeded" in str(exc.value)
    assert route.call_count == 3  # initial attempt + 2 retries
    _assert_jittered(sleeps, CEILINGS[:2])


@respx.mock
def test_4xx_is_not_retried(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(return_value=Response(400, json={"message": "bad agent id"}))

    with _client() as client, pytest.raises(BadRequestError):
        client.chats.create("agent-1")

    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_max_retries_zero_disables_retrying(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(return_value=Response(429, json={}))

    with _client(max_retries=0) as client, pytest.raises(RateLimitError):
        client.chats.create("agent-1")

    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_backoff_delay_is_capped(sleeps: list[float]) -> None:
    respx.post(URL).mock(return_value=Response(500, json={}))

    with _client(max_retries=8) as client, pytest.raises(XMagicAPIError):
        client.chats.create("agent-1")

    _assert_jittered(sleeps, CEILINGS)


def test_backoff_jitter_varies_between_calls() -> None:
    """The delay for a given attempt must not be a constant.

    Without this, every other assertion here would still pass against the old
    deterministic `min(2**attempt, 30)` — the point of jitter is the spread.
    """
    delays = {_backoff(3) for _ in range(50)}

    assert len(delays) > 1, "backoff is deterministic; clients will retry in lockstep"
    assert all(4.0 <= d <= 8.0 for d in delays)


@respx.mock
def test_connection_errors_surface_as_a_typed_sdk_error(sleeps: list[float]) -> None:
    """Transport failures are wrapped, not leaked, and never retried.

    Callers should be able to catch `XMagicError` alone rather than also
    importing httpx; only HTTP status codes drive retries.
    """
    respx.post(URL).mock(side_effect=httpx.ConnectError("no route to host"))

    with _client() as client, pytest.raises(APIConnectionError) as exc:
        client.chats.create("agent-1")

    assert "no route to host" in str(exc.value)
    assert isinstance(exc.value.__cause__, httpx.ConnectError)
    assert sleeps == []
