"""`XMagicProvider` stream handling.

There was no provider-level test file before this: the stream loop was covered
only indirectly, through the CLI. That is how an `error` event went unnoticed as
a silent drop -- nothing asserted on the provider's behaviour directly.
"""

from __future__ import annotations

import pytest

from xmagic.client.models import StreamEvent
from xmagic.errors import XMagicAPIError
from xmagic.providers.base import ChatMessage
from xmagic.providers.xmagic import XMagicProvider, _usage_from

MESSAGES = [ChatMessage(role="user", content="hi")]


class _FakeChats:
    """Replays canned events, and records that a chat was created once."""

    def __init__(self, events: list[StreamEvent]) -> None:
        self._events = events
        self.created = 0

    def create(self, *_args, **_kwargs):
        self.created += 1
        return type("Chat", (), {"id": "chat-1"})()

    def stream(self, *_args, **_kwargs):
        yield from self._events


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch):
    """A provider whose transport is replaced, so no client is constructed."""

    def build(events: list[StreamEvent]) -> XMagicProvider:
        monkeypatch.setattr(XMagicProvider, "__init__", lambda self, **kw: None)
        p = XMagicProvider()
        p._chat_id = "chat-1"
        p._client = type("Client", (), {"chats": _FakeChats(events)})()
        return p

    return build


def _event(kind: str, text: str = "", **raw) -> StreamEvent:
    return StreamEvent(type=kind, text=text, raw=raw)


def test_text_and_reasoning_still_flow(provider) -> None:
    p = provider(
        [
            _event("reasoning", "thinking"),
            _event("response", "hello"),
            _event("done"),
        ]
    )
    chunks = list(p.stream(MESSAGES, model="agent-1"))

    assert [(c.kind, c.text) for c in chunks[:2]] == [
        ("reasoning", "thinking"),
        ("response", "hello"),
    ]
    assert chunks[-1].done


def test_token_usage_reaches_the_terminal_chunk(provider) -> None:
    p = provider(
        [
            _event("response", "hi"),
            _event(
                "token_usage", data={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}
            ),
            _event("done"),
        ]
    )
    chunks = list(p.stream(MESSAGES, model="agent-1"))

    # Usage arrives before `done`, so it rides out on the terminal chunk rather
    # than as a chunk of its own -- callers already treat `done` as the end.
    assert chunks[-1].done
    assert chunks[-1].usage is not None
    assert (chunks[-1].usage.input_tokens, chunks[-1].usage.total_tokens) == (12, 15)
    # And it must not have been mistaken for answer text.
    assert "".join(c.text for c in chunks) == "hi"


def test_streamed_error_raises_instead_of_truncating(provider) -> None:
    """The bug this file exists for.

    Before, an `error` frame fell through the if/elif and vanished: the caller
    received "partial" and a clean end of stream, indistinguishable from a short
    successful answer.
    """
    p = provider(
        [
            _event("response", "partial"),
            _event("error", "the agent exploded", data={"error_code": "E_AGENT"}),
            _event("done"),
        ]
    )

    collected = []
    with pytest.raises(XMagicAPIError) as excinfo:
        for chunk in p.stream(MESSAGES, model="agent-1"):
            collected.append(chunk.text)

    assert collected == ["partial"]  # what arrived before the failure still arrived
    assert "the agent exploded" in str(excinfo.value)
    assert "E_AGENT" in str(excinfo.value)


def test_error_without_a_message_still_says_something_useful(provider) -> None:
    p = provider([_event("error")])

    with pytest.raises(XMagicAPIError, match="reported an error mid-stream"):
        list(p.stream(MESSAGES, model="agent-1"))


def test_unknown_events_are_ignored_not_rendered(provider) -> None:
    """`metadata`/`ping`/`live_update` carry text we must not print as an answer."""
    p = provider(
        [
            _event("ping"),
            _event("metadata", data={"message_id": "m-1"}),
            _event("live_update", "calling a tool"),
            _event("response", "answer"),
            _event("done"),
        ]
    )
    assert "".join(c.text for c in p.stream(MESSAGES, model="agent-1")) == "answer"


class TestUsageParsing:
    """The payload shape is unobserved, so parsing must never be the failure."""

    def test_nested_under_data(self) -> None:
        usage = _usage_from(_event("token_usage", data={"input_tokens": 5}))
        assert usage is not None and usage.input_tokens == 5

    def test_flat_openai_style_names(self) -> None:
        usage = _usage_from(_event("token_usage", prompt_tokens=7, completion_tokens=2))
        assert usage is not None
        assert (usage.input_tokens, usage.output_tokens) == (7, 2)

    def test_numeric_strings_are_accepted(self) -> None:
        usage = _usage_from(_event("token_usage", data={"total_tokens": "42"}))
        assert usage is not None and usage.total_tokens == 42

    def test_unreadable_payload_yields_none_rather_than_zeros(self) -> None:
        # Reporting 0 tokens as though it were measured would be worse than
        # reporting nothing.
        assert _usage_from(_event("token_usage", data={"what": "ever"})) is None
        assert _usage_from(_event("token_usage")) is None

    def test_booleans_are_not_token_counts(self) -> None:
        # bool is a subclass of int; `cached=True` must not become 1 token.
        assert _usage_from(_event("token_usage", data={"input_tokens": True})) is None


class TestErrorReachesTheCli:
    """End-to-end: a streamed error must make `xmagic chat` fail, not exit 0.

    This lives here rather than in `test_cli_chat.py` because that file is
    contended by another open PR; the assertion belongs with the behaviour it
    guards regardless.
    """

    @staticmethod
    def test_chat_exits_non_zero_on_a_streamed_error(
        monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import json

        import respx
        from httpx import Response
        from typer.testing import CliRunner

        from xmagic.cli.main import app
        from xmagic.config import DEFAULT_BASE_URL

        monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
        monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))

        frames = [
            json.dumps({"type": "response", "text": "partial"}),
            json.dumps({"type": "error", "text": "the agent exploded"}),
        ]
        body = "\n\n".join(f"data: {f}" for f in frames) + "\n\n"

        with respx.mock:
            respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats").mock(
                return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
            )
            respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query").mock(
                return_value=Response(200, text=body, headers={"content-type": "text/event-stream"})
            )
            result = CliRunner().invoke(app, ["chat", "--agent", "agent-1", "hi"])

        # Before: exit 0, output "partial", indistinguishable from success.
        assert result.exit_code == 1
        assert "the agent exploded" in result.output
