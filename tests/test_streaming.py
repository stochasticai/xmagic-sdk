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

from xmagic import XMagicClient
from xmagic.client.http import _stream_timeout
from xmagic.config import DEFAULT_BASE_URL, Settings
from xmagic.errors import APITimeoutError

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
def test_mid_stream_timeout_is_typed_and_names_stream_timeout() -> None:
    """The failure this whole setting exists for, reported in the caller's terms."""
    respx.post(QUERY_URL).mock(side_effect=httpx.ReadTimeout("no data"))

    with _client() as client, pytest.raises(APITimeoutError) as exc:
        list(client.chats.stream("agent-1", "chat-1", "hello"))

    assert "stream_timeout" in str(exc.value)


@pytest.fixture
def sse_body() -> str:
    return 'event: message\ndata: {"type": "response", "content": "hi"}\n\ndata: [DONE]\n\n'
