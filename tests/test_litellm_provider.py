"""Contract tests for the LiteLLM adapter.

LiteLLM speaks to OpenAI-compatible endpoints over httpx, so respx intercepts it
exactly as it does the vendor-native adapter -- no network, no key, no LiteLLM
test double. `openai/gpt-5` is the routing target throughout because it is the
cheapest one to mock; the adapter itself passes the model string through
untouched, so nothing here is OpenAI-specific.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from xmagic.errors import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    ServerError,
    XMagicAPIError,
)
from xmagic.providers import get_provider
from xmagic.providers.base import ChatMessage
from xmagic.providers.litellm import LiteLLMProvider

pytest.importorskip("litellm")

CHAT_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "openai/gpt-5"
MESSAGES = [
    ChatMessage(role="system", content="Be terse."),
    ChatMessage(role="user", content="Hello!"),
]


@pytest.fixture
def provider() -> LiteLLMProvider:
    return LiteLLMProvider(api_key="sk-test")


def _completion(text: str, usage: dict[str, int] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _sse(*frames: dict[str, Any]) -> str:
    return "".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n"


def _chunk(**delta: object) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def _stop() -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }


def _usage_frame(**counts: int) -> dict[str, Any]:
    """The OpenAI shape: a trailing frame with no choices, only usage."""
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [],
        "usage": counts,
    }


def _stream_response(*frames: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, text=_sse(*frames), headers={"content-type": "text/event-stream"})


def test_no_api_key_is_not_an_error() -> None:
    # Unlike OpenAIProvider, which raises: LiteLLM resolves credentials per
    # vendor from the environment, and a local runtime needs none at all.
    assert LiteLLMProvider().capabilities()["streaming"] is True


@respx.mock
def test_complete_sends_the_openai_message_shape(provider: LiteLLMProvider) -> None:
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi")))

    result = provider.complete(MESSAGES, model=MODEL)

    assert result.text == "hi"
    # The ref is echoed back with the provider prefix, not the vendor's own id.
    assert result.model == "litellm:openai/gpt-5"
    sent = json.loads(route.calls.last.request.content)
    assert sent["messages"] == [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "Hello!"},
    ]
    assert sent["model"] == "gpt-5"


@respx.mock
def test_complete_reports_the_token_counts_the_provider_sent(provider: LiteLLMProvider) -> None:
    counts = {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13}
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi", counts)))

    usage = provider.complete(MESSAGES, model=MODEL).usage

    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (11, 2, 13)
    # `model_dump()` on the response drops usage entirely, so `raw` is the only
    # place the untranslated payload survives.
    assert usage.raw["prompt_tokens"] == 11


@respx.mock
def test_a_response_without_usage_reports_none_rather_than_zeros(
    provider: LiteLLMProvider,
) -> None:
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi")))

    assert provider.complete(MESSAGES, model=MODEL).usage is None


@respx.mock
def test_extra_params_reach_the_request(provider: LiteLLMProvider) -> None:
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi")))

    # gpt-4o rather than gpt-5, because LiteLLM checks params against the model
    # before sending -- see the test below.
    provider.complete(MESSAGES, model="openai/gpt-4o", temperature=0.2)

    assert json.loads(route.calls.last.request.content)["temperature"] == 0.2


@respx.mock
def test_params_the_model_does_not_support_are_rejected_before_sending(
    provider: LiteLLMProvider,
) -> None:
    """A real difference from `OpenAIProvider`, which passes params through blind.

    LiteLLM validates against its own model metadata, so an unsupported param
    fails locally and never reaches the vendor. Worth knowing when moving a call
    from `openai:` to `litellm:`: the same arguments can start failing.
    """
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi")))

    with pytest.raises(BadRequestError):
        provider.complete(MESSAGES, model=MODEL, temperature=0.2)  # gpt-5 allows only 1

    assert not route.called


@respx.mock
def test_base_url_and_key_are_forwarded_to_the_vendor() -> None:
    # An OpenAI-compatible endpoint (vLLM, LM Studio, a gateway) is the reason
    # `base_url` exists; LiteLLM spells it `api_base`.
    route = respx.post("https://gateway.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("hi"))
    )
    provider = LiteLLMProvider(api_key="sk-local", base_url="https://gateway.test/v1")

    provider.complete(MESSAGES, model=MODEL)

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-local"


@respx.mock
def test_stream_yields_text_then_a_terminal_done(provider: LiteLLMProvider) -> None:
    respx.post(CHAT_URL).mock(
        return_value=_stream_response(_chunk(content="hel"), _chunk(content="lo"), _stop())
    )

    chunks = list(provider.stream(MESSAGES, model=MODEL))

    assert "".join(c.text for c in chunks) == "hello"
    assert [c.done for c in chunks] == [False, False, True]


@respx.mock
def test_stream_marks_reasoning_deltas(provider: LiteLLMProvider) -> None:
    # LiteLLM normalizes every vendor's thinking channel onto `reasoning_content`,
    # so a caller can dim it without knowing which vendor produced it.
    respx.post(CHAT_URL).mock(
        return_value=_stream_response(
            _chunk(reasoning_content="thinking"), _chunk(content="answer"), _stop()
        )
    )

    chunks = list(provider.stream(MESSAGES, model=MODEL))

    assert [(c.kind, c.text) for c in chunks[:2]] == [
        ("reasoning", "thinking"),
        ("response", "answer"),
    ]


@respx.mock
def test_streamed_usage_rides_out_on_the_terminal_chunk(provider: LiteLLMProvider) -> None:
    respx.post(CHAT_URL).mock(
        return_value=_stream_response(
            _chunk(content="hello"),
            _stop(),
            _usage_frame(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
    )

    chunks = list(provider.stream(MESSAGES, model=MODEL))

    # The usage frame arrives *after* the finish reason, which is why `done` is
    # emitted at the end of the stream rather than on `finish_reason` -- closing
    # early would drop these counts every time.
    assert chunks[-1].done
    assert chunks[-1].usage is not None
    assert (chunks[-1].usage.input_tokens, chunks[-1].usage.total_tokens) == (5, 8)
    # And usage must not have been mistaken for answer text.
    assert "".join(c.text for c in chunks) == "hello"


@respx.mock
def test_streamed_counts_are_estimated_when_the_provider_sends_none(
    provider: LiteLLMProvider,
) -> None:
    """Documented, not desired: LiteLLM fills the gap with its own tokenizer.

    A stream with no usage frame still ends with counts, and nothing on the wire
    distinguishes them from measured ones. Pinned here so the behaviour is a
    known property of this adapter rather than a surprise in someone's billing
    reconciliation.
    """
    respx.post(CHAT_URL).mock(return_value=_stream_response(_chunk(content="hello"), _stop()))

    usage = list(provider.stream(MESSAGES, model=MODEL))[-1].usage

    assert usage is not None
    assert usage.total_tokens is not None


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, AuthenticationError), (429, RateLimitError), (503, ServerError)],
)
@respx.mock
def test_vendor_errors_map_onto_this_sdk_hierarchy(
    provider: LiteLLMProvider, status: int, expected: type[XMagicAPIError]
) -> None:
    # LiteLLM normalizes ~150 vendors' failures into its own exception set, and
    # this maps that set onto ours -- so a caller catching XMagicError never has
    # to know which vendor, or which SDK, actually failed.
    respx.post(CHAT_URL).mock(return_value=httpx.Response(status, json={"error": {"m": "no"}}))

    with pytest.raises(expected) as excinfo:
        provider.complete(MESSAGES, model=MODEL)

    assert excinfo.value.status_code == status


@respx.mock
def test_a_timeout_becomes_this_sdk_s_timeout_error(provider: LiteLLMProvider) -> None:
    respx.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

    with pytest.raises(APITimeoutError):
        provider.complete(MESSAGES, model=MODEL)


@respx.mock
def test_an_unreachable_provider_surfaces_as_litellm_classifies_it(
    provider: LiteLLMProvider,
) -> None:
    """Documented, not chosen: LiteLLM calls a dead socket a 500.

    A connection failure on the OpenAI path is wrapped as
    `litellm.InternalServerError`, so it reaches us with a status code and maps
    to `ServerError` -- not to `APIConnectionError`, which is what the same
    failure raises through this SDK's own transport. Re-classifying it here
    would mean string-matching LiteLLM's messages, which is worse than the
    inconsistency. `APIConnectionError` still fires for the providers LiteLLM
    routes through its own HTTP handler.
    """
    respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("no route to host"))

    with pytest.raises(ServerError):
        provider.complete(MESSAGES, model=MODEL)


class TestReachedThroughTheRest:
    """`litellm:` refs resolve through the registry and the CLI, not just here."""

    @respx.mock
    def test_the_registry_resolves_the_ref_and_the_model_it_names(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
        respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi")))

        provider = get_provider("litellm:openai/gpt-5", api_key="sk-test")

        assert isinstance(provider, LiteLLMProvider)
        assert provider.complete(MESSAGES, model="openai/gpt-5").text == "hi"
        # Reads the model off the ref the registry parsed. False here would mean
        # `default_model` never landed, and capabilities silently degraded.
        assert provider.capabilities()["vision"] is True

    @respx.mock
    def test_the_cli_can_chat_through_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from typer.testing import CliRunner

        from xmagic.cli.main import app

        monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
        monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        respx.post(CHAT_URL).mock(
            return_value=_stream_response(_chunk(content="hello from litellm"), _stop())
        )

        result = CliRunner().invoke(app, ["chat", "-m", "litellm:openai/gpt-5", "hi"])

        assert result.exit_code == 0, result.output
        assert "hello from litellm" in result.output


class TestCapabilities:
    """Read off LiteLLM's model metadata instead of a hand-maintained table."""

    def test_flags_come_from_the_model_being_addressed(self) -> None:
        provider = LiteLLMProvider()
        provider.default_model = "openai/gpt-5"  # type: ignore[attr-defined]

        assert provider.capabilities() == {"streaming": True, "tools": True, "vision": True}

    def test_a_text_only_model_does_not_advertise_vision(self) -> None:
        provider = LiteLLMProvider()
        provider.default_model = "groq/llama-3.3-70b-versatile"  # type: ignore[attr-defined]

        caps = provider.capabilities()

        assert caps["tools"] is True
        assert caps["vision"] is False

    def test_an_unmapped_model_falls_back_to_the_conservative_defaults(self) -> None:
        provider = LiteLLMProvider()
        provider.default_model = "nobody/invented-this"  # type: ignore[attr-defined]

        assert provider.capabilities() == {"streaming": True, "tools": False, "vision": False}

    def test_no_model_at_all_falls_back_too(self) -> None:
        # Constructed directly rather than through `get_provider`, so there is no
        # ref to read a model out of.
        assert LiteLLMProvider().capabilities() == {
            "streaming": True,
            "tools": False,
            "vision": False,
        }
