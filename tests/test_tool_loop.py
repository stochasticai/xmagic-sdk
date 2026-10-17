"""The tool-calling execution loop — DESIGN.md §13, stage D.

The loop's contract is tested against a scripted provider that returns queued
completions and records what it was sent — the loop is pure orchestration, so
what matters is the history it builds, the dispatch it performs, and what it
does when a tool misbehaves. The wire is covered separately at the end,
through both adapters over respx, because the one thing a fake cannot prove
is that the history the loop builds survives `messages_to_wire`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from xmagic.errors import ToolTurnsExceeded, XMagicError
from xmagic.providers.base import (
    ChatMessage,
    Completion,
    CompletionChunk,
    Provider,
    ToolCall,
    ToolDef,
    Usage,
)

CHAT_URL = "https://api.openai.com/v1/chat/completions"


class ScriptedProvider(Provider):
    """Returns queued completions and records every request it was sent."""

    name = "scripted"

    def __init__(self, *script: Completion) -> None:
        super().__init__(api_key="unused")
        self.script = list(script)
        self.seen: list[list[ChatMessage]] = []
        self.seen_threads: list[int] = []
        self.seen_response_formats: list[type[BaseModel] | None] = []
        self.seen_params: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        response_format: type[BaseModel] | None = None,
        **params: Any,
    ) -> Completion:
        self.seen.append(list(messages))
        self.seen_threads.append(threading.get_ident())
        self.seen_response_formats.append(response_format)
        self.seen_params.append(params)
        return self.script.pop(0)

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        response_format: type[BaseModel] | None = None,
        **params: Any,
    ) -> Iterator[CompletionChunk]:
        raise NotImplementedError("the loop never streams")


def _calls_turn(*calls: ToolCall, usage: Usage | None = None) -> Completion:
    return Completion(text="", model="scripted:m", tool_calls=list(calls), usage=usage)


def _text_turn(text: str, usage: Usage | None = None) -> Completion:
    return Completion(text=text, model="scripted:m", usage=usage)


def _weather(city: str) -> str:
    """Look up the weather."""
    return f"sunny in {city}"


WEATHER = ToolDef.from_callable(_weather, name="get_weather")
ASK = [ChatMessage(role="user", content="weather in Osaka?")]
CALL = ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})


class TestHappyPath:
    def test_one_call_then_text(self) -> None:
        provider = ScriptedProvider(_calls_turn(CALL), _text_turn("Sunny."))

        run = provider.run_tools(ASK, model="m", tools=[WEATHER])

        assert run.completion.text == "Sunny."
        assert run.turns == 2
        # user, assistant(tool_calls), tool, assistant(text) -- resendable as-is.
        assert [m.role for m in run.messages] == ["user", "assistant", "tool", "assistant"]
        assert run.messages[1].tool_calls == [CALL]
        assert run.messages[1].content is None  # not "" -- a tool-only turn has no text
        assert run.messages[2].tool_call_id == "call_1"
        assert run.messages[2].content == "sunny in Osaka"
        assert run.messages[3].content == "Sunny."
        # The second model call saw the tool result.
        assert [m.role for m in provider.seen[1]] == ["user", "assistant", "tool"]

    def test_the_callers_list_is_not_mutated(self) -> None:
        provider = ScriptedProvider(_text_turn("hi"))
        messages = list(ASK)

        run = provider.run_tools(messages, model="m", tools=[WEATHER])

        assert messages == ASK
        assert run.messages is not messages

    def test_parallel_calls_run_in_the_models_order(self) -> None:
        ran: list[str] = []

        def first() -> str:
            ran.append("first")
            return "a"

        def second() -> str:
            ran.append("second")
            return "b"

        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="first"), ToolCall(id="c2", name="second")),
            _text_turn("done"),
        )

        run = provider.run_tools(
            ASK,
            model="m",
            tools=[ToolDef.from_callable(first), ToolDef.from_callable(second)],
        )

        assert ran == ["first", "second"]
        tool_messages = [m for m in run.messages if m.role == "tool"]
        assert [(m.tool_call_id, m.content) for m in tool_messages] == [("c1", "a"), ("c2", "b")]

    def test_a_multi_turn_chain(self) -> None:
        provider = ScriptedProvider(
            _calls_turn(CALL),
            _calls_turn(ToolCall(id="call_2", name="get_weather", arguments={"city": "Nara"})),
            _text_turn("Both sunny."),
        )

        run = provider.run_tools(ASK, model="m", tools=[WEATHER])

        assert run.turns == 3
        assert [m.content for m in run.messages if m.role == "tool"] == [
            "sunny in Osaka",
            "sunny in Nara",
        ]

    def test_usage_is_summed_across_turns(self) -> None:
        provider = ScriptedProvider(
            _calls_turn(CALL, usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15)),
            _text_turn("Sunny.", usage=Usage(input_tokens=20, output_tokens=2, total_tokens=22)),
        )

        run = provider.run_tools(ASK, model="m", tools=[WEATHER])

        # `completion.usage` covers the final call alone; the sum is the run's.
        assert run.usage == Usage(input_tokens=30, output_tokens=7, total_tokens=37)
        assert run.completion.usage == Usage(input_tokens=20, output_tokens=2, total_tokens=22)

    def test_usage_is_none_when_no_turn_reported_any(self) -> None:
        provider = ScriptedProvider(_text_turn("hi"))

        assert provider.run_tools(ASK, model="m", tools=[WEATHER]).usage is None

    def test_params_and_response_format_pass_through(self) -> None:
        class Answer(BaseModel):
            summary: str

        provider = ScriptedProvider(_text_turn('{"summary": "sunny"}'))

        provider.run_tools(ASK, model="m", tools=[WEATHER], response_format=Answer, temperature=0.1)

        assert provider.seen_response_formats == [Answer]
        assert provider.seen_params == [{"temperature": 0.1}]


class TestTurnCap:
    def test_the_cap_raises_with_the_run_attached(self) -> None:
        ran: list[str] = []

        def noisy(city: str) -> str:
            ran.append(city)
            return "sunny"

        provider = ScriptedProvider(
            _calls_turn(CALL, usage=Usage(total_tokens=7)),
            _calls_turn(ToolCall(id="call_2", name="get_weather", arguments={"city": "Nara"})),
        )

        with pytest.raises(ToolTurnsExceeded, match="still calling tools") as exc_info:
            provider.run_tools(
                ASK,
                model="m",
                tools=[ToolDef.from_callable(noisy, name="get_weather")],
                max_turns=2,
            )

        # The final turn's call was NOT executed: its result could never
        # reach the model. Only the first turn's tool ran.
        assert ran == ["Osaka"]
        error = exc_info.value
        assert [c.id for c in error.completion.tool_calls] == ["call_2"]
        # `.messages` ends at the last tool result -- resendable with a fresh cap.
        assert [m.role for m in error.messages] == ["user", "assistant", "tool"]
        assert error.usage == Usage(total_tokens=7)

    def test_a_cap_below_one_is_refused(self) -> None:
        provider = ScriptedProvider()

        with pytest.raises(ValueError, match="max_turns"):
            provider.run_tools(ASK, model="m", tools=[WEATHER], max_turns=0)
        assert provider.seen == []  # refused before any model call


class TestToolErrors:
    def test_a_raising_tool_becomes_the_tool_result(self) -> None:
        def flaky(city: str) -> str:
            raise RuntimeError("upstream is down")

        provider = ScriptedProvider(_calls_turn(CALL), _text_turn("Could not check."))

        run = provider.run_tools(
            ASK, model="m", tools=[ToolDef.from_callable(flaky, name="get_weather")]
        )

        # The loop continued: the error went back for the model to react to.
        tool_message = next(m for m in run.messages if m.role == "tool")
        assert tool_message.content == "Error: RuntimeError: upstream is down"
        assert run.completion.text == "Could not check."

    def test_raise_errors_reraises_the_original_and_skips_the_rest(self) -> None:
        ran: list[str] = []

        def flaky() -> str:
            raise RuntimeError("upstream is down")

        def after() -> str:
            ran.append("after")
            return "ok"

        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="flaky"), ToolCall(id="c2", name="after"))
        )

        with pytest.raises(RuntimeError, match="upstream is down"):
            provider.run_tools(
                ASK,
                model="m",
                tools=[ToolDef.from_callable(flaky), ToolDef.from_callable(after)],
                raise_errors=True,
            )
        assert ran == []

    def test_an_unknown_tool_name_is_fed_back(self) -> None:
        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="get_wether", arguments={})),
            _text_turn("sorry"),
        )

        run = provider.run_tools(ASK, model="m", tools=[WEATHER])

        tool_message = next(m for m in run.messages if m.role == "tool")
        assert tool_message.content is not None
        assert "unknown tool 'get_wether'" in tool_message.content
        assert "get_weather" in tool_message.content  # what IS available

    def test_an_unknown_tool_name_raises_when_asked(self) -> None:
        provider = ScriptedProvider(_calls_turn(ToolCall(id="c1", name="get_wether", arguments={})))

        with pytest.raises(XMagicError, match="unknown tool"):
            provider.run_tools(ASK, model="m", tools=[WEATHER], raise_errors=True)

    def test_bad_argument_types_are_fed_back_in_pydantics_words(self) -> None:
        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="get_weather", arguments={"city": [1, 2]})),
            _text_turn("retrying"),
        )

        run = provider.run_tools(ASK, model="m", tools=[WEATHER])

        tool_message = next(m for m in run.messages if m.role == "tool")
        assert tool_message.content is not None
        assert "failed validation" in tool_message.content
        assert "city" in tool_message.content


class TestArgumentDispatch:
    def test_arguments_are_coerced_through_the_tools_model(self) -> None:
        def add(a: int, b: int) -> int:
            return a + b

        provider = ScriptedProvider(
            # "3" as a string: strict mode is off for vendors that lack it,
            # and a model that answers loosely should still land.
            _calls_turn(ToolCall(id="c1", name="add", arguments={"a": "3", "b": 4})),
            _text_turn("7"),
        )

        run = provider.run_tools(ASK, model="m", tools=[ToolDef.from_callable(add)])

        assert next(m for m in run.messages if m.role == "tool").content == "7"

    def test_a_nested_model_parameter_arrives_as_an_instance(self) -> None:
        received: list[Any] = []

        def search(query: str, filters: Filters) -> str:
            received.append(filters)
            return "found"

        provider = ScriptedProvider(
            _calls_turn(
                ToolCall(
                    id="c1",
                    name="search",
                    arguments={"query": "q", "filters": {"since": "2026"}},
                )
            ),
            _text_turn("done"),
        )

        provider.run_tools(ASK, model="m", tools=[ToolDef.from_callable(search)])

        assert received == [Filters(since="2026")]

    def test_a_hand_built_tooldef_with_a_callable_passes_arguments_raw(self) -> None:
        received: list[Any] = []

        def grab(**kwargs: Any) -> str:
            received.append(kwargs)
            return "ok"

        # No arguments_model, so there is nothing to validate through; the
        # parsed dict goes in as-is. (`from_callable` would refuse **kwargs.)
        tool = ToolDef(name="grab", parameters={"type": "object", "properties": {}}, fn=grab)
        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="grab", arguments={"x": 1})),
            _text_turn("done"),
        )

        provider.run_tools(ASK, model="m", tools=[tool])

        assert received == [{"x": 1}]


class Filters(BaseModel):
    """Module level, so postponed annotations resolve it (stage C's rule)."""

    since: str


class TestResultSerialization:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("plain", "plain"),
            (None, ""),
            (Filters(since="2026"), '{"since":"2026"}'),
            ({"n": 3}, '{"n":3}'),
            ([1, 2], "[1,2]"),
        ],
    )
    def test_returns_become_wire_text(self, value: Any, expected: str) -> None:
        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="give", arguments={})),
            _text_turn("done"),
        )

        def give() -> Any:
            return value

        run = provider.run_tools(ASK, model="m", tools=[ToolDef.from_callable(give)])

        assert next(m for m in run.messages if m.role == "tool").content == expected

    def test_an_unserializable_return_is_a_tool_error(self) -> None:
        def give() -> Any:
            return object()

        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="give", arguments={})),
            _text_turn("done"),
        )

        run = provider.run_tools(ASK, model="m", tools=[ToolDef.from_callable(give)])

        tool_message = next(m for m in run.messages if m.role == "tool")
        assert tool_message.content is not None
        assert "does not serialize" in tool_message.content


