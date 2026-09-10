"""``--json``: one document on stdout, nothing else, errors on stderr.

Every test here parses ``result.stdout`` rather than searching ``result.output``
for a substring, because that is the contract: a script pipes stdout into a
JSON parser and never sees stderr. A command that printed a table footnote or a
progress line on stdout under ``--json`` would pass a substring test and break
``jq``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx

from httpx import Response
from typer.testing import CliRunner, Result

import xmagic
from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL

AGENT = "agent-1"
CHATS_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats"
QUERY_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats/chat-1/query"
UPLOAD_URL = f"{DEFAULT_BASE_URL}/uploaded-files"
KB_URL = f"{DEFAULT_BASE_URL}/knowledge-bases"
WORKSPACES_URL = f"{DEFAULT_BASE_URL}/users/workspaces"
AGENTS_URL = f"{DEFAULT_BASE_URL}/agents"
WORKLIST_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/worklist"

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))


def _sse(*frames: str) -> Response:
    body = "\n\n".join(f"data: {f}" for f in frames) + "\n\n"
    return Response(200, text=body, headers={"content-type": "text/event-stream"})


def _task(status: str = "pending") -> dict[str, object]:
    return {
        "id": "task-1",
        "persona_id": AGENT,
        "name": "Generate report",
        "detailed_description": "Generate the weekly report.",
        "input_s3_file_paths": [],
        "run_chat_id": None,
        "run_message_ids": [],
        "status": status,
        "output_s3_file_paths": [],
        "is_scheduled": False,
        "is_archived": False,
        "created_at": "2026-08-01T10:00:00Z",
    }


def _only_json(result: Result) -> Any:
    """stdout must be exactly one JSON document. Anything else is a defect."""
    return json.loads(result.stdout)


class TestChat:
    @respx.mock
    def test_streamed_answer_is_emitted_once_after_it_completes(self) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(
            return_value=_sse(
                '{"type": "reasoning", "text": "thinking"}',
                '{"type": "response", "text": "hel"}',
                '{"type": "response", "text": "lo"}',
                "[DONE]",
            )
        )

        result = runner.invoke(app, ["chat", "--agent", AGENT, "--json", "hi"])

        assert result.exit_code == 0, result.output
        assert _only_json(result) == {
            "model": f"xmagic:{AGENT}",
            "text": "hello",
            "reasoning": "thinking",
            "usage": None,
        }

    @respx.mock
    def test_no_stream_path_emits_the_same_shape(self) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(
            return_value=Response(200, json={"data": {"message_id": "m1", "text": "hello"}})
        )

        result = runner.invoke(app, ["chat", "--agent", AGENT, "--json", "--no-stream", "hi"])

        assert result.exit_code == 0, result.output
        assert _only_json(result)["text"] == "hello"

    @respx.mock
    def test_upload_progress_goes_to_stderr_not_stdout(self, tmp_path: Path) -> None:
        doc = tmp_path / "notes.md"
        doc.write_text("notes")
        respx.post(UPLOAD_URL).mock(return_value=Response(200, json={"data": "file-1"}))
        respx.post(CHATS_URL).mock(
            return_value=Response(200, json={"data": {"chat": {"id": "chat-1"}}})
        )
        respx.post(QUERY_URL).mock(
            return_value=_sse('{"type": "response", "text": "ok"}', "[DONE]")
        )

        result = runner.invoke(app, ["chat", "--agent", AGENT, "--json", "-f", str(doc), "hi"])

        assert result.exit_code == 0, result.output
        assert _only_json(result)["text"] == "ok"
        assert "uploaded notes.md" in result.stderr

    def test_interactive_mode_is_refused(self) -> None:
        result = runner.invoke(app, ["chat", "--agent", AGENT, "--json"])

        assert result.exit_code != 0
        assert "one-shot prompt" in result.output

    @respx.mock
    def test_an_api_error_leaves_stdout_empty(self) -> None:
        respx.post(CHATS_URL).mock(
            return_value=Response(401, json={"error": {"message": "bad key"}})
        )

        result = runner.invoke(app, ["chat", "--agent", AGENT, "--json", "hi"])

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "bad key" in result.stderr


class TestListings:
    @respx.mock
    def test_workspaces(self) -> None:
        respx.get(WORKSPACES_URL).mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "current_workspace_id": "w1",
                        "workspaces": [{"id": "w1", "name": "Alpha", "role": "admin"}],
                    }
                },
            )
        )

        result = runner.invoke(app, ["workspaces", "--json"])

        assert result.exit_code == 0, result.output
        data = _only_json(result)
        assert data["current_workspace_id"] == "w1"
        assert data["workspaces"][0]["name"] == "Alpha"

    @respx.mock
    def test_workspace_switch(self) -> None:
        respx.get(WORKSPACES_URL).mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "current_workspace_id": "w1",
                        "workspaces": [{"id": "w2", "name": "Beta"}],
                    }
                },
            )
        )
        respx.post(f"{WORKSPACES_URL}/switch").mock(
            return_value=Response(200, json={"data": {"current_workspace_id": "w2"}})
        )

        result = runner.invoke(app, ["workspaces", "--id", "w2", "--json"])

        assert result.exit_code == 0, result.output
        assert _only_json(result)["current_workspace_id"] == "w2"

    @respx.mock
    def test_agents(self) -> None:
        respx.get(AGENTS_URL).mock(
            return_value=Response(
                200, json={"data": [{"id": AGENT, "name": "Sales", "role": "owner"}]}
            )
        )

        result = runner.invoke(app, ["agents", "--json"])

        assert result.exit_code == 0, result.output
        assert _only_json(result) == [{"id": AGENT, "name": "Sales", "role": "owner"}]

    @respx.mock
    def test_drive_ls_and_upload(self, tmp_path: Path) -> None:
        respx.get(KB_URL).mock(
            return_value=Response(
                200, json={"data": {"results": [{"id": "kb-1", "name": "Docs", "type": "folder"}]}}
            )
        )
        respx.post(UPLOAD_URL).mock(return_value=Response(200, json={"data": "file-1"}))
        respx.post(f"{KB_URL}/kb-1/data-sources/documents").mock(
            return_value=Response(
                200,
                json={"data": {"id": "doc-1", "title": "notes.md", "knowledge_base_id": "kb-1"}},
            )
        )
        doc = tmp_path / "notes.md"
        doc.write_text("notes")

        listed = runner.invoke(app, ["drive", "ls", "--json"])
        uploaded = runner.invoke(app, ["drive", "upload", "kb-1", str(doc), "--json"])

        assert listed.exit_code == 0, listed.output
        assert _only_json(listed)[0]["id"] == "kb-1"
        assert uploaded.exit_code == 0, uploaded.output
        assert _only_json(uploaded)["id"] == "doc-1"

    def test_skills_validate(self, tmp_path: Path) -> None:
        skill = tmp_path / "my-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: my-skill\ndescription: Does things.\n---\n")

        result = runner.invoke(app, ["skills", "validate", str(skill), "--json"])

        assert result.exit_code == 0, result.output
        assert _only_json(result) == {
            "path": str(skill),
            "name": "my-skill",
            "description": "Does things.",
        }

    def test_version(self) -> None:
        result = runner.invoke(app, ["version", "--json"])

        assert result.exit_code == 0, result.output
        assert _only_json(result) == {"version": xmagic.__version__}


class TestWorklistMutations:
    @pytest.mark.parametrize(
        ("verb", "route"),
        [("trigger", "trigger"), ("rerun", "rerun"), ("cancel", "stop")],
    )
    @respx.mock
    def test_a_task_mutation_returns_the_task(self, verb: str, route: str) -> None:
        respx.post(f"{WORKLIST_URL}/task-1/{route}").mock(
            return_value=Response(200, json={"data": _task("in_progress")})
        )

        result = runner.invoke(app, ["worklists", verb, "task-1", "--agent", AGENT, "--json"])

        assert result.exit_code == 0, result.output
        data = _only_json(result)
        assert data["id"] == "task-1"
        assert data["status"] == "in_progress"

    @respx.mock
    def test_delete_reports_what_it_deleted(self) -> None:
        respx.delete(f"{WORKLIST_URL}/task-1").mock(
            return_value=Response(200, json={"data": {"deleted": True}})
        )

        result = runner.invoke(
            app, ["worklists", "delete", "task-1", "--agent", AGENT, "--yes", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert _only_json(result) == {"deleted": "task-1"}

    @respx.mock
    def test_an_api_error_keeps_stdout_empty_and_the_hint_on_stderr(self) -> None:
        respx.post(f"{WORKLIST_URL}/task-1/trigger").mock(
            return_value=Response(
                400,
                json={
                    "error": {
                        "error_code": "WORKLIST_TASK_NEEDS_REVIEW",
                        "message": "task needs review",
                    }
                },
            )
        )

        result = runner.invoke(app, ["worklists", "trigger", "task-1", "--agent", AGENT, "--json"])

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "task needs review" in result.stderr
        assert "Hint:" in result.stderr

    @pytest.mark.parametrize("verb", ["pause", "resume"])
    @respx.mock
    def test_a_schedule_mutation_returns_the_schedule(self, verb: str) -> None:
        respx.post(f"{WORKLIST_URL}/schedules/schedule-1/{verb}").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "id": "schedule-1",
                        "persona_id": AGENT,
                        "name": "Daily report",
                        "detailed_description": "Generate a daily report.",
                        "input_s3_file_paths": [],
                        "recurrence": {
                            "frequency": "daily",
                            "interval": 1,
                            "time_of_day": "09:00",
                            "timezone": "UTC",
                        },
                        "status": "paused" if verb == "pause" else "active",
                    }
                },
            )
        )

        result = runner.invoke(
            app, ["worklists", "schedules", verb, "schedule-1", "--agent", AGENT, "--json"]
        )

        assert result.exit_code == 0, result.output
        assert _only_json(result)["id"] == "schedule-1"


class TestExistingFlagsWriteTheSameWay:
    """The commands that already had --json now go through the same writer."""

    def test_models_providers_is_plain_json_on_stdout(self) -> None:
        pytest.importorskip("litellm")

        result = runner.invoke(app, ["models", "providers", "--json"])

        assert result.exit_code == 0, result.output
        data = _only_json(result)
        assert isinstance(data, list) and data and "provider" in data[0]
