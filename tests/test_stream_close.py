"""Streams close when told, not when collected.

`sse()` yields from inside `with connect_sse(...)`. Leaving the loop early used
to suspend the generator there, holding the response until the garbage
collector reached it -- and for an async generator, until the event loop's
finalizer ran, which after the loop is gone is never. `Stream` / `AsyncStream`
make the close explicit.

The tests watch the transport's `connect_sse` block: exiting it is what closes
the response, so "the block exited when close() was called and not before" is
the whole claim. (Watching `httpx.Response.close` directly is noisy -- respx
closes intermediate responses of its own while serving a mock.)
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import httpx_sse
import pytest
import respx
from httpx import Response

import xmagic
from xmagic import AsyncStream, AsyncXMagicClient, Stream, XMagicClient
from xmagic.config import DEFAULT_BASE_URL, Settings
from xmagic.errors import XMagicError
from xmagic.providers import ChatMessage, ToolDef
from xmagic.providers.openai import OpenAIProvider
from xmagic.providers.xmagic import XMagicProvider

AGENT = "agent-1"
CHATS_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats"
QUERY_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats/chat-1/query"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

THREE_FRAMES = (
    'data: {"type": "response", "text": "one"}\n\n'
    'data: {"type": "response", "text": "two"}\n\n'
    'data: {"type": "response", "text": "three"}\n\n'
    "data: [DONE]\n\n"
)


def _sse(body: str = THREE_FRAMES) -> Response:
    return Response(200, text=body, headers={"content-type": "text/event-stream"})


def _client() -> XMagicClient:
    return XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL)


@pytest.fixture
def released(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """One entry per `connect_sse` / `aconnect_sse` block that has exited."""
    seen: list[str] = []
    real_sync, real_async = httpx_sse.connect_sse, httpx_sse.aconnect_sse

    @contextmanager
    def connect_sse(*args: Any, **kwargs: Any) -> Iterator[Any]:
        with real_sync(*args, **kwargs) as source:
            try:
                yield source
            finally:
                seen.append("released")

    @asynccontextmanager
    async def aconnect_sse(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        async with real_async(*args, **kwargs) as source:
            try:
                yield source
            finally:
                seen.append("released")

    # Patched where the transport looks them up, not where they are defined.
    monkeypatch.setattr("xmagic.client.http.connect_sse", connect_sse)
    monkeypatch.setattr("xmagic.client.http.aconnect_sse", aconnect_sse)
    return seen


class TestSyncStream:
    @respx.mock
    def test_close_releases_the_connection_at_that_moment(self, released: list[str]) -> None:
        respx.post(QUERY_URL).mock(return_value=_sse())
        with _client() as client:
            events = client.chats.stream(AGENT, "chat-1", "hi")
            assert isinstance(events, Stream)

            assert next(events).text == "one"
            assert released == []  # mid-stream: connection held, as it should be

            events.close()

            assert released == ["released"]
            assert events.closed

    @respx.mock
    def test_a_closed_stream_yields_nothing_more_and_releases_once(
        self, released: list[str]
    ) -> None:
        respx.post(QUERY_URL).mock(return_value=_sse())
        with _client() as client:
            events = client.chats.stream(AGENT, "chat-1", "hi")
            next(events)
            events.close()
            events.close()

            assert list(events) == []
            assert released == ["released"]

    @respx.mock
    def test_with_releases_on_exit_whichever_way_the_loop_ends(self, released: list[str]) -> None:
        respx.post(QUERY_URL).mock(return_value=_sse())
        with _client() as client:
            with client.chats.stream(AGENT, "chat-1", "hi") as events:
                for event in events:
                    if event.text == "two":
                        break  # the case that used to leak
            assert released == ["released"]
            assert events.closed

    @respx.mock
    def test_exhausting_the_stream_marks_it_closed(self, released: list[str]) -> None:
        respx.post(QUERY_URL).mock(return_value=_sse())
        with _client() as client:
            events = client.chats.stream(AGENT, "chat-1", "hi")
            texts = [e.text for e in events]

        assert texts == ["one", "two", "three", ""]  # three frames and the done event
        assert events.closed
        assert released == ["released"]

    @respx.mock
    def test_an_error_status_still_raises_through_the_wrapper(self) -> None:
        respx.post(QUERY_URL).mock(
            return_value=Response(401, json={"error": {"message": "bad key"}})
        )
        with _client() as client, pytest.raises(XMagicError, match="bad key"):
            next(client.chats.stream(AGENT, "chat-1", "hi"))


class TestAsyncStream:
    @respx.mock
    async def test_aclose_releases_the_connection(self, released: list[str]) -> None:
        respx.post(QUERY_URL).mock(return_value=_sse())
        async with AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
            events = client.chats.stream(AGENT, "chat-1", "hi")
            assert isinstance(events, AsyncStream)

            assert (await events.__anext__()).text == "one"
            assert released == []

            await events.aclose()

            assert released == ["released"]
            assert events.closed
            assert [e async for e in events] == []

    @respx.mock
    async def test_async_with_releases_on_exit(self, released: list[str]) -> None:
        respx.post(QUERY_URL).mock(return_value=_sse())
        async with AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
            async with client.chats.stream(AGENT, "chat-1", "hi") as events:
                async for event in events:
                    if event.text == "two":
                        break
            assert released == ["released"]


class TestProviders:
    @respx.mock
    def test_the_xmagic_adapter_closes_through_to_the_transport(self, released: list[str]) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(return_value=_sse())
        provider = XMagicProvider(settings=Settings(api_key="k", base_url=DEFAULT_BASE_URL))

        chunks = provider.stream([ChatMessage(role="user", content="hi")], model=AGENT)
        assert isinstance(chunks, Stream)
        assert next(chunks).text == "one"
        assert released == []
        chunks.close()

        assert released == ["released"]

    def test_the_xmagic_adapter_validates_at_the_call_not_the_first_next(self) -> None:
        # A generator function would defer the check to the first `next()`; the
        # wrapper is built by a plain method, so a bad call fails where it is made.
        provider = XMagicProvider(settings=Settings(api_key="k", base_url=DEFAULT_BASE_URL))
        tool = ToolDef(name="t", parameters={"type": "object", "properties": {}})

        with pytest.raises(XMagicError, match="registered in the dashboard"):
            provider.stream([ChatMessage(role="user", content="hi")], model=AGENT, tools=[tool])

    @respx.mock
    def test_the_openai_adapter_closes_the_vendors_stream_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openai import Stream as VendorStream

        vendor_closes: list[str] = []
        original = VendorStream.close

        def close(self: Any) -> None:
            vendor_closes.append("close")
            original(self)

        monkeypatch.setattr(VendorStream, "close", close)
        respx.post(OPENAI_URL).mock(
            return_value=Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    'data: {"id":"c","object":"chat.completion.chunk","created":0,"model":"gpt-5",'
                    '"choices":[{"index":0,"delta":{"content":"one"},"finish_reason":null}]}\n\n'
                    'data: {"id":"c","object":"chat.completion.chunk","created":0,"model":"gpt-5",'
                    '"choices":[{"index":0,"delta":{"content":"two"},"finish_reason":null}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        )
        provider = OpenAIProvider(api_key="sk-test")

        chunks = provider.stream([ChatMessage(role="user", content="hi")], model="gpt-5")
        assert isinstance(chunks, Stream)
        assert next(chunks).text == "one"
        assert vendor_closes == []
        chunks.close()

        assert vendor_closes == ["close"]


def test_both_classes_are_exported_from_the_package_root() -> None:
    assert xmagic.Stream is Stream
    assert xmagic.AsyncStream is AsyncStream


def test_a_stream_over_any_iterator_closes_cleanly() -> None:
    # Not every source has close(); a list iterator does not, and the wrapper
    # must not care. A generator does, and must be closed.
    def items() -> Iterator[int]:
        yield from (1, 2, 3)

    plain = Stream(iter([1, 2, 3]))
    assert next(plain) == 1
    plain.close()
    assert list(plain) == []

    generator = Stream(items())
    assert next(generator) == 1
    generator.close()
    assert list(generator) == []