class TestPreflight:
    """Caller mistakes fail before any tokens are spent."""

    def test_no_tools_is_refused(self) -> None:
        provider = ScriptedProvider()

        with pytest.raises(ValueError, match="at least one tool"):
            provider.run_tools(ASK, model="m", tools=[])

    def test_duplicate_names_are_refused(self) -> None:
        provider = ScriptedProvider()

        with pytest.raises(ValueError, match="get_weather"):
            provider.run_tools(ASK, model="m", tools=[WEATHER, WEATHER])

    def test_a_tooldef_without_a_callable_is_refused(self) -> None:
        provider = ScriptedProvider()
        schema_only = ToolDef(name="get_weather", parameters={"type": "object"})

        with pytest.raises(TypeError, match="from_callable"):
            provider.run_tools(ASK, model="m", tools=[schema_only])

    def test_an_async_tool_is_pointed_at_arun_tools(self) -> None:
        async def lookup(city: str) -> str:
            return "sunny"

        provider = ScriptedProvider()

        with pytest.raises(TypeError, match="arun_tools"):
            provider.run_tools(ASK, model="m", tools=[ToolDef.from_callable(lookup)])

    def test_a_sync_tool_returning_an_awaitable_raises_either_way(self) -> None:
        async def inner() -> str:
            return "sunny"

        def forgot_await() -> Any:
            return inner()

        provider = ScriptedProvider(
            _calls_turn(ToolCall(id="c1", name="forgot_await", arguments={}))
        )

        # Not fed back even with raise_errors=False: the model cannot fix a
        # missing await, and the coroutine is closed rather than leaked.
        with pytest.raises(TypeError, match="returned an awaitable"):
            provider.run_tools(ASK, model="m", tools=[ToolDef.from_callable(forgot_await)])


