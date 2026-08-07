"""Contract tests for the one vendor-native adapter.

The OpenAI SDK is built on httpx, so respx intercepts it the same way the xMagic
client tests are mocked -- no network, no key, no vendor test double.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from xmagic.errors import AuthenticationError, ConfigurationError, RateLimitError
from xmagic.providers.base import ChatMessage
from xmagic.providers.openai import OpenAIProvider

CHAT_URL = "https://api.openai.com/v1/chat/completions"
MESSAGES = [
    ChatMessage(role="system", content="Be terse."),
    ChatMessage(role="user", content="Hello!"),
]


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="sk-test")


def _completion(text: str) -> dict:
    return {
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


def _sse(*frames: dict) -> str:
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames)
    return body + "data: [DONE]\n\n"


def _delta(**delta: object) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def test_missing_api_key_raises_configuration_error() -> None:
    # Before any network call, and as XMagicError so the CLI prints it cleanly
    # rather than surfacing an OpenAI traceback.
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        OpenAIProvider(api_key=None)


@respx.mock
def test_complete_sends_messages_verbatim(provider: OpenAIProvider) -> None:
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("Hi.")))
    result = provider.complete(MESSAGES, model="gpt-5")

    assert result.text == "Hi."
    assert result.model == "openai:gpt-5"
    sent = json.loads(route.calls.last.request.content)
    # Unlike xMagic, which flattens the list into one query string, OpenAI keeps
    # roles -- so the system message must survive as its own entry.
    assert sent["messages"] == [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "Hello!"},
    ]
    assert sent["model"] == "gpt-5"
    assert not sent.get("stream")


@respx.mock
def test_extra_params_reach_the_request(provider: OpenAIProvider) -> None:
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("ok")))
    provider.complete(MESSAGES, model="gpt-5", temperature=0.2, max_tokens=16)

    sent = json.loads(route.calls.last.request.content)
    assert sent["temperature"] == 0.2
    assert sent["max_tokens"] == 16


@respx.mock
def test_stream_yields_text_then_a_terminal_done(provider: OpenAIProvider) -> None:
    frames = [_delta(content="Hel"), _delta(content="lo")]
    frames.append(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gpt-5",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(*frames),
        )
    )
    chunks = list(provider.stream(MESSAGES, model="gpt-5"))

    assert "".join(c.text for c in chunks) == "Hello"
    assert [c.done for c in chunks] == [False, False, True]
    assert {c.kind for c in chunks} == {"response"}


@respx.mock
def test_stream_marks_reasoning_deltas(provider: OpenAIProvider) -> None:
    # `reasoning_content` is not an OpenAI field; OpenAI-compatible backends
    # reachable via base_url send it. Absent, this test is the only thing that
    # exercises the branch -- present, reasoning renders dimmed like xMagic's.
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(_delta(reasoning_content="thinking"), _delta(content="Hi")),
        )
    )
    chunks = list(provider.stream(MESSAGES, model="gpt-5"))

    assert [(c.kind, c.text) for c in chunks] == [("reasoning", "thinking"), ("response", "Hi")]


@respx.mock
def test_usage_only_frames_are_skipped(provider: OpenAIProvider) -> None:
    # `stream_options={"include_usage": True}` appends a frame with an empty
    # `choices` list; indexing [0] on it would raise.
    empty = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(_delta(content="Hi"), empty),
        )
    )
    assert [c.text for c in provider.stream(MESSAGES, model="gpt-5")] == ["Hi"]


@respx.mock
@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, AuthenticationError), (429, RateLimitError)],
)
def test_vendor_errors_map_onto_this_sdk_hierarchy(
    provider: OpenAIProvider, status: int, expected: type
) -> None:
    # A caller catching XMagicError should not have to know which vendor failed.
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(status, json={"error": {"message": "nope"}})
    )
    with pytest.raises(expected) as excinfo:
        provider.complete(MESSAGES, model="gpt-5")
    assert excinfo.value.status_code == status


def test_capabilities_advertise_tools_and_vision(provider: OpenAIProvider) -> None:
    assert provider.capabilities() == {"streaming": True, "tools": True, "vision": True}
