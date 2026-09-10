"""Tool calling as a typed surface — DESIGN.md §13, stages A and C.

Before this, `capabilities()` advertised `tools: True` while `Provider.complete`
had no `tools` parameter and `ChatMessage` had no `tool_call_id`, so a tool
result could not be represented at all. Tools "worked" only by `**params`
passthrough with the caller digging results out of `raw`.

The mapping is exercised against the OpenAI wire shape through both adapters,
which is the whole bet of §13.2: LiteLLM normalizes every vendor onto that
shape, so one mapping is not one vendor's.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from xmagic.errors import XMagicError
from xmagic.providers._openai_wire import (
    ToolCallAccumulator,
    messages_to_wire,
    tool_calls_from_wire,
    tools_to_wire,
)
from xmagic.providers.base import ChatMessage, TextPart, ToolCall, ToolDef
from xmagic.providers.openai import OpenAIProvider

CHAT_URL = "https://api.openai.com/v1/chat/completions"


class Filters(BaseModel):
    """A nested model, at module level -- see the resolution test below."""

    since: str


WEATHER = ToolDef(
    name="get_weather",
    description="Look up the weather.",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
        "additionalProperties": False,
    },
    strict=True,
)


def _tool_call_response(arguments: str = '{"city": "Osaka"}') -> dict[str, Any]:
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
                    # An assistant turn that only calls tools has no text -- the
                    # case that made `content: str` the real blocker (§13.3).
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def _sse(*frames: dict[str, Any]) -> str:
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames)
    return body + "data: [DONE]\n\n"


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-5",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _fragment(
    index: int = 0,
    *,
    id_: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> dict[str, Any]:
    """One streamed tool-call fragment, shaped as OpenAI sends them.

    The opening fragment carries `id` and `name`; the rest carry only a slice of
    the argument string. Omitted keys are genuinely absent from the wire, not
    null, which is what the accumulator has to tolerate.
    """
    function: dict[str, Any] = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    fragment: dict[str, Any] = {"index": index, "function": function}
    if id_ is not None:
        fragment["id"] = id_
        fragment["type"] = "function"
    return fragment


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="sk-test")


class TestSchemaFromCallables:
    """Stage C: a tool is written once, not twice."""

    def test_signature_and_docstring_become_the_definition(self) -> None:
        def get_weather(city: str, units: str) -> str:
            """Look up the weather in a city."""
            return "sunny"

        tool = ToolDef.from_callable(get_weather)

        assert tool.name == "get_weather"
        assert tool.description == "Look up the weather in a city."
        assert set(tool.parameters["properties"]) == {"city", "units"}
        assert tool.parameters["properties"]["city"]["type"] == "string"
        assert set(tool.parameters["required"]) == {"city", "units"}

    def test_a_fully_required_schema_is_marked_strict(self) -> None:
        def echo(text: str) -> str:
            """Echo."""
            return text

        tool = ToolDef.from_callable(echo)

        # Both are conditions of strict mode; sending one without the other is
        # rejected by the vendor.
        assert tool.strict is True
        assert tool.parameters["additionalProperties"] is False

    def test_a_default_disables_strict_rather_than_sending_an_invalid_schema(self) -> None:
        def search(query: str, limit: int = 10) -> str:
            """Search."""
            return query

        tool = ToolDef.from_callable(search)

        # Strict mode requires every property to be required. Claiming it here
        # would have the vendor reject the whole request.
        assert tool.strict is False
        assert "additionalProperties" not in tool.parameters
        assert tool.parameters["required"] == ["query"]

    def test_a_nested_model_is_not_claimed_as_strict(self) -> None:
        def search(query: str, filters: Filters) -> str:
            """Search with filters."""
            return query

        tool = ToolDef.from_callable(search)

        # `$defs` means nested objects this does not rewrite, and strict applies
        # at every level -- so the flat case is the only one claimed.
        assert "$defs" in tool.parameters
        assert tool.strict is False

    def test_name_and_description_can_be_overridden(self) -> None:
        def _internal_name(x: int) -> int:
            """Docstring nobody wants shown."""
            return x

        tool = ToolDef.from_callable(_internal_name, name="double", description="Double it.")

        assert (tool.name, tool.description) == ("double", "Double it.")

    def test_an_unannotated_parameter_is_refused(self) -> None:
        def bad(city) -> str:  # type: ignore[no-untyped-def]
            """No annotation."""
            return str(city)

        with pytest.raises(ValueError, match="no type annotation"):
            ToolDef.from_callable(bad)

    def test_a_locally_defined_type_fails_with_a_usable_message(self) -> None:
        """The bare failure is a `NameError` naming a type and nothing else.

        `from __future__ import annotations` turns annotations into strings, and
        a class defined inside a function is not in the namespace that resolves
        them. Common enough to be worth explaining rather than propagating.
        """

        class Local(BaseModel):
            x: int

        def search(filters: Local) -> str:
            """Search."""
            return ""

        with pytest.raises(ValueError, match="could not resolve its annotations"):
            ToolDef.from_callable(search)

    def test_varargs_are_refused(self) -> None:
        def bad(*args: int) -> int:
            """Not expressible."""
            return 0

        with pytest.raises(ValueError, match=r"\*args"):
            ToolDef.from_callable(bad)


class TestWireMapping:
    def test_a_plain_message_is_unchanged(self) -> None:
        assert messages_to_wire([ChatMessage(role="user", content="hi")]) == [
            {"role": "user", "content": "hi"}
        ]

    def test_structured_content_becomes_typed_parts(self) -> None:
        wire = messages_to_wire([ChatMessage(role="user", content=[TextPart("a"), TextPart("b")])])

        assert wire[0]["content"] == [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]

    def test_a_tool_call_turn_carries_no_text_and_keeps_its_calls(self) -> None:
        message = ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})],
        )

        (wire,) = messages_to_wire([message])

        assert wire["content"] is None
        # Back to a JSON string on the wire; the parsed dict is this SDK's
        # contract with its callers, not the vendor's.
        assert wire["tool_calls"][0]["function"] == {
            "name": "get_weather",
            "arguments": '{"city": "Osaka"}',
        }

    def test_a_result_is_correlated_with_the_call_that_asked_for_it(self) -> None:
        (wire,) = messages_to_wire(
            [ChatMessage(role="tool", tool_call_id="call_1", content="sunny, 24C")]
        )

        assert wire == {"role": "tool", "content": "sunny, 24C", "tool_call_id": "call_1"}

    def test_strict_is_sent_only_when_set(self) -> None:
        (strict,) = tools_to_wire([WEATHER])
        (loose,) = tools_to_wire([ToolDef(name="anything")])

        assert strict["function"]["strict"] is True
        # Not every OpenAI-compatible backend knows the key, and sending it at
        # its default value is a needless thing to fail on.
        assert "strict" not in loose["function"]

    def test_raw_vendor_dicts_are_refused_with_a_usable_message(self) -> None:
        """The old `**params` passthrough now binds to a typed parameter.

        Before `tools=` existed, raw OpenAI dicts through `**params` were the
        only way to pass tools. They now reach `tools_to_wire` and would fail as
        `AttributeError: 'dict' object has no attribute 'name'` three frames
        down, which tells the caller nothing about the fix.
        """
        raw = [{"type": "function", "function": {"name": "get_weather"}}]

        with pytest.raises(TypeError, match=r"ToolDef\.from_callable"):
            tools_to_wire(raw)  # type: ignore[arg-type]

    def test_arguments_arrive_parsed(self) -> None:
        message = _FakeMessage([_FakeCall("call_1", "get_weather", '{"city": "Osaka"}')])

        assert tool_calls_from_wire(message) == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]

    def test_a_backend_that_already_parsed_them_is_accepted(self) -> None:
        message = _FakeMessage([_FakeCall("call_1", "get_weather", {"city": "Osaka"})])

        assert tool_calls_from_wire(message)[0].arguments == {"city": "Osaka"}

    def test_unparseable_arguments_are_raised_not_swallowed(self) -> None:
        message = _FakeMessage([_FakeCall("call_1", "get_weather", '{"city": ')])

        with pytest.raises(XMagicError) as excinfo:
            tool_calls_from_wire(message)

        # Naming the tool and showing the raw string is the difference between
        # a debuggable failure and a KeyError inside someone's tool.
        assert "get_weather" in str(excinfo.value)
        assert "strict" in str(excinfo.value)

    def test_a_response_with_no_tool_calls_yields_none(self) -> None:
        assert tool_calls_from_wire(_FakeMessage(None)) == []


class _FakeCall:
    def __init__(self, id_: str, name: str, arguments: Any) -> None:
        self.id = id_
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _FakeMessage:
    def __init__(self, calls: list[_FakeCall] | None) -> None:
        self.tool_calls = calls


class TestOpenAIAdapter:
    @respx.mock
    def test_tools_reach_the_request_and_calls_come_back_typed(
        self, provider: OpenAIProvider
    ) -> None:
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_tool_call_response())
        )

        result = provider.complete(
            [ChatMessage(role="user", content="weather in Osaka?")],
            model="gpt-5",
            tools=[WEATHER],
        )

        sent = json.loads(route.calls.last.request.content)
        assert sent["tools"][0]["function"]["name"] == "get_weather"
        assert result.text == ""  # the turn was a tool call, not an answer
        assert result.tool_calls == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]

    @respx.mock
    def test_the_full_round_trip_reaches_the_wire(self, provider: OpenAIProvider) -> None:
        """Call, run it, feed the result back — the loop a caller writes."""
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_tool_call_response())
        )
        messages = [ChatMessage(role="user", content="weather in Osaka?")]

        first = provider.complete(messages, model="gpt-5", tools=[WEATHER])
        call = first.tool_calls[0]
        messages += [
            ChatMessage(role="assistant", content=None, tool_calls=first.tool_calls),
            ChatMessage(
                role="tool", tool_call_id=call.id, content=f"sunny in {call.arguments['city']}"
            ),
        ]
        provider.complete(messages, model="gpt-5", tools=[WEATHER])

        sent = json.loads(route.calls.last.request.content)["messages"]
        assert [m["role"] for m in sent] == ["user", "assistant", "tool"]
        assert sent[1]["tool_calls"][0]["id"] == "call_1"
        assert sent[2]["tool_call_id"] == "call_1"
        assert sent[2]["content"] == "sunny in Osaka"

    @respx.mock
    def test_no_tools_means_no_tools_key(self, provider: OpenAIProvider) -> None:
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "c1",
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
            )
        )

        result = provider.complete([ChatMessage(role="user", content="hi")], model="gpt-5")

        assert "tools" not in json.loads(route.calls.last.request.content)
        assert result.tool_calls == []

    @respx.mock
    def test_no_tools_leaves_the_terminal_chunk_empty(self, provider: OpenAIProvider) -> None:
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(_chunk({"content": "hi"}), _chunk({}, finish_reason="stop")),
            )
        )

        chunks = list(provider.stream([ChatMessage(role="user", content="hi")], model="gpt-5"))

        assert [c.text for c in chunks] == ["hi", ""]
        assert chunks[-1].tool_calls == []


class TestStreamedToolCalls:
    """Stage B: fragments in, whole calls out.

    The failure this guards is not a crash. A model streaming a tool call sends
    `arguments` as JSON slices that are individually invalid, so an adapter that
    forwards deltas naively loses the call entirely and the stream still looks
    successful.
    """

    @respx.mock
    def test_argument_fragments_reassemble_into_one_call(self, provider: OpenAIProvider) -> None:
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    _chunk({"tool_calls": [_fragment(id_="call_1", name="get_weather")]}),
                    _chunk({"tool_calls": [_fragment(arguments='{"ci')]}),
                    _chunk({"tool_calls": [_fragment(arguments='ty": "Osa')]}),
                    _chunk({"tool_calls": [_fragment(arguments='ka"}')]}),
                    _chunk({}, finish_reason="tool_calls"),
                ),
            )
        )

        chunks = list(
            provider.stream(
                [ChatMessage(role="user", content="weather in Osaka?")],
                model="gpt-5",
                tools=[WEATHER],
            )
        )

        assert (
            json.loads(route.calls.last.request.content)["tools"][0]["function"]["name"]
            == "get_weather"
        )
        # Four fragment deltas produced no visible chunk at all: a half-built
        # call cannot be told apart from a finished one, so there is nothing
        # honest to emit until the arguments close.
        assert len(chunks) == 1
        assert chunks[-1].done
        assert chunks[-1].tool_calls == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]

    @respx.mock
    def test_text_and_a_call_in_one_turn_stay_separate(self, provider: OpenAIProvider) -> None:
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    _chunk({"content": "Let me check. "}),
                    _chunk({"tool_calls": [_fragment(id_="call_1", name="get_weather")]}),
                    _chunk({"tool_calls": [_fragment(arguments='{"city": "Osaka"}')]}),
                    _chunk({}, finish_reason="tool_calls"),
                ),
            )
        )

        chunks = list(
            provider.stream(
                [ChatMessage(role="user", content="weather?")], model="gpt-5", tools=[WEATHER]
            )
        )

        assert "".join(c.text for c in chunks) == "Let me check. "
        # The text chunk is emitted while the call is still accumulating, and
        # carries none of it -- only the terminal chunk does.
        assert [bool(c.tool_calls) for c in chunks] == [False, True]
        assert chunks[-1].tool_calls[0].arguments == {"city": "Osaka"}

    @respx.mock
    def test_parallel_calls_are_keyed_by_index_not_arrival_order(
        self, provider: OpenAIProvider
    ) -> None:
        """Two calls whose fragments interleave — the case order alone gets wrong."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    _chunk({"tool_calls": [_fragment(0, id_="call_a", name="get_weather")]}),
                    _chunk({"tool_calls": [_fragment(1, id_="call_b", name="get_weather")]}),
                    # Interleaved, and the second call's slice arrives first.
                    _chunk({"tool_calls": [_fragment(1, arguments='{"city": "Kyo')]}),
                    _chunk({"tool_calls": [_fragment(0, arguments='{"city": "Osa')]}),
                    _chunk({"tool_calls": [_fragment(1, arguments='to"}')]}),
                    _chunk({"tool_calls": [_fragment(0, arguments='ka"}')]}),
                    _chunk({}, finish_reason="tool_calls"),
                ),
            )
        )

        calls = list(
            provider.stream(
                [ChatMessage(role="user", content="both?")], model="gpt-5", tools=[WEATHER]
            )
        )[-1].tool_calls

        assert [c.id for c in calls] == ["call_a", "call_b"]
        assert [c.arguments["city"] for c in calls] == ["Osaka", "Kyoto"]

    @respx.mock
    def test_a_backend_that_omits_index_still_works(self, provider: OpenAIProvider) -> None:
        # `index` is required of OpenAI but not of every OpenAI-compatible
        # backend reachable through `base_url`; position stands in for it.
        fragment = _fragment(id_="call_1", name="get_weather", arguments='{"city": "Osaka"}')
        del fragment["index"]
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    _chunk({"tool_calls": [fragment]}),
                    _chunk({}, finish_reason="tool_calls"),
                ),
            )
        )

        chunks = list(
            provider.stream(
                [ChatMessage(role="user", content="weather?")], model="gpt-5", tools=[WEATHER]
            )
        )

        assert chunks[-1].tool_calls == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]

    @respx.mock
    def test_a_truncated_call_raises_rather_than_arriving_half_built(
        self, provider: OpenAIProvider
    ) -> None:
        """A model that hits the token limit mid-arguments, the realistic failure."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    _chunk({"tool_calls": [_fragment(id_="call_1", name="get_weather")]}),
                    _chunk({"tool_calls": [_fragment(arguments='{"city": "Osa')]}),
                    _chunk({}, finish_reason="length"),
                ),
            )
        )

        with pytest.raises(XMagicError, match="get_weather"):
            list(
                provider.stream(
                    [ChatMessage(role="user", content="weather?")],
                    model="gpt-5",
                    tools=[WEATHER],
                )
            )

    @respx.mock
    def test_a_stream_that_closes_without_a_finish_reason_still_raises(
        self, provider: OpenAIProvider
    ) -> None:
        """The server hangs up mid-call and never sends `finish_reason`.

        Found in review: the OpenAI adapter emitted its terminal chunk only on
        `finish_reason`, so this case yielded nothing at all and the half-built
        call vanished without an error -- the LiteLLM adapter, which closes
        after the loop, already raised here.
        """
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content="".join(
                    f"data: {json.dumps(f)}\n\n"
                    for f in (
                        _chunk({"tool_calls": [_fragment(id_="call_1", name="get_weather")]}),
                        _chunk({"tool_calls": [_fragment(arguments='{"city": "Osa')]}),
                    )
                ),  # no finish_reason and no [DONE]
            )
        )

        with pytest.raises(XMagicError, match="get_weather"):
            list(
                provider.stream(
                    [ChatMessage(role="user", content="weather?")],
                    model="gpt-5",
                    tools=[WEATHER],
                )
            )


class TestAccumulator:
    """The pieces of stage B that no adapter round trip reaches."""

    def test_deltas_without_tool_calls_are_ignored(self) -> None:
        accumulator = ToolCallAccumulator()

        accumulator.add(_FakeDelta(None))
        accumulator.add(_FakeDelta([]))

        assert accumulator.finish() == []

    def test_arguments_already_parsed_are_taken_as_they_are(self) -> None:
        # Not OpenAI's shape, but some compatible backends send an object --
        # the same tolerance `_arguments_to_dict` has on the blocking path.
        accumulator = ToolCallAccumulator()

        accumulator.add(_FakeDelta([_FakeFragment(0, "call_1", "get_weather", {"city": "Osaka"})]))

        assert accumulator.finish() == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]

    def test_a_call_with_no_arguments_at_all_is_still_a_call(self) -> None:
        # A zero-parameter tool sends no argument fragments; an empty string is
        # not valid JSON, so this would raise if it reached the parser bare.
        accumulator = ToolCallAccumulator()

        accumulator.add(_FakeDelta([_FakeFragment(0, "call_1", "ping", None)]))

        assert accumulator.finish() == [ToolCall(id="call_1", name="ping", arguments={})]


class _FakeFragment:
    def __init__(self, index: int, id_: str | None, name: str | None, arguments: Any) -> None:
        self.index = index
        self.id = id_
        self.function = _FakeFunction(name, arguments)


class _FakeFunction:
    def __init__(self, name: str | None, arguments: Any) -> None:
        self.name = name
        self.arguments = arguments


class _FakeDelta:
    def __init__(self, tool_calls: list[_FakeFragment] | None) -> None:
        self.tool_calls = tool_calls


class TestLiteLLMAdapter:
    """The same mapping, through the adapter that reaches ~150 vendors."""

    @pytest.fixture
    def provider(self) -> Any:
        pytest.importorskip("litellm")
        from xmagic.providers.litellm import LiteLLMProvider

        return LiteLLMProvider(api_key="sk-test")

    @respx.mock
    def test_tool_calls_come_back_typed(self, provider: Any) -> None:
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_tool_call_response())
        )

        result = provider.complete(
            [ChatMessage(role="user", content="weather in Osaka?")],
            model="openai/gpt-5",
            tools=[WEATHER],
        )

        assert (
            json.loads(route.calls.last.request.content)["tools"][0]["function"]["strict"] is True
        )
        assert result.tool_calls == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]

    @respx.mock
    def test_streamed_calls_survive_the_second_adapter_too(self, provider: Any) -> None:
        """The bet of §13.2, on the streaming path: one accumulator, ~150 vendors."""
        respx.post(CHAT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    _chunk({"tool_calls": [_fragment(id_="call_1", name="get_weather")]}),
                    _chunk({"tool_calls": [_fragment(arguments='{"city": "Os')]}),
                    _chunk({"tool_calls": [_fragment(arguments='aka"}')]}),
                    _chunk({}, finish_reason="tool_calls"),
                ),
            )
        )

        chunks = list(
            provider.stream(
                [ChatMessage(role="user", content="weather in Osaka?")],
                model="openai/gpt-5",
                tools=[WEATHER],
            )
        )

        assert chunks[-1].done
        assert chunks[-1].tool_calls == [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "Osaka"})
        ]


class TestXMagicAdapterRejects:
    """D4: the flag means per-call tools, and xMagic has none."""

    @pytest.fixture
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        from xmagic.providers.xmagic import XMagicProvider

        monkeypatch.setattr(XMagicProvider, "__init__", lambda self, **kw: None)
        return XMagicProvider()

    def test_capabilities_does_not_claim_per_call_tools(self, provider: Any) -> None:
        # Not a downgrade: xMagic's tools are real, but registered in the
        # dashboard and attached to an agent, which this dict has no word for.
        assert provider.capabilities()["tools"] is False

    def test_complete_refuses_tools_rather_than_ignoring_them(self, provider: Any) -> None:
        with pytest.raises(XMagicError, match="registered in the dashboard"):
            provider.complete([ChatMessage(role="user", content="hi")], model="a", tools=[WEATHER])

    def test_stream_refuses_them_too(self, provider: Any) -> None:
        with pytest.raises(XMagicError, match="registered in the dashboard"):
            list(
                provider.stream(
                    [ChatMessage(role="user", content="hi")], model="a", tools=[WEATHER]
                )
            )


def test_structured_content_flattens_for_the_xmagic_query_endpoint() -> None:
    # That endpoint takes one query string, so parts join and a bodyless
    # assistant turn contributes nothing rather than the word "None".
    from xmagic.providers.xmagic import _flatten

    flattened = _flatten(
        [
            ChatMessage(role="user", content=[TextPart("first"), TextPart("second")]),
            ChatMessage(role="assistant", content=None),
        ]
    )

    assert "first\nsecond" in flattened
    assert "None" not in flattened
