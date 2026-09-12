"""``xmagic chat --schema``: a JSON Schema file in, a validated `parsed` out.

The provider interface takes a pydantic class (DESIGN.md §14.1). The CLI
builds one from the file for the subset a response format uses, and refuses
the rest by name, so a constraint the vendor would never see is not silently
dropped. Driven over the OpenAI wire, the same way test_structured_output does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response
from pydantic import BaseModel
from typer.testing import CliRunner

from xmagic.cli._schema import SchemaError, load_schema_model, schema_to_model
from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL
from xmagic.providers._openai_wire import response_format_to_wire

CHAT_URL = "https://api.openai.com/v1/chat/completions"
AGENT = "agent-1"
XMAGIC_CHATS_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats"

runner = CliRunner()

WEATHER = {
    "title": "Weather",
    "type": "object",
    "properties": {
        "city": {"type": "string", "description": "City name"},
        "temp_c": {"type": "number"},
    },
    "required": ["city", "temp_c"],
}
OSAKA = '{"city": "Osaka", "temp_c": 24.0}'


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))


@pytest.fixture
def schema_file(tmp_path: Path) -> Path:
    path = tmp_path / "weather.json"
    path.write_text(json.dumps(WEATHER), encoding="utf-8")
    return path


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


def _sse(*frames: dict[str, Any]) -> Response:
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n"
    return Response(200, text=body, headers={"content-type": "text/event-stream"})


def _sent_response_format(route: respx.Route) -> dict[str, Any]:
    body = json.loads(route.calls.last.request.read())
    return body["response_format"]  # type: ignore[no-any-return]


class TestSchemaToModel:
    def test_the_file_becomes_a_model_named_after_its_title(self, schema_file: Path) -> None:
        model = load_schema_model(schema_file)

        assert issubclass(model, BaseModel)
        assert model.__name__ == "Weather"
        instance = model.model_validate_json(OSAKA)
        assert instance.model_dump() == {"city": "Osaka", "temp_c": 24.0}

    def test_a_flat_fully_required_schema_claims_strict(self, schema_file: Path) -> None:
        wire = response_format_to_wire(load_schema_model(schema_file))

        assert wire["json_schema"]["strict"] is True
        assert wire["json_schema"]["schema"]["required"] == ["city", "temp_c"]
        assert wire["json_schema"]["schema"]["properties"]["city"]["description"] == "City name"

    def test_the_filename_names_the_model_when_there_is_no_title(self, tmp_path: Path) -> None:
        path = tmp_path / "weather-report.json"
        path.write_text(json.dumps({k: v for k, v in WEATHER.items() if k != "title"}))

        assert load_schema_model(path).__name__ == "weather_report"

    def test_nested_objects_arrays_enums_and_optionals(self) -> None:
        model = schema_to_model(
            {
                "type": "object",
                "properties": {
                    "sky": {"enum": ["clear", "cloudy"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "wind": {
                        "type": "object",
                        "properties": {"kph": {"type": "integer", "minimum": 0}},
                        "required": ["kph"],
                    },
                    "note": {"type": ["string", "null"]},
                    "source": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                },
                "required": ["sky", "wind"],
            }
        )

        instance = model.model_validate_json('{"sky": "clear", "wind": {"kph": 3}}')
        assert instance.model_dump() == {
            "sky": "clear",
            "tags": None,
            "wind": {"kph": 3},
            "note": None,
            "source": None,
        }
        with pytest.raises(ValueError, match="sky"):
            model.model_validate_json('{"sky": "hazy", "wind": {"kph": 3}}')
        with pytest.raises(ValueError, match="kph"):
            model.model_validate_json('{"sky": "clear", "wind": {"kph": -1}}')

    def test_a_default_is_kept(self) -> None:
        model = schema_to_model(
            {"type": "object", "properties": {"unit": {"type": "string", "default": "C"}}}
        )

        assert model.model_validate_json("{}").model_dump() == {"unit": "C"}

    @pytest.mark.parametrize(
        ("schema", "reason"),
        [
            ({"type": "array", "items": {"type": "string"}}, "root schema must be an object"),
            ({"type": "object"}, "non-empty 'properties'"),
            (
                {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}},
                r"does not map: \$ref",
            ),
            (
                {"type": "object", "properties": {"a": {"type": "string", "format": "date"}}},
                "does not map: format",
            ),
            (
                {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]},
                "do not exist",
            ),
            ({"type": "object", "properties": {"a": {}}}, "has no 'type'"),
            ({"type": "object", "properties": {"a": {"type": "array"}}}, "needs an 'items'"),
            (
                {"type": "object", "properties": {"a": {"type": "tuple"}}},
                "unsupported type 'tuple'",
            ),
        ],
    )
    def test_the_unmapped_is_refused_by_name(self, schema: dict[str, Any], reason: str) -> None:
        with pytest.raises(SchemaError, match=reason):
            schema_to_model(schema)

    def test_unreadable_files_say_why(self, tmp_path: Path) -> None:
        not_json = tmp_path / "s.json"
        not_json.write_text("{not json")
        with pytest.raises(SchemaError, match="not valid JSON"):
            load_schema_model(not_json)

        a_list = tmp_path / "list.json"
        a_list.write_text("[]")
        with pytest.raises(SchemaError, match="is an object, not a list"):
            load_schema_model(a_list)

        with pytest.raises(SchemaError, match="cannot read"):
            load_schema_model(tmp_path / "missing.json")


class TestChatSchemaFlag:
    @respx.mock
    def test_json_output_carries_parsed(self, schema_file: Path) -> None:
        route = respx.post(CHAT_URL).mock(return_value=Response(200, json=_completion(OSAKA)))

        result = runner.invoke(
            app,
            [
                "chat",
                "-m",
                "openai:gpt-5",
                "--json",
                "--no-stream",
                "--schema",
                str(schema_file),
                "hi",
            ],
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["parsed"] == {"city": "Osaka", "temp_c": 24.0}
        assert document["text"] == OSAKA
        sent = _sent_response_format(route)
        assert sent["type"] == "json_schema"
        assert sent["json_schema"]["name"] == "Weather"

    @respx.mock
    def test_streamed_parsed_lands_from_the_terminal_chunk(self, schema_file: Path) -> None:
        respx.post(CHAT_URL).mock(
            return_value=_sse(
                _chunk({"role": "assistant", "content": '{"city": "Osaka",'}),
                _chunk({"content": ' "temp_c": 24.0}'}),
                _chunk({}, finish_reason="stop"),
            )
        )

        result = runner.invoke(
            app, ["chat", "-m", "openai:gpt-5", "--json", "--schema", str(schema_file), "hi"]
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["parsed"] == {"city": "Osaka", "temp_c": 24.0}
        assert document["text"] == '{"city": "Osaka", "temp_c": 24.0}'

    @respx.mock
    def test_without_the_flag_parsed_is_null_and_nothing_is_sent(self) -> None:
        route = respx.post(CHAT_URL).mock(return_value=Response(200, json=_completion("hi")))

        result = runner.invoke(app, ["chat", "-m", "openai:gpt-5", "--json", "--no-stream", "hi"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["parsed"] is None
        assert "response_format" not in json.loads(route.calls.last.request.read())

    @respx.mock
    def test_plain_output_is_still_validated(self, schema_file: Path) -> None:
        respx.post(CHAT_URL).mock(return_value=Response(200, json=_completion("not json")))

        result = runner.invoke(
            app, ["chat", "-m", "openai:gpt-5", "--no-stream", "--schema", str(schema_file), "hi"]
        )

        assert result.exit_code == 1
        assert "did not validate as Weather" in result.stderr

    @respx.mock
    def test_a_refusal_fails_in_the_vendors_words(self, schema_file: Path) -> None:
        respx.post(CHAT_URL).mock(
            return_value=Response(200, json=_completion(None, refusal="I cannot help with that."))
        )

        result = runner.invoke(
            app,
            [
                "chat",
                "-m",
                "openai:gpt-5",
                "--json",
                "--no-stream",
                "--schema",
                str(schema_file),
                "hi",
            ],
        )

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "I cannot help with that." in result.stderr

    @respx.mock
    def test_a_bad_schema_fails_before_any_request(self, tmp_path: Path) -> None:
        route = respx.post(CHAT_URL).mock(return_value=Response(200, json=_completion(OSAKA)))
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"type": "object", "properties": {"a": {"$ref": "#/x"}}}))

        result = runner.invoke(app, ["chat", "-m", "openai:gpt-5", "--schema", str(bad), "hi"])

        assert result.exit_code == 2
        assert "$ref" in result.output
        assert not route.called

    def test_a_missing_file_is_rejected_by_the_option(self) -> None:
        result = runner.invoke(app, ["chat", "-m", "openai:gpt-5", "--schema", "nope.json", "hi"])

        assert result.exit_code == 2
        assert "nope.json" in result.output

    @respx.mock
    def test_an_xmagic_agent_refuses_it_without_a_request(self, schema_file: Path) -> None:
        route = respx.post(XMAGIC_CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )

        result = runner.invoke(app, ["chat", "--agent", AGENT, "--schema", str(schema_file), "hi"])

        assert result.exit_code == 1
        assert "openai:" in result.stderr
        assert not route.called
