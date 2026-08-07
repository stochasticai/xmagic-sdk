"""``xmagic chat`` behavior: file attachments, chat type, reasoning, session reuse."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL

AGENT = "agent-1"
CHATS_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats"
QUERY_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats/chat-1/query"
UPLOAD_URL = f"{DEFAULT_BASE_URL}/uploaded-files"

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate from the developer's real key and config file."""
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))


def _create_chat_route() -> respx.Route:
    return respx.post(CHATS_URL).mock(
        return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
    )


def _sse(*frames: str) -> Response:
    body = "\n\n".join(f"data: {f}" for f in frames) + "\n\n"
    return Response(200, text=body, headers={"content-type": "text/event-stream"})


@respx.mock
def test_chat_one_shot_streams_response() -> None:
    _create_chat_route()
    respx.post(QUERY_URL).mock(return_value=_sse('{"type": "response", "text": "hello"}', "[DONE]"))

    result = runner.invoke(app, ["chat", "--agent", AGENT, "hi"])

    assert result.exit_code == 0, result.output
    assert "hello" in result.output


@respx.mock
def test_chat_type_flag_reaches_the_create_payload() -> None:
    create = _create_chat_route()
    respx.post(QUERY_URL).mock(return_value=_sse("[DONE]"))

    result = runner.invoke(app, ["chat", "--agent", AGENT, "--chat-type", "playground", "hi"])

    assert result.exit_code == 0, result.output
    assert '"chat_type":"playground"' in create.calls.last.request.read().decode()


@respx.mock
def test_chat_type_defaults_to_standard() -> None:
    create = _create_chat_route()
    respx.post(QUERY_URL).mock(return_value=_sse("[DONE]"))

    runner.invoke(app, ["chat", "--agent", AGENT, "hi"])

    assert '"chat_type":"standard"' in create.calls.last.request.read().decode()


@respx.mock
def test_file_flag_uploads_and_references_the_id(tmp_path: Path) -> None:
    doc = tmp_path / "notes.md"
    doc.write_text("some notes")

    _create_chat_route()
    upload = respx.post(UPLOAD_URL).mock(
        return_value=Response(200, json={"data": "uploaded-file-1"})
    )
    query = respx.post(QUERY_URL).mock(return_value=_sse("[DONE]"))

    result = runner.invoke(app, ["chat", "--agent", AGENT, "-f", str(doc), "summarize"])

    assert result.exit_code == 0, result.output
    assert upload.called
    assert '"uploaded_files":["uploaded-file-1"]' in query.calls.last.request.read().decode()


@respx.mock
def test_multiple_files_are_all_referenced(tmp_path: Path) -> None:
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("a")
    second.write_text("b")

    _create_chat_route()
    respx.post(UPLOAD_URL).mock(
        side_effect=[
            Response(200, json={"data": "file-a"}),
            Response(200, json={"data": "file-b"}),
        ]
    )
    query = respx.post(QUERY_URL).mock(return_value=_sse("[DONE]"))

    result = runner.invoke(
        app, ["chat", "--agent", AGENT, "-f", str(first), "-f", str(second), "compare"]
    )

    assert result.exit_code == 0, result.output
    assert '"uploaded_files":["file-a","file-b"]' in query.calls.last.request.read().decode()


def test_file_flag_rejected_for_non_xmagic_provider(tmp_path: Path) -> None:
    doc = tmp_path / "notes.md"
    doc.write_text("x")

    result = runner.invoke(app, ["chat", "-m", "openai:gpt-4o", "-f", str(doc), "hi"])

    assert result.exit_code != 0
    assert "only supported for xMagic agents" in result.output


@respx.mock
def test_missing_file_is_rejected_before_any_request() -> None:
    """Typer's exists=True catches this, so no chat is created and nothing uploads."""
    create = _create_chat_route()
    upload = respx.post(UPLOAD_URL).mock(return_value=Response(200, json={"data": "x"}))

    result = runner.invoke(app, ["chat", "--agent", AGENT, "-f", "/nonexistent/nope.txt", "hi"])

    assert result.exit_code == 2  # usage error
    assert not create.called
    assert not upload.called


@respx.mock
def test_reasoning_is_rendered_before_the_answer() -> None:
    _create_chat_route()
    respx.post(QUERY_URL).mock(
        return_value=_sse(
            '{"type": "reasoning", "text": "thinking..."}',
            '{"type": "response", "text": "the answer"}',
            "[DONE]",
        )
    )

    result = runner.invoke(app, ["chat", "--agent", AGENT, "hi"])

    assert result.exit_code == 0, result.output
    # Both are shown, reasoning first. (Dimming is an ANSI style the test runner
    # strips; ordering and presence are what matter here.)
    assert result.output.index("thinking...") < result.output.index("the answer")


@respx.mock
def test_interactive_session_reuses_one_chat() -> None:
    create = _create_chat_route()
    query = respx.post(QUERY_URL).mock(return_value=_sse("[DONE]"))

    result = runner.invoke(app, ["chat", "--agent", AGENT], input="first\nsecond\n")

    assert result.exit_code == 0, result.output
    # Two turns, but the chat is created once and both queries land in it.
    assert create.call_count == 1
    assert query.call_count == 2


@respx.mock
def test_no_stream_uses_blocking_query() -> None:
    _create_chat_route()
    query = respx.post(QUERY_URL).mock(
        return_value=Response(200, json={"data": {"text": "blocking answer"}})
    )

    result = runner.invoke(app, ["chat", "--agent", AGENT, "--no-stream", "hi"])

    assert result.exit_code == 0, result.output
    assert "blocking answer" in result.output
    assert '"is_stream":false' in query.calls.last.request.read().decode()


def test_error_text_is_not_swallowed_as_rich_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bracketed content in an error must survive to the terminal.

    Rich reads `[providers.openai]` as a style tag and drops it, which turned
    "add [providers.openai] api_key to ..." into "add  api_key to ..." -- advice
    pointing at nothing. Errors are data; they get escaped.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_API_KEY", "xm-test")
    result = CliRunner().invoke(app, ["chat", "-m", "openai:gpt-5", "hi"])

    assert result.exit_code == 1
    assert "[providers.openai]" in result.output