class TestToolDefStaysComparable:
    """The new fields must not change what equality and repr mean."""

    def test_equality_ignores_the_callable(self) -> None:
        def get_weather(city: str) -> str:
            """Look up the weather."""
            return "sunny"

        rebuilt = ToolDef.from_callable(get_weather)
        by_hand = ToolDef(
            name=rebuilt.name,
            description=rebuilt.description,
            parameters=rebuilt.parameters,
            strict=rebuilt.strict,
        )

        assert rebuilt == by_hand
        assert "fn=" not in repr(rebuilt)


class TestAsyncLoop:
    async def test_async_and_sync_tools_mix(self) -> None:
        async def temperature(city: str) -> int:
            return 24

        def unit() -> str:
            return "celsius"

        provider = ScriptedProvider(
            _calls_turn(
                ToolCall(id="c1", name="temperature", arguments={"city": "Osaka"}),
                ToolCall(id="c2", name="unit"),
            ),
            _text_turn("24C"),
        )

        run = await provider.arun_tools(
            ASK,
            model="m",
            tools=[ToolDef.from_callable(temperature), ToolDef.from_callable(unit)],
        )

        assert [m.content for m in run.messages if m.role == "tool"] == ["24", "celsius"]
        assert run.completion.text == "24C"

    async def test_the_model_call_leaves_the_event_loop_thread(self) -> None:
        provider = ScriptedProvider(_text_turn("hi"))

        await provider.arun_tools(ASK, model="m", tools=[WEATHER])

        assert provider.seen_threads != [threading.get_ident()]

    async def test_a_raising_async_tool_is_fed_back(self) -> None:
        async def flaky(city: str) -> str:
            raise RuntimeError("upstream is down")

        provider = ScriptedProvider(_calls_turn(CALL), _text_turn("sorry"))

        run = await provider.arun_tools(
            ASK, model="m", tools=[ToolDef.from_callable(flaky, name="get_weather")]
        )

        tool_message = next(m for m in run.messages if m.role == "tool")
        assert tool_message.content == "Error: RuntimeError: upstream is down"

    async def test_the_cap_raises_here_too(self) -> None:
        provider = ScriptedProvider(_calls_turn(CALL))

        with pytest.raises(ToolTurnsExceeded):
            await provider.arun_tools(ASK, model="m", tools=[WEATHER], max_turns=1)


