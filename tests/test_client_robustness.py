"""Edge behaviour of the transport: stream timeouts, error typing, exports.

These are the audit findings from 2026-08-05 that had no coverage at all. The
stream timeout in particular was a live bug rather than a latent one -- any agent
that paused longer than `settings.timeout` between tokens killed its own stream.
"""

from __future__ import annotations

import httpx
import pytest
import respx

import xmagic
from xmagic.client.http import _stream_timeout
from xmagic.config import DEFAULT_BASE_URL, Settings
from xmagic.errors import (
    APIConnectionError,
    PermissionDeniedError,
    ServerError,
    XMagicAPIError,
    XMagicError,
    error_for_status,
)

CHATS = f"{DEFAULT_BASE_URL}/agents/agent-1/chats"
QUERY = f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query"


class TestStreamTimeout:
    """`settings.timeout` is a unary budget; applying its read half to SSE is wrong."""

    def test_read_is_unbounded_while_the_rest_stay_bounded(self) -> None:
        timeout = _stream_timeout(Settings(api_key="k", timeout=60.0))

        # Read must be None: there is no defensible value for "the agent has
        # gone quiet for too long". A reasoning model may think for minutes.
        assert timeout.read is None
        # Everything else is still bounded -- an unreachable host must not hang.
        assert timeout.connect == 60.0
        assert timeout.write == 60.0
        assert timeout.pool == 60.0

    def test_it_tracks_the_configured_timeout(self) -> None:
        timeout = _stream_timeout(Settings(api_key="k", timeout=5.0))
        assert timeout.connect == 5.0
        assert timeout.read is None

    @respx.mock
    def test_streaming_requests_drop_the_read_deadline_unary_ones_keep_it(self) -> None:
        """The regression, asserted on the wire rather than on the clock.

        A mocked response arrives instantly, so no test can *experience* a slow
        stream -- an earlier version of this test passed with the fix reverted
        and therefore proved nothing. What is checkable is the timeout httpx
        actually attaches to each request, and the two must differ.
        """
        frames = 'data: {"type": "response", "text": "hi"}\n\ndata: [DONE]\n\n'
        create = respx.post(CHATS).mock(
            return_value=httpx.Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        query = respx.post(QUERY).mock(
            return_value=httpx.Response(
                200, text=frames, headers={"content-type": "text/event-stream"}
            )
        )

        with xmagic.XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL, timeout=7.0) as client:
            client.chats.create("agent-1")
            list(client.chats.stream("agent-1", "chat-1", "q"))

        unary = create.calls.last.request.extensions["timeout"]
        stream = query.calls.last.request.extensions["timeout"]

        # The unary budget is unchanged: one request/response must still finish.
        assert unary["read"] == 7.0
        # The stream must not measure the gap between tokens against it.
        assert stream["read"] is None
        # Everything else stays bounded on both.
        assert unary["connect"] == stream["connect"] == 7.0
        assert unary["write"] == stream["write"] == 7.0


class TestErrorTyping:
    """A caller should be able to tell "you were denied" from "the server broke"."""

    def test_403_is_its_own_type(self) -> None:
        assert isinstance(error_for_status(403, None, "nope"), PermissionDeniedError)

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
    def test_any_5xx_is_a_server_error(self, status: int) -> None:
        # Previously every 5xx surfaced as the bare base class, so "the server
        # failed" and "we don't recognise this status" were indistinguishable.
        error = error_for_status(status, None, "boom")
        assert isinstance(error, ServerError)
        assert error.status_code == status

    def test_an_unknown_4xx_stays_the_base_type(self) -> None:
        error = error_for_status(418, None, "teapot")
        assert isinstance(error, XMagicAPIError)
        assert not isinstance(error, ServerError)

    @respx.mock
    def test_exhausted_retries_on_503_raise_server_error(self) -> None:
        respx.post(CHATS).mock(return_value=httpx.Response(503, json={}))

        with (
            xmagic.XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL, max_retries=0) as client,
            pytest.raises(ServerError),
        ):
            client.chats.create("agent-1")

    @respx.mock
    async def test_the_async_transport_wraps_connection_errors_too(self) -> None:
        # Sync coverage lives in test_retries.py; the two transports duplicate
        # this logic, so the async half needs its own assertion.
        respx.post(CHATS).mock(side_effect=httpx.ConnectError("unreachable"))

        async with xmagic.AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
            with pytest.raises(APIConnectionError) as excinfo:
                await client.chats.create("agent-1")

        assert isinstance(excinfo.value, XMagicError)
        assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


class TestPublicExports:
    """Names a caller needs must be importable from the package root."""

    def test_the_first_run_failure_is_catchable_from_the_root(self) -> None:
        # `XMagicClient()` with no key raises ConfigurationError -- the single
        # most likely first-run error. It was not exported.
        from xmagic import ConfigurationError

        assert issubclass(ConfigurationError, XMagicError)

    def test_documented_parameter_types_are_exported(self) -> None:
        # ChatType is a documented argument of `chats.create`; requiring an
        # import from `xmagic.client.models` made a public type look private.
        assert xmagic.ChatType.STANDARD.value == "standard"

    @pytest.mark.parametrize(
        "name",
        [
            "APIConnectionError",
            "BadRequestError",
            "ChatType",
            "ConfigurationError",
            "PermissionDeniedError",
            "ServerError",
        ],
    )
    def test_new_names_are_in_dunder_all(self, name: str) -> None:
        assert name in xmagic.__all__
        assert hasattr(xmagic, name)
