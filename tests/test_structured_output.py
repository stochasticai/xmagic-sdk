"""Structured output — DESIGN.md §14.

`response_format=` takes a pydantic model, the vendor is asked for that schema,
and the reply comes back validated as `Completion.parsed`. The promise is the
same one tool calling makes: a caller who asked for a `Weather` gets a `Weather`
or an exception, never a `None` that looks like success until `.parsed.city`
blows up three lines later.

Driven over the OpenAI wire through both adapters, since LiteLLM levels every
vendor onto that shape (§13.2) -- for Anthropic it does so by forcing a tool,
which is its problem and not this mapping's.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from xmagic.errors import XMagicError
from xmagic.providers._openai_wire import parse_structured, response_format_to_wire
from xmagic.providers.base import ChatMessage
from xmagic.providers.openai import OpenAIProvider

CHAT_URL = "https://api.openai.com/v1/chat/completions"


class Weather(BaseModel):
    """Flat and fully required: the shape strict mode accepts as-is."""

    city: str
    temp_c: float


class Report(BaseModel):
    """Nested: pydantic emits `$defs`, which strict mode would reject unrewritten."""

    title: str
    weather: Weather


class Loose(BaseModel):
    """A default makes the property optional, which strict mode forbids."""

    city: str
    note: str = ""


MESSAGES = [ChatMessage(role="user", content="Weather in Osaka?")]
OSAKA = '{"city": "Osaka", "temp_c": 24.0}'


def _completion(content: str | None, refusal: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if refusal is not None:
        message["refusal"] = refusal
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _sse(*frames: dict[str, Any], done: bool = True) -> str:
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames)
    return body + ("data: [DONE]\n\n" if done else "")


def _stream(*frames: dict[str, Any], done: bool = True) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=_sse(*frames, done=done)
    )


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="sk-test")


class TestWireMapping:
    def test_a_model_becomes_a_json_schema_response_format(self) -> None:
        wire = response_format_to_wire(Weather)

        assert wire["type"] == "json_schema"
        assert wire["json_schema"]["name"] == "Weather"
        schema = wire["json_schema"]["schema"]
        assert set(schema["properties"]) == {"city", "temp_c"}
        assert "title" not in schema  # the name belongs to the format, not the schema

    def test_strict_is_claimed_only_for_a_flat_fully_required_model(self) -> None:
        # The same rule `ToolDef.from_callable` applies, through the same helper:
        # strict constrains every level and the nested objects are not rewritten.
        assert response_format_to_wire(Weather)["json_schema"]["strict"] is True
        assert (
            response_format_to_wire(Weather)["json_schema"]["schema"]["additionalProperties"]
            is False
        )
        assert response_format_to_wire(Report)["json_schema"]["strict"] is False
        assert response_format_to_wire(Loose)["json_schema"]["strict"] is False

    def test_a_raw_dict_is_refused_with_directions(self) -> None:
        # The vendor's own `{"type": "json_schema", ...}` dict is the shape a
        # caller might reach for first. It would fail as an AttributeError on
        # `model_json_schema` otherwise, which says nothing about what to do.
        with pytest.raises(TypeError, match="pydantic model class"):
            response_format_to_wire({"type": "json_object"})  # type: ignore[arg-type]

    def test_parse_reports_a_refusal_in_the_vendors_words(self) -> None:
        with pytest.raises(XMagicError, match=r"refused.*Weather.*cannot help"):
            parse_structured("", Weather, refusal="I cannot help with that.")


class TestOpenAIAdapter:
    @respx.mock
    def test_the_reply_comes_back_parsed(self, provider: OpenAIProvider) -> None:
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(OSAKA)))

        result = provider.complete(MESSAGES, model="gpt-5", response_format=Weather)

        sent = json.loads(route.calls.last.request.content)["response_format"]
        assert sent["type"] == "json_schema"
        assert sent["json_schema"]["name"] == "Weather"
        assert result.parsed == Weather(city="Osaka", temp_c=24.0)
        assert result.text == OSAKA  # the raw text is still there for anyone who wants it

    @respx.mock
    def test_without_a_schema_parsed_is_none_and_nothing_is_sent(
        self, provider: OpenAIProvider
    ) -> None:
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi")))

        result = provider.complete(MESSAGES, model="gpt-5")

        assert "response_format" not in json.loads(route.calls.last.request.content)
        assert result.parsed is None

    @respx.mock
    def test_a_reply_that_does_not_validate_raises(self, provider: OpenAIProvider) -> None:
        """Without strict mode, a model can answer off-schema; that must not pass."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_completion('{"city": "Osaka"}'))
        )

        with pytest.raises(XMagicError, match=r"(?s)did not validate as Weather.*temp_c"):
            provider.complete(MESSAGES, model="gpt-5", response_format=Weather)

    @respx.mock
    def test_a_refusal_raises_rather_than_parsing_empty_content(
        self, provider: OpenAIProvider
    ) -> None:
        # OpenAI puts a safety refusal in its own field with `content: null`.
        # Parsing "" would raise a JSON error that hides the actual reason.
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_completion(None, refusal="I can't do that."))
        )

        with pytest.raises(XMagicError, match=r"refused.*I can't do that"):
            provider.complete(MESSAGES, model="gpt-5", response_format=Weather)

    @respx.mock
    def test_streamed_json_is_text_until_the_terminal_chunk(self, provider: OpenAIProvider) -> None:
        respx.post(CHAT_URL).mock(
            return_value=_stream(
                _chunk({"content": '{"city": "Os'}),
                _chunk({"content": 'aka", "temp_c": 24}'}),
                _chunk({}, finish_reason="stop"),
            )
        )

        chunks = list(provider.stream(MESSAGES, model="gpt-5", response_format=Weather))

        # The JSON streams as ordinary text, so a caller can show progress.
        assert "".join(c.text for c in chunks) == '{"city": "Osaka", "temp_c": 24}'
        # The instance exists only once the JSON closes -- like tool calls and usage.
        assert [c.parsed for c in chunks[:-1]] == [None, None]
        assert chunks[-1].done
        assert chunks[-1].parsed == Weather(city="Osaka", temp_c=24.0)

    @respx.mock
    def test_a_stream_cut_off_mid_json_raises(self, provider: OpenAIProvider) -> None:
        """No finish reason, no [DONE]: the server hung up. Half a JSON object is not a Weather."""
        respx.post(CHAT_URL).mock(
            return_value=_stream(_chunk({"content": '{"city": "Os'}), done=False)
        )

        with pytest.raises(XMagicError, match="did not validate as Weather"):
            list(provider.stream(MESSAGES, model="gpt-5", response_format=Weather))

    @respx.mock
    def test_a_streamed_refusal_raises(self, provider: OpenAIProvider) -> None:
        respx.post(CHAT_URL).mock(
            return_value=_stream(
                _chunk({"refusal": "I can't "}),
                _chunk({"refusal": "do that."}),
                _chunk({}, finish_reason="stop"),
            )
        )

        with pytest.raises(XMagicError, match=r"refused.*I can't do that"):
            list(provider.stream(MESSAGES, model="gpt-5", response_format=Weather))

    def test_capabilities_advertise_it(self, provider: OpenAIProvider) -> None:
        assert provider.capabilities()["structured_output"] is True


