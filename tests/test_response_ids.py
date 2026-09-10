"""The response id reaches the caller, on every path.

xMagic sends the id of the message it is generating in a `metadata` frame
before any text. The provider used to drop that frame, so a streaming caller
could see the whole answer and still not know which message it was -- the id
`chats.get_message` and the worklist review flow take. `Completion.id` and the
terminal `CompletionChunk.id` carry it now, and the same field carries the
`chatcmpl-...` id from OpenAI and whatever LiteLLM passes through, so there is
one place to look rather than one per provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from xmagic.cli.main import app
from xmagic.client.models import StreamEvent
from xmagic.config import DEFAULT_BASE_URL, Settings
from xmagic.providers.base import ChatMessage
from xmagic.providers.openai import OpenAIProvider
from xmagic.providers.xmagic import XMagicProvider, _message_id_from

AGENT = "agent-1"
CHATS_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats"
QUERY_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats/chat-1/query"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MESSAGES = [ChatMessage(role="user", content="hi")]

# The recorded live shape, from tests/fixtures/stream_sse_frames.txt.
METADATA_FRAME = (
    '{"text": "", "extended_text": null, "type": "metadata", "subtype": null, '
    '"data": {"message_id": "msg-42"}, "elapsed_ms": null}'
)


def _sse(*frames: str) -> Response:
    body = "\n\n".join(f"data: {f}" for f in frames) + "\n\n"
    return Response(200, text=body, headers={"content-type": "text/event-stream"})


def _openai_chunk(content: str, finish: str | None = None, id_: str = "chatcmpl-7") -> str:
    return json.dumps(
        {
            "id": id_,
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gpt-5",
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}],
        }
    )


class TestXMagic:
    def test_the_metadata_frame_is_read_in_its_recorded_shape(self) -> None:
        event = StreamEvent(type="metadata", text="", raw=json.loads(METADATA_FRAME))

        assert _message_id_from(event) == "msg-42"

    @pytest.mark.parametrize(
        "raw",
        [
            {},
            {"data": {}},
            {"data": {"message_id": ""}},
            {"data": {"message_id": 7}},
            {"data": "x"},
        ],
    )
    def test_an_unexpected_metadata_shape_yields_none_not_an_error(
        self, raw: dict[str, Any]
    ) -> None:
        assert _message_id_from(StreamEvent(type="metadata", text="", raw=raw)) is None

    @respx.mock
    def test_streaming_puts_the_message_id_on_the_terminal_chunk(self) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(
            return_value=_sse(
                METADATA_FRAME,
                '{"type": "response", "text": "hello"}',
                "[DONE]",
            )
        )
        provider = XMagicProvider(settings=Settings(api_key="k", base_url=DEFAULT_BASE_URL))

        chunks = list(provider.stream(MESSAGES, model=AGENT))

        # The frame arrived first, but the id surfaces where usage does.
        assert [c.id for c in chunks] == [None, "msg-42"]
        assert chunks[-1].done

    @respx.mock
    def test_blocking_carries_the_message_id_too(self) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(
            return_value=Response(200, json={"data": {"message_id": "msg-43", "text": "hello"}})
        )
        provider = XMagicProvider(settings=Settings(api_key="k", base_url=DEFAULT_BASE_URL))

        assert provider.complete(MESSAGES, model=AGENT).id == "msg-43"


class TestOpenAI:
    @respx.mock
    def test_blocking_and_streaming_carry_the_vendors_id(self) -> None:
        respx.post(OPENAI_URL).mock(
            side_effect=[
                Response(
                    200,
                    json={
                        "id": "chatcmpl-7",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "gpt-5",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "hi"},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                ),
                Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=(
                        f"data: {_openai_chunk('hi')}\n\n"
                        f"data: {_openai_chunk('', 'stop')}\n\n"
                        "data: [DONE]\n\n"
                    ),
                ),
            ]
        )
        provider = OpenAIProvider(api_key="sk-test")

        assert provider.complete(MESSAGES, model="gpt-5").id == "chatcmpl-7"
        chunks = list(provider.stream(MESSAGES, model="gpt-5"))
        assert [c.id for c in chunks] == [None, "chatcmpl-7"]


class TestLiteLLM:
    @respx.mock
    def test_the_id_passes_through(self) -> None:
        pytest.importorskip("litellm")
        from xmagic.providers.litellm import LiteLLMProvider

        respx.post(OPENAI_URL).mock(
            return_value=Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    f"data: {_openai_chunk('hi', id_='chatcmpl-9')}\n\n"
                    f"data: {_openai_chunk('', 'stop', id_='chatcmpl-9')}\n\n"
                    "data: [DONE]\n\n"
                ),
            )
        )

        chunks = list(LiteLLMProvider(api_key="sk-test").stream(MESSAGES, model="openai/gpt-5"))

        assert chunks[-1].done
        assert chunks[-1].id == "chatcmpl-9"


class TestCli:
    @pytest.fixture(autouse=True)
    def env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
        monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))

    @respx.mock
    def test_chat_json_reports_the_message_id(self) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(
            return_value=_sse(METADATA_FRAME, '{"type": "response", "text": "hello"}', "[DONE]")
        )

        result = CliRunner().invoke(app, ["chat", "--agent", AGENT, "--json", "hi"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["id"] == "msg-42"
