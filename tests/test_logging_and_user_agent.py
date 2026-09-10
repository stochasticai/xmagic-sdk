"""The client identifies itself, and says what it is doing when asked.

Two gaps closed together because they share a purpose -- making a failing call
inspectable. Before this there was no logging anywhere in the package, so the
only record of a request was the exception it ended in; and no `User-Agent`, so
the server could not tell one SDK version from another.

Logging follows the library convention: everything under the "xmagic" logger,
a `NullHandler` at the package root, nothing emitted unless the application
attaches a handler. Request and response lines are DEBUG, a retry is INFO, and
headers and bodies are never logged -- the request carries the API key.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

import xmagic
from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.cli.main import app
from xmagic.client.http import USER_AGENT
from xmagic.config import DEFAULT_BASE_URL

CHATS_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/chats"
STREAM_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query"
KEY = "xm-secret-key-do-not-log"

UA = re.compile(r"^xmagic-sdk/\S+ python/\d+\.\d+\.\d+ httpx/\S+$")


def _client(**kw: object) -> XMagicClient:
    return XMagicClient(api_key=KEY, base_url=DEFAULT_BASE_URL, **kw)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr("xmagic.client.http.time.sleep", recorded.append)
    return recorded


@pytest.fixture
def package_logger() -> Iterator[logging.Logger]:
    """Leave the "xmagic" logger the way it was found, whatever a test did to it."""
    logger = logging.getLogger("xmagic")
    level, handlers = logger.level, list(logger.handlers)
    yield logger
    logger.setLevel(level)
    logger.handlers[:] = handlers


class TestUserAgent:
    def test_names_the_sdk_python_and_httpx_versions(self) -> None:
        assert UA.match(USER_AGENT), USER_AGENT
        assert xmagic.__version__ in USER_AGENT

    @respx.mock
    def test_sent_on_every_request(self) -> None:
        route = respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )

        with _client() as client:
            client.chats.create("agent-1")

        assert route.calls.last.request.headers["user-agent"] == USER_AGENT

    @respx.mock
    def test_sent_on_streams_too(self) -> None:
        route = respx.post(STREAM_URL).mock(
            return_value=Response(
                200, headers={"content-type": "text/event-stream"}, content="data: [DONE]\n\n"
            )
        )

        with _client() as client:
            list(client.chats.stream("agent-1", "chat-1", "hi"))

        assert route.calls.last.request.headers["user-agent"] == USER_AGENT

    @respx.mock
    async def test_the_async_transport_sends_the_same_one(self) -> None:
        route = respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )

        async with AsyncXMagicClient(api_key=KEY, base_url=DEFAULT_BASE_URL) as client:
            await client.chats.create("agent-1")

        assert route.calls.last.request.headers["user-agent"] == USER_AGENT


class TestLogging:
    def test_the_package_is_quiet_by_default(self) -> None:
        # The library convention: a NullHandler at the root so an application
        # that configured no logging sees nothing, and no "no handlers" warning.
        assert any(isinstance(h, logging.NullHandler) for h in logging.getLogger("xmagic").handlers)

    @respx.mock
    def test_a_request_logs_its_line_and_its_response(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(
                200, json={"data": {"chat": {"id": "chat-1"}}}, headers={"x-request-id": "req-42"}
            )
        )

        with caplog.at_level(logging.DEBUG, logger="xmagic"), _client() as client:
            client.chats.create("agent-1")

        messages = [r.getMessage() for r in caplog.records if r.name == "xmagic.http"]
        assert messages[0] == "POST /agents/agent-1/chats"
        assert re.match(
            r"POST /agents/agent-1/chats -> 200 in \d+ms \(request id req-42\)$", messages[1]
        )
        assert all(r.levelno == logging.DEBUG for r in caplog.records)

    @respx.mock
    def test_a_retry_is_info_and_names_the_delay(
        self, caplog: pytest.LogCaptureFixture, sleeps: list[float]
    ) -> None:
        respx.post(CHATS_URL).mock(
            side_effect=[
                Response(429, json={"message": "slow down"}, headers={"Retry-After": "2"}),
                Response(200, json={"data": {"chat": {"id": "chat-1"}}}),
            ]
        )

        with caplog.at_level(logging.INFO, logger="xmagic"), _client(max_retries=3) as client:
            client.chats.create("agent-1")

        infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert infos == [
            "POST /agents/agent-1/chats returned 429; retrying in 2.0s (attempt 1 of 3)"
        ]
        assert sleeps == [2.0]

    @respx.mock
    def test_a_stream_logs_as_a_stream(self, caplog: pytest.LogCaptureFixture) -> None:
        respx.post(STREAM_URL).mock(
            return_value=Response(
                200, headers={"content-type": "text/event-stream"}, content="data: [DONE]\n\n"
            )
        )

        with caplog.at_level(logging.DEBUG, logger="xmagic"), _client() as client:
            list(client.chats.stream("agent-1", "chat-1", "hi"))

        messages = [r.getMessage() for r in caplog.records if r.name == "xmagic.http"]
        assert messages[0].endswith("/query (stream)")
        assert " -> 200 in " in messages[1]

    @respx.mock
    def test_the_api_key_never_appears_in_a_log_record(
        self, caplog: pytest.LogCaptureFixture, sleeps: list[float]
    ) -> None:
        """The request line carries the key; the log line must not. Retries included."""
        respx.post(CHATS_URL).mock(
            side_effect=[
                Response(503, json={"message": "busy"}),
                Response(200, json={"data": {"chat": {"id": "chat-1"}}}),
            ]
        )

        with caplog.at_level(logging.DEBUG, logger="xmagic"), _client() as client:
            client.chats.create("agent-1")

        assert caplog.records, "nothing was logged, so nothing was checked"
        assert KEY not in caplog.text
        assert "x-api-key" not in caplog.text.lower()


class TestCliVerbose:
    def test_dash_v_turns_debug_on_for_the_package(self, package_logger: logging.Logger) -> None:
        result = CliRunner().invoke(app, ["-v", "version"])

        assert result.exit_code == 0, result.output
        assert package_logger.level == logging.DEBUG
        assert any(isinstance(h, logging.StreamHandler) for h in package_logger.handlers)

    def test_without_it_the_package_stays_quiet(self, package_logger: logging.Logger) -> None:
        result = CliRunner().invoke(app, ["version"])

        assert result.exit_code == 0, result.output
        assert package_logger.level == logging.NOTSET
        assert all(isinstance(h, logging.NullHandler) for h in package_logger.handlers)
