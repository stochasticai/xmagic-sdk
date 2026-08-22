"""Worklist API, YAML codec, and CLI behavior tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL
from xmagic.client.models import WorklistReviewAction
from xmagic.worklist_codec import (
    CREATE_TEMPLATE,
    schedule_to_edit_yaml,
    yaml_to_create_payload,
    yaml_to_schedule_update_payload,
    yaml_to_update_payload,
)

AGENT_ID = "agent-1"
TASK_ID = "task-1"
SCHEDULE_ID = "schedule-1"
WORKLIST_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT_ID}/worklist"
runner = CliRunner()


def _task_payload(
    task_id: str = TASK_ID,
    *,
    status: str = "pending",
    run_message_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "persona_id": AGENT_ID,
        "name": "Generate report",
        "detailed_description": "Generate the weekly report.",
        "input_s3_file_paths": ["s3://bucket/input.txt"],
        "run_chat_id": "chat-1" if run_message_ids else None,
        "run_message_ids": run_message_ids or [],
        "status": status,
        "output_s3_file_paths": ["s3://bucket/output.txt"] if run_message_ids else [],
        "is_scheduled": False,
        "is_archived": False,
        "created_at": "2026-08-01T10:00:00Z",
    }


def _schedule_payload() -> dict[str, Any]:
    return {
        "id": SCHEDULE_ID,
        "persona_id": AGENT_ID,
        "name": "Daily report",
        "detailed_description": "Generate a daily report.",
        "input_s3_file_paths": ["s3://bucket/input.txt"],
        "recurrence": {
            "frequency": "daily",
            "interval": 1,
            "time_of_day": "09:00",
            "timezone": "UTC",
        },
        "status": "active",
        "total_runs": 2,
    }


@pytest.fixture(autouse=True)
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "missing.toml"))


@respx.mock
def test_worklist_list_uses_explicit_pagination_and_filters() -> None:
    route = respx.get(WORKLIST_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "tasks": [_task_payload()],
                    "total": 3,
                    "skip": 10,
                    "limit": 5,
                }
            },
        )
    )

    with XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        page = client.worklists.list(
            AGENT_ID,
            status="pending",
            is_archived=False,
            is_recurring=True,
            creation_chat_id="chat-created",
            skip=10,
            limit=5,
        )

    params = route.calls.last.request.url.params
    assert params["status"] == "pending"
    assert params["is_archived"] == "false"
    assert params["is_recurring"] == "true"
    assert params["creation_chat_id"] == "chat-created"
    assert params["skip"] == "10"
    assert params["limit"] == "5"
    assert page.tasks[0].id == TASK_ID
    assert page.total == 3


@respx.mock
def test_worklist_task_and_schedule_operations_use_backend_routes() -> None:
    task_response = {"data": _task_payload()}
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(return_value=Response(200, json=task_response))
    create_route = respx.post(WORKLIST_URL).mock(return_value=Response(200, json=task_response))
    update_route = respx.patch(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json=task_response)
    )
    delete_route = respx.delete(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": {"deleted": True}})
    )
    trigger_route = respx.post(f"{WORKLIST_URL}/{TASK_ID}/trigger").mock(
        return_value=Response(200, json=task_response)
    )
    rerun_route = respx.post(f"{WORKLIST_URL}/{TASK_ID}/rerun").mock(
        return_value=Response(200, json=task_response)
    )
    stop_route = respx.post(f"{WORKLIST_URL}/{TASK_ID}/stop").mock(
        return_value=Response(200, json=task_response)
    )

    schedule_response = {"data": _schedule_payload()}
    schedule_url = f"{WORKLIST_URL}/schedules/{SCHEDULE_ID}"
    respx.get(schedule_url).mock(return_value=Response(200, json=schedule_response))
    schedule_update_route = respx.patch(schedule_url).mock(
        return_value=Response(200, json=schedule_response)
    )
    schedule_delete_route = respx.delete(schedule_url).mock(
        return_value=Response(200, json={"data": {"deleted": True}})
    )
    pause_route = respx.post(f"{schedule_url}/pause").mock(
        return_value=Response(200, json=schedule_response)
    )
    resume_route = respx.post(f"{schedule_url}/resume").mock(
        return_value=Response(200, json=schedule_response)
    )

    with XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        assert client.worklists.get(AGENT_ID, TASK_ID).id == TASK_ID
        client.worklists.create(AGENT_ID, {"name": "A", "scheduled_at": "2026-08-01T10:00:00Z"})
        client.worklists.update(AGENT_ID, TASK_ID, {"status": "needs_review"})
        assert client.worklists.delete(AGENT_ID, TASK_ID) == {"deleted": True}
        assert client.worklists.trigger(AGENT_ID, TASK_ID).id == TASK_ID
        assert client.worklists.rerun(AGENT_ID, TASK_ID).id == TASK_ID
        assert client.worklists.stop(AGENT_ID, TASK_ID).id == TASK_ID
        assert client.worklists.get_schedule(AGENT_ID, SCHEDULE_ID).id == SCHEDULE_ID
        client.worklists.update_schedule(AGENT_ID, SCHEDULE_ID, {"name": "Updated"})
        assert client.worklists.delete_schedule(AGENT_ID, SCHEDULE_ID) == {"deleted": True}
        assert client.worklists.pause_schedule(AGENT_ID, SCHEDULE_ID).id == SCHEDULE_ID
        assert client.worklists.resume_schedule(AGENT_ID, SCHEDULE_ID).id == SCHEDULE_ID

    assert json.loads(create_route.calls.last.request.read())["name"] == "A"
    assert json.loads(update_route.calls.last.request.read()) == {"status": "needs_review"}
    assert json.loads(schedule_update_route.calls.last.request.read()) == {"name": "Updated"}
    assert all(
        route.called
        for route in [
            create_route,
            update_route,
            delete_route,
            trigger_route,
            rerun_route,
            stop_route,
            schedule_update_route,
            schedule_delete_route,
            pause_route,
            resume_route,
        ]
    )


@respx.mock
def test_worklist_get_can_fetch_latest_message_download_urls() -> None:
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(run_message_ids=["msg-1"])})
    )
    message_route = respx.get(
        f"{DEFAULT_BASE_URL}/agents/{AGENT_ID}/chats/chat-1/message/msg-1"
    ).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "id": "msg-1",
                    "response": "Report complete",
                    "downloadable_output": {"output-1": "https://signed.example/output"},
                }
            },
        )
    )

    result = runner.invoke(app, ["worklists", "get", TASK_ID, "--agent", AGENT_ID])

    assert result.exit_code == 0, result.output
    assert "Report complete" in result.output
    assert "https://signed.example/output" in result.output
    assert message_route.calls.last.request.url.params["downloadable_output"] == "true"


@respx.mock
def test_cli_review_completes_specific_task_with_blank_message() -> None:
    task = _task_payload(status="needs_review", run_message_ids=["msg-1"])
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(return_value=Response(200, json={"data": task}))
    respx.get(f"{DEFAULT_BASE_URL}/agents/{AGENT_ID}/chats/chat-1/message/msg-1").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "id": "msg-1",
                    "response": "Please approve this report.",
                    "downloadable_output": {},
                }
            },
        )
    )
    patch_route = respx.patch(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="completed")})
    )
    result = runner.invoke(
        app,
        ["worklists", "review", TASK_ID, "--agent", AGENT_ID],
        input="\n",
    )

    assert result.exit_code == 0, result.output
    assert "Please approve this report." in result.output
    assert "Completed worklist task task-1" in result.output
    assert json.loads(patch_route.calls.last.request.read()) == {"status": "completed"}
    assert len(respx.calls) == 3


@respx.mock
def test_cli_review_sends_follow_up_message_without_direct_trigger() -> None:
    task = _task_payload(status="needs_review", run_message_ids=["msg-1"])
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(return_value=Response(200, json={"data": task}))
    respx.get(f"{DEFAULT_BASE_URL}/agents/{AGENT_ID}/chats/chat-1/message/msg-1").mock(
        return_value=Response(
            200,
            json={"data": {"id": "msg-1", "response": "Please approve this report."}},
        )
    )
    query_route = respx.post(f"{DEFAULT_BASE_URL}/agents/{AGENT_ID}/chats/chat-1/query").mock(
        return_value=Response(
            200,
            json={"data": {"message_id": "message-1", "text": "Follow-up started."}},
        )
    )

    result = runner.invoke(
        app,
        ["worklists", "review", TASK_ID, "--agent", AGENT_ID],
        input="Use the revised assumptions.\n",
    )

    assert result.exit_code == 0, result.output
    assert "Sent follow-up message for task-1" in result.output
    payload = json.loads(query_route.calls.last.request.read())
    assert payload["query"] == "Use the revised assumptions."
    assert len(payload["message_id"]) == 24
    int(payload["message_id"], 16)
    assert payload["hidden_query"] == (
        'You have to follow up on the worklist task ID "task-1" '
        'with name "Generate report". Please modify the existing task instead '
        "of creating a new one."
    )
    assert payload["is_stream"] is False
    assert payload["parse_response"] is True
    assert not any(
        call.request.method in {"PATCH", "POST"} and call.request.url.path.startswith(WORKLIST_URL)
        for call in respx.calls
    )


@respx.mock
def test_cli_review_skips_task_with_skip_command() -> None:
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="needs_review")})
    )

    result = runner.invoke(
        app,
        ["worklists", "review", TASK_ID, "--agent", AGENT_ID],
        input="/skip\n",
    )

    assert result.exit_code == 0, result.output
    assert "Skipped worklist task task-1" in result.output
    assert len(respx.calls) == 1


@respx.mock
def test_cli_review_processes_needs_review_tasks_one_by_one() -> None:
    second_task_id = "task-2"
    tasks = [
        _task_payload(status="needs_review"),
        _task_payload(task_id=second_task_id, status="needs_review"),
    ]
    respx.get(WORKLIST_URL).mock(
        return_value=Response(
            200,
            json={"data": {"tasks": tasks, "total": 2, "skip": 0, "limit": 200}},
        )
    )
    result = runner.invoke(
        app,
        ["worklists", "review", "--agent", AGENT_ID],
        input="/skip\n/skip\n",
    )

    assert result.exit_code == 0, result.output
    assert result.output.count("Skipped worklist task") == 2
    assert len(respx.calls) == 1


@respx.mock
def test_cli_review_reports_empty_queue() -> None:
    respx.get(WORKLIST_URL).mock(
        return_value=Response(
            200, json={"data": {"tasks": [], "total": 0, "skip": 0, "limit": 200}}
        )
    )

    result = runner.invoke(app, ["worklists", "review", "--agent", AGENT_ID])

    assert result.exit_code == 0, result.output
    assert "No worklist tasks need review" in result.output


@respx.mock
def test_programmatic_review_completes_needs_review_task() -> None:
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="needs_review")})
    )
    patch_route = respx.patch(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="completed")})
    )

    with XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        result = client.worklists.review(AGENT_ID, TASK_ID)

    assert result.action is WorklistReviewAction.COMPLETED
    assert result.task.status.value == "completed"
    assert json.loads(patch_route.calls.last.request.read()) == {"status": "completed"}
    assert [call.request.method for call in respx.calls] == ["GET", "PATCH"]


@respx.mock
def test_programmatic_review_sends_follow_up_message() -> None:
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(
            200,
            json={"data": _task_payload(status="needs_review", run_message_ids=["msg-1"])},
        )
    )
    query_route = respx.post(f"{DEFAULT_BASE_URL}/agents/{AGENT_ID}/chats/chat-1/query").mock(
        return_value=Response(200, json={"data": {"text": "continued", "message_id": "m2"}})
    )

    with XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        result = client.worklists.review(AGENT_ID, TASK_ID, message="Use revised assumptions")

    assert result.action is WorklistReviewAction.FOLLOW_UP_SENT
    assert result.query is not None
    assert result.query.text == "continued"
    payload = json.loads(query_route.calls.last.request.read())
    assert payload["query"] == "Use revised assumptions"
    assert payload["parse_response"] is True
    assert payload["hidden_query"] == (
        'You have to follow up on the worklist task ID "task-1" '
        'with name "Generate report". Please modify the existing task instead '
        "of creating a new one."
    )


@respx.mock
def test_programmatic_review_rejects_non_review_task_without_mutation() -> None:
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="pending")})
    )

    with XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        with pytest.raises(ValueError, match="not 'needs_review'"):
            client.worklists.review(AGENT_ID, TASK_ID)

    assert len(respx.calls) == 1


@respx.mock
async def test_async_programmatic_review_completes_task() -> None:
    respx.get(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="needs_review")})
    )
    respx.patch(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": _task_payload(status="completed")})
    )

    async with AsyncXMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        result = await client.worklists.review(AGENT_ID, TASK_ID)

    assert result.action is WorklistReviewAction.COMPLETED
    assert result.task.status.value == "completed"


def test_codec_validates_create_and_returns_only_task_changes() -> None:
    payload = yaml_to_create_payload(
        """name: Weekly report