def _wire_tool_call_reply() -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Osaka"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def _wire_text_reply(text: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-2",
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


def _assert_second_request_carries_the_tool_turn(route: respx.Route) -> None:
    """The history the loop builds must survive `messages_to_wire`."""
    sent = json.loads(route.calls[1].request.content)["messages"]
    assistant = sent[1]
    assert assistant["role"] == "assistant"
    # Arguments go back as the JSON string the wire wants, not our parsed dict.
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"city": "Osaka"}'
    tool = sent[2]
    assert tool == {"role": "tool", "content": "sunny in Osaka", "tool_call_id": "call_1"}


class TestOverTheWire:
    @respx.mock
    def test_openai_round_trip(self) -> None:
        from xmagic.providers.openai import OpenAIProvider

        route = respx.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(200, json=_wire_tool_call_reply()),
                httpx.Response(200, json=_wire_text_reply("Sunny in Osaka.")),
            ]
        )

        run = OpenAIProvider(api_key="sk-test").run_tools(ASK, model="gpt-5", tools=[WEATHER])

        assert run.completion.text == "Sunny in Osaka."
        _assert_second_request_carries_the_tool_turn(route)

    @respx.mock
    def test_litellm_round_trip(self) -> None:
        pytest.importorskip("litellm")
        from xmagic.providers.litellm import LiteLLMProvider

        route = respx.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(200, json=_wire_tool_call_reply()),
                httpx.Response(200, json=_wire_text_reply("Sunny in Osaka.")),
            ]
        )

        run = LiteLLMProvider(api_key="sk-test").run_tools(
            ASK, model="openai/gpt-5", tools=[WEATHER]
        )

        assert run.completion.text == "Sunny in Osaka."
        _assert_second_request_carries_the_tool_turn(route)

    @respx.mock
    def test_response_format_lands_on_the_answering_turn(self) -> None:
        from xmagic.providers.openai import OpenAIProvider

        class Answer(BaseModel):
            city: str
            summary: str

        respx.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(200, json=_wire_tool_call_reply()),
                httpx.Response(
                    200,
                    json=_wire_text_reply('{"city": "Osaka", "summary": "sunny"}'),
                ),
            ]
        )

        run = OpenAIProvider(api_key="sk-test").run_tools(
            ASK, model="gpt-5", tools=[WEATHER], response_format=Answer
        )

        # The tool-calling turn owed no schema (its parsed is None by the
        # adapters' rule); the answering turn validated.
        assert run.completion.parsed == Answer(city="Osaka", summary="sunny")

    def test_the_xmagic_adapter_fails_on_the_first_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from xmagic.providers.xmagic import XMagicProvider

        monkeypatch.setattr(XMagicProvider, "__init__", lambda self, **kw: None)

        with pytest.raises(XMagicError, match="registered in the dashboard"):
            XMagicProvider().run_tools(ASK, model="agent", tools=[WEATHER])
