"""``examples/09_worklist_outputs_to_drive.py``, driven end to end over respx.

The example is a script, but its work is in functions, so the flow it
documents -- page through completed tasks, ask the run message for presigned
URLs, download, upload into Drive -- is pinned here rather than trusted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import respx
from httpx import Request, Response

from xmagic import XMagicClient
from xmagic.config import DEFAULT_BASE_URL

AGENT = "agent-1"
FOLDER = "kb-1"
WORKLIST_URL = f"{DEFAULT_BASE_URL}/agents/{AGENT}/worklist"
SIGNED = "https://bucket.s3.example/assets/org/report%20final.pdf?X-Amz-Signature=abc"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "examples" / "09_worklist_outputs_to_drive.py"
    spec = importlib.util.spec_from_file_location("worklist_outputs_example", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered first: a dataclass with postponed annotations resolves them
    # through sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _task(task_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": task_id,
        "name": f"task {task_id}",
        "detailed_description": "d",
        "status": "completed",
        "run_chat_id": None,
        "run_message_ids": [],
        "output_s3_file_paths": [],
    }
    return {**base, **overrides}


def _mock_backend() -> dict[str, Any]:
    """Three completed tasks over two pages; one has a downloadable output."""
    with_output = _task("t1", run_chat_id="chat-1", run_message_ids=["m1"])
    no_message = _task("t2", output_s3_file_paths=["s3://bucket/assets/orphan.html"])
    no_outputs = _task("t3", run_chat_id="chat-3", run_message_ids=["m3"])

    def page(request: Request) -> Response:
        skip = int(request.url.params["skip"])
        tasks = [with_output, no_message][skip:] if skip < 2 else [no_outputs]
        return Response(200, json={"data": {"tasks": tasks, "total": 3, "skip": skip, "limit": 2}})

    respx.get(WORKLIST_URL).mock(side_effect=page)
    respx.get(f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats/chat-1/message/m1").mock(
        return_value=Response(
            200, json={"data": {"id": "m1", "downloadable_output": {"report": SIGNED}}}
        )
    )
    respx.get(f"{DEFAULT_BASE_URL}/agents/{AGENT}/chats/chat-3/message/m3").mock(
        return_value=Response(200, json={"data": {"id": "m3", "downloadable_output": {}}})
    )
    signed = respx.get("https://bucket.s3.example/assets/org/report%20final.pdf").mock(
        return_value=Response(200, content=b"%PDF-1.7 fake")
    )
    upload = respx.post(f"{DEFAULT_BASE_URL}/uploaded-files").mock(
        return_value=Response(200, json={"data": "file-9"})
    )
    attach = respx.post(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}/data-sources/documents").mock(
        return_value=Response(
            200,
            json={
                "data": {"id": "doc-9", "title": "t1-report final.pdf", "knowledge_base_id": FOLDER}
            },
        )
    )
    return {"signed": signed, "upload": upload, "attach": attach}


@respx.mock
def test_files_every_downloadable_output_and_reports_the_rest(
    example: ModuleType, tmp_path: Path
) -> None:
    routes = _mock_backend()
    log: list[str] = []

    with XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        filed = example.file_outputs(client, AGENT, FOLDER, tmp_path, log=log.append)

    assert [(f.task_id, f.key, f.local.name, f.file.id) for f in filed] == [
        ("t1", "report", "t1-report final.pdf", "doc-9")
    ]
    assert filed[0].local.read_bytes() == b"%PDF-1.7 fake"
    # The presigned URL is fetched as-is, with its signature and without the API key.
    signed_request = routes["signed"].calls.last.request
    assert signed_request.url.params["X-Amz-Signature"] == "abc"
    assert "x-api-key" not in signed_request.headers
    attach_body = json.loads(routes["attach"].calls.last.request.read())
    assert attach_body["data_source_title"] == "t1-report final.pdf"
    assert any("t2" in line and "no download URL exposed" in line for line in log)
    assert not any("t3" in line for line in log)


@respx.mock
def test_pages_through_every_completed_task(example: ModuleType) -> None:
    _mock_backend()
    with XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        ids = [t.id for t in example.completed_tasks(client, AGENT, page_size=2)]
    assert ids == ["t1", "t2", "t3"]


@respx.mock
def test_single_task_mode_skips_the_listing(example: ModuleType, tmp_path: Path) -> None:
    routes = _mock_backend()
    listing = respx.get(WORKLIST_URL)
    respx.get(f"{WORKLIST_URL}/t1").mock(
        return_value=Response(
            200, json={"data": _task("t1", run_chat_id="chat-1", run_message_ids=["m1"])}
        )
    )
    with XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        filed = example.file_outputs(
            client, AGENT, FOLDER, tmp_path, task_id="t1", log=lambda s: None
        )

    assert [f.task_id for f in filed] == ["t1"]
    assert not listing.called
    assert routes["upload"].call_count == 1


def test_filename_comes_from_the_url_or_the_key(example: ModuleType) -> None:
    assert example.filename_for(SIGNED, "report") == "report final.pdf"
    assert example.filename_for("https://h/?sig=1", "report") == "report"