class TestLiteLLMAdapter:
    """The same mapping through the adapter that reaches ~150 vendors."""

    @pytest.fixture
    def provider(self) -> Any:
        pytest.importorskip("litellm")
        from xmagic.providers.litellm import LiteLLMProvider

        return LiteLLMProvider(api_key="sk-test")

    @respx.mock
    def test_the_reply_comes_back_parsed(self, provider: Any) -> None:
        route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(OSAKA)))

        result = provider.complete(MESSAGES, model="openai/gpt-5", response_format=Weather)

        sent = json.loads(route.calls.last.request.content)["response_format"]
        assert sent["json_schema"]["name"] == "Weather"
        assert result.parsed == Weather(city="Osaka", temp_c=24.0)

    @respx.mock
    def test_streamed_json_parses_on_the_terminal_chunk(self, provider: Any) -> None:
        respx.post(CHAT_URL).mock(
            return_value=_stream(
                _chunk({"content": '{"city": "Osaka", '}),
                _chunk({"content": '"temp_c": 24}'}),
                _chunk({}, finish_reason="stop"),
            )
        )

        chunks = list(provider.stream(MESSAGES, model="openai/gpt-5", response_format=Weather))

        assert chunks[-1].done
        assert chunks[-1].parsed == Weather(city="Osaka", temp_c=24.0)

    @respx.mock
    def test_a_reply_that_does_not_validate_raises_here_too(self, provider: Any) -> None:
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("not json")))

        with pytest.raises(XMagicError, match="did not validate as Weather"):
            provider.complete(MESSAGES, model="openai/gpt-5", response_format=Weather)


class TestXMagicAdapterRejects:
    """An agent's output shape is part of its configuration, not a per-call parameter."""

    @pytest.fixture
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        from xmagic.providers.xmagic import XMagicProvider

        monkeypatch.setattr(XMagicProvider, "__init__", lambda self, **kw: None)
        return XMagicProvider()

    def test_capabilities_do_not_claim_it(self, provider: Any) -> None:
        assert provider.capabilities()["structured_output"] is False

    def test_complete_refuses_rather_than_returning_parsed_none(self, provider: Any) -> None:
        with pytest.raises(XMagicError, match="per-call response schema"):
            provider.complete(MESSAGES, model="a", response_format=Weather)

    def test_stream_refuses_too(self, provider: Any) -> None:
        with pytest.raises(XMagicError, match="per-call response schema"):
            list(provider.stream(MESSAGES, model="a", response_format=Weather))