detailed_description: Build the report
input_s3_file_paths:
  - s3://bucket/input.txt
is_scheduled: true
scheduled_at: 2026-08-02T10:00:00Z
status: needs_review
recurrence:
  frequency: weekly
  days_of_week: [0, 2]
  time_of_day: '09:30'
"""
    )

    assert payload["name"] == "Weekly report"
    assert payload["recurrence"]["timezone"] == "UTC"
    original = {"name": "Old", "status": "pending", "input_s3_file_paths": []}
    assert yaml_to_update_payload("name: New\nstatus: pending\n", original) == {"name": "New"}
    assert CREATE_TEMPLATE.startswith("# Worklist task to create.")

    with pytest.raises(ValueError, match="time_of_day"):
        yaml_to_create_payload(
            "name: Daily\ndetailed_description: Report\nrecurrence:\n  frequency: daily\n"
        )


def test_codec_renders_and_validates_schedule_edits() -> None:
    original = _schedule_payload()
    text = schedule_to_edit_yaml(original)
    assert "name: Daily report" in text
    assert "status:" not in text

    edited = yaml_to_schedule_update_payload(
        """name: Morning report
detailed_description: Updated description
input_s3_file_paths: []
recurrence:
  frequency: daily
  time_of_day: '10:00'
  timezone: UTC
