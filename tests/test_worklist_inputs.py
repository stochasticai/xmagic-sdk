"""Worklist inputs from local files.

The API takes ``input_s3_file_paths`` only, and the one place the platform
reveals an upload's storage path is the Drive attach response. So a local file
becomes an input by being uploaded into a Drive folder, and the tests here pin
that route end to end: the client helper, the YAML key, and the CLI flags.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Request, Response
from typer.testing import CliRunner

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL
from xmagic.errors import ResponseShapeError
from xmagic.worklist_codec import (
    CREATE_TEMPLATE,
    prefill_input_files,
    task_to_edit_yaml,
    yaml_to_create_payload,
    yaml_to_update_payload,
)

AGENT = "agent-1"
FOLDER = "kb-inputs"
KB_URL = f"{DEFAULT_BASE_URL}/knowledge-bases"
UPLOAD_URL = f"{DEFAULT_BASE_URL}/uploaded-files"
WORKLIST_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/worklist"
S3 = "s3://bucket/attachments/org/{}"

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))


def _mock_upload_and_attach(folder: str = FOLDER) -> None:
    """Uploads get sequential ids; attaching one answers with its storage path."""
    counter = {"n": 0}

    def upload(request: Request) -> Response:
        counter["n"] += 1
        return Response(200, json={"data": f"file-{counter['n']}"})

    def attach(request: Request) -> Response:
        body = json.loads(request.read())
        return Response(
            200,
            json={
                "data": {
                    "id": f"doc-{body['file_id']}",
                    "title": body["data_source_title"],
                    "knowledge_base_id": folder,
                    "value": S3.format(body["data_source_title"]),
                }
            },
        )

    respx.post(UPLOAD_URL).mock(side_effect=upload)
    respx.post(f"{KB_URL}/{folder}/data-sources/documents").mock(side_effect=attach)


def _task(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "task-1",
        "persona_id": AGENT,
        "name": "Report",
        "detailed_description": "Do work",
        "input_s3_file_paths": ["s3://bucket/existing.txt"],
        "status": "pending",
        "is_scheduled": False,
    }
    return {**base, **overrides}


def _files(tmp_path: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_text(f"content of {name}")
        paths.append(p)
    return paths


# -- client -----------------------------------------------------------------------------------


@respx.mock
def test_upload_inputs_returns_storage_paths_in_order(tmp_path: Path) -> None:
    _mock_upload_and_attach()
    a, b = _files(tmp_path, "a.txt", "b.txt")

    with XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        paths = client.worklists.upload_inputs(FOLDER, [a, str(b)])

    assert paths == [S3.format("a.txt"), S3.format("b.txt")]


@respx.mock
def test_upload_inputs_refuses_an_attach_response_without_a_path(tmp_path: Path) -> None:
    respx.post(UPLOAD_URL).mock(return_value=Response(200, json={"data": "file-1"}))
    respx.post(f"{KB_URL}/{FOLDER}/data-sources/documents").mock(
        return_value=Response(200, json={"data": {"id": "doc-1", "title": "a.txt"}})
    )
    (a,) = _files(tmp_path, "a.txt")

    with XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        with pytest.raises(ResponseShapeError, match="no storage path"):
            client.worklists.upload_inputs(FOLDER, [a])


@respx.mock
async def test_async_upload_inputs_mirrors_sync(tmp_path: Path) -> None:
    _mock_upload_and_attach()
    (a,) = _files(tmp_path, "a.txt")

    async with AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        assert await client.worklists.upload_inputs(FOLDER, [a]) == [S3.format("a.txt")]


# -- codec ------------------------------------------------------------------------------------


def test_create_yaml_keeps_input_files_only_when_given() -> None:
    with_files = yaml_to_create_payload(
        "name: t\ndetailed_description: d\ninput_files: [a.txt, b.txt]\n"
    )
    without = yaml_to_create_payload("name: t\ndetailed_description: d\ninput_files: []\n")

    assert with_files["input_files"] == ["a.txt", "b.txt"]
    assert "input_files" not in without
    with pytest.raises(ValueError, match="input_files must be a list"):
        yaml_to_create_payload("name: t\ndetailed_description: d\ninput_files: a.txt\n")


def test_update_yaml_reports_input_files_as_a_change() -> None:
    original = _task()
    edited = task_to_edit_yaml(original).replace("input_files: []", "input_files:\n- new.txt")

    assert yaml_to_update_payload(edited, original) == {"input_files": ["new.txt"]}
    assert yaml_to_update_payload(task_to_edit_yaml(original), original) == {}


def test_prefill_renders_paths_into_the_template() -> None:
    text = prefill_input_files(CREATE_TEMPLATE, ["/tmp/a.txt", "/tmp/b.txt"])

    assert "input_files:\n- /tmp/a.txt\n- /tmp/b.txt" in text
    assert prefill_input_files(CREATE_TEMPLATE, []) == CREATE_TEMPLATE
    with pytest.raises(ValueError, match="no input_files line"):
        prefill_input_files("name: x\n", ["a"])


# -- CLI --------------------------------------------------------------------------------------


def _editor_that_fills_in(monkeypatch: pytest.MonkeyPatch, **fields: str) -> list[str]:
    """An editor that sets name and description and leaves the rest of the file alone."""
    seen: list[str] = []

    def edit_file(path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        seen.append(text)
        for key, value in fields.items():
            text = text.replace(f'{key}: ""', f"{key}: {value}")
        path.write_text(text, encoding="utf-8")

    monkeypatch.setattr("xmagic.cli.worklists._edit_file", edit_file)
    return seen


@respx.mock
def test_create_with_input_uploads_into_the_named_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_upload_and_attach()
    create = respx.post(WORKLIST_URL).mock(return_value=Response(200, json={"data": _task()}))
    seen = _editor_that_fills_in(monkeypatch, name="T", detailed_description="D")
    a, b = _files(tmp_path, "a.txt", "b.txt")

    result = runner.invoke(
        app,
        ["worklists", "create", "--agent", AGENT, "-i", str(a), "-i", str(b), "--folder", FOLDER],
    )

    assert result.exit_code == 0, result.output
    assert f"input_files:\n- {a}\n- {b}" in seen[0]  # pre-filled for the editor
    sent = json.loads(create.calls.last.request.read())
    assert sent["input_s3_file_paths"] == [S3.format("a.txt"), S3.format("b.txt")]
    assert "input_files" not in sent
    assert "Uploaded a.txt" in result.output


@respx.mock
def test_create_without_folder_finds_or_creates_worklist_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_upload_and_attach(folder="kb-new")
    respx.post(WORKLIST_URL).mock(return_value=Response(200, json={"data": _task()}))
    listing = respx.get(KB_URL).mock(return_value=Response(200, json={"data": {"results": []}}))
    created = respx.post(KB_URL).mock(
        return_value=Response(200, json={"data": {"id": "kb-new", "name": "worklist-inputs"}})
    )
    _editor_that_fills_in(monkeypatch, name="T", detailed_description="D")
    (a,) = _files(tmp_path, "a.txt")

    first = runner.invoke(app, ["worklists", "create", "--agent", AGENT, "-i", str(a)])
    assert first.exit_code == 0, first.output
    assert json.loads(created.calls.last.request.read())["knowledge_base_name"] == "worklist-inputs"
    assert "Created Drive folder worklist-inputs" in first.output

    listing.mock(
        return_value=Response(
            200, json={"data": {"results": [{"id": "kb-new", "name": "worklist-inputs"}]}}
        )
    )
    second = runner.invoke(app, ["worklists", "create", "--agent", AGENT, "-i", str(a)])
    assert second.exit_code == 0, second.output
    assert created.call_count == 1  # found this time, not created again


@respx.mock
def test_create_from_yaml_input_files_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_upload_and_attach()
    create = respx.post(WORKLIST_URL).mock(return_value=Response(200, json={"data": _task()}))
    (a,) = _files(tmp_path, "a.txt")

    def edit_file(path: Path) -> None:
        path.write_text(
            f"name: T\ndetailed_description: D\ninput_s3_file_paths: [s3://bucket/keep.txt]\n"
            f"input_files: [{a}]\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("xmagic.cli.worklists._edit_file", edit_file)

    result = runner.invoke(app, ["worklists", "create", "--agent", AGENT, "--folder", FOLDER])

    assert result.exit_code == 0, result.output
    sent = json.loads(create.calls.last.request.read())
    assert sent["input_s3_file_paths"] == ["s3://bucket/keep.txt", S3.format("a.txt")]


@respx.mock
def test_edit_with_input_appends_to_the_existing_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_upload_and_attach()
    respx.get(f"{WORKLIST_URL}/task-1").mock(return_value=Response(200, json={"data": _task()}))
    patched = respx.patch(f"{WORKLIST_URL}/task-1").mock(
        return_value=Response(200, json={"data": _task()})
    )
    monkeypatch.setattr("xmagic.cli.worklists._edit_file", lambda path: None)
    (a,) = _files(tmp_path, "a.txt")

    result = runner.invoke(
        app, ["worklists", "edit", "task-1", "--agent", AGENT, "-i", str(a), "--folder", FOLDER]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(patched.calls.last.request.read()) == {
        "input_s3_file_paths": ["s3://bucket/existing.txt", S3.format("a.txt")]
    }


@respx.mock
def test_missing_input_file_fails_before_any_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    create = respx.post(WORKLIST_URL).mock(return_value=Response(200, json={"data": _task()}))
    upload = respx.post(UPLOAD_URL).mock(return_value=Response(200, json={"data": "file-1"}))

    def edit_file(path: Path) -> None:
        path.write_text(
            f"name: T\ndetailed_description: D\ninput_files: [{tmp_path / 'gone.txt'}]\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("xmagic.cli.worklists._edit_file", edit_file)

    result = runner.invoke(app, ["worklists", "create", "--agent", AGENT, "--folder", FOLDER])

    assert result.exit_code == 1
    assert "input file not found" in result.output
    assert not upload.called and not create.called