""",
        original,
    )
    assert edited["name"] == "Morning report"
    assert edited["input_s3_file_paths"] == []
    assert edited["recurrence"]["time_of_day"] == "10:00"

    with pytest.raises(ValueError, match="unsupported key"):
        yaml_to_schedule_update_payload("status: paused\n", original)


@respx.mock
def test_cli_create_uses_yaml_editor_template(monkeypatch: pytest.MonkeyPatch) -> None:
    def edit_file(path: Path) -> None:
        path.write_text(
            "name: New task\ndetailed_description: Do work\ninput_s3_file_paths: []\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("xmagic.cli.worklists._edit_file", edit_file)
    route = respx.post(WORKLIST_URL).mock(
        return_value=Response(200, json={"data": _task_payload()})
    )

    result = runner.invoke(app, ["worklists", "create", "--agent", AGENT_ID])

    assert result.exit_code == 0, result.output
    assert "Created worklist task" in result.output
    assert json.loads(route.calls.last.request.read())["name"] == "New task"


@respx.mock
def test_cli_schedule_edit_patches_yaml_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    def edit_file(path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("name: Daily report", "name: Morning report"), encoding="utf-8"
        )

    monkeypatch.setattr("xmagic.cli.worklists._edit_file", edit_file)
    schedule_url = f"{WORKLIST_URL}/schedules/{SCHEDULE_ID}"
    respx.get(schedule_url).mock(return_value=Response(200, json={"data": _schedule_payload()}))
    patch_route = respx.patch(schedule_url).mock(
        return_value=Response(200, json={"data": _schedule_payload()})
    )

    result = runner.invoke(
        app, ["worklists", "schedules", "edit", SCHEDULE_ID, "--agent", AGENT_ID]
    )

    assert result.exit_code == 0, result.output
    assert "Updated recurring schedule" in result.output
    assert json.loads(patch_route.calls.last.request.read()) == {"name": "Morning report"}


@respx.mock
def test_cli_delete_can_skip_confirmation() -> None:
    route = respx.delete(f"{WORKLIST_URL}/{TASK_ID}").mock(
        return_value=Response(200, json={"data": {"deleted": True}})
    )

    result = runner.invoke(app, ["worklists", "delete", TASK_ID, "--agent", AGENT_ID, "--yes"])

    assert result.exit_code == 0, result.output
    assert "Deleted worklist task task-1" in result.output
    assert route.called
