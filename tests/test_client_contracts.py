"""Backend contract tests for xmagic client request/response shapes.

The mocked tests below replay *recorded* fixtures captured from a live agent
on 2026-07-31 (see ``tests/fixtures/``, account-identifying ids redacted).
They pin the confirmed request/response shapes so regressions are caught
without needing network access.

Live tests are opt-in and require an API key, resolved with the same
precedence as the SDK itself (explicit env var > .env > ``xmagic configure``'s
``config.toml``), plus a test agent id:

- XMAGIC_API_KEY (environment, .env, or ``~/.config/xmagic/config.toml``)
- XMAGIC_TEST_AGENT_ID (environment or .env; falls back to the config file's
  ``default_agent_id`` if unset)

Run live tests with:

    XMAGIC_LIVE_TESTS=1 uv run pytest tests/test_client_contracts.py -k live
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import respx
from httpx import Response

from xmagic import XMagicClient
from xmagic.client.models import ChatType
from xmagic.config import DEFAULT_BASE_URL, Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _load_text_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _sse_frames_from_fixture(name: str) -> str:
    """Extract just the ``data: ...`` lines from the annotated fixture file."""
    lines = [
        line for line in _load_text_fixture(name).splitlines() if line.startswith("data: ")
    ]
    return "\n\n".join(lines) + "\n\n"


def _load_env_file(repo_root: Path) -> None:
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _resolve_live_credentials(repo_root: Path) -> tuple[str | None, str | None]:
    """Resolve (api_key, agent_id) using the SDK's own precedence rules.

    ``Settings.load()`` already merges, in order: explicit kwargs > env vars >
    ``config.toml`` (written by ``xmagic configure``) > defaults. Loading the
    repo's ``.env`` first lets a local dev key take priority without needing
    it exported in the shell, while still falling back to a key stored via
    ``xmagic configure`` if no env var/``.env`` value is present.
    """
    _load_env_file(repo_root)
    settings = Settings.load()
    agent_id = os.environ.get("XMAGIC_TEST_AGENT_ID") or settings.default_agent_id
    return settings.api_key, agent_id


@pytest.fixture
def client() -> XMagicClient:
    c = XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL)
    try:
        yield c
    finally:
        c.close()


@respx.mock
def test_create_chat_request_and_response_shape(client: XMagicClient) -> None:
    fixture = _load_json_fixture("create_chat_response.json")
    route = respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats").mock(
        return_value=Response(200, json=fixture)
    )

    chat = client.chats.create("agent-1", title="Demo", chat_type=ChatType.STANDARD)

    assert chat.id == "REDACTED_CHAT_ID"
    assert chat.title == "contract-capture"
    assert chat.chat_type.value == "standard"
    sent = route.calls.last.request.read().decode()
    assert '"title":"Demo"' in sent
    assert '"chat_type":"standard"' in sent


@respx.mock
def test_query_request_and_non_stream_response_shape(client: XMagicClient) -> None:
    fixture = _load_json_fixture("query_response.json")
    route = respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query").mock(
        return_value=Response(200, json=fixture)
    )

    resp = client.chats.query(
        "agent-1",
        "chat-1",
        "Hello",
        uploaded_files=["file-1"],
    )

    assert resp.message_id == "REDACTED_MESSAGE_ID"
    assert resp.text == "capture-ok"
    sent = route.calls.last.request.read().decode()
    assert '"query":"Hello"' in sent
    assert '"is_stream":false' in sent
    assert '"uploaded_files":["file-1"]' in sent


@respx.mock
def test_get_message_response_shape(client: XMagicClient) -> None:
    fixture = _load_json_fixture("get_message_response.json")
    respx.get(
        f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/message/msg-1"
    ).mock(return_value=Response(200, json=fixture))

    message = client.chats.get_message("agent-1", "chat-1", "msg-1")

    assert message.id == "REDACTED_MESSAGE_ID"
    assert message.query == "Reply with exactly: getmsg-ok"
    assert message.response == "getmsg-ok"
    assert message.output_assets == {}


@respx.mock
def test_stream_uses_payload_type_not_sse_event(client: XMagicClient) -> None:
    # Recorded raw SSE frames: no `event:` field is ever sent, so event identity
    # must come from payload["type"], not the SSE event name (all "message").
    sse_body = _sse_frames_from_fixture("stream_sse_frames.txt")

    respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query").mock(
        return_value=Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )
    )

    events = list(client.chats.stream("agent-1", "chat-1", "hello"))
    assert [e.type for e in events] == ["metadata", "response", "response", "end_response", "done"]
    assert [e.text for e in events] == ["", "1,", " 2, 3.", "", ""]
    assert events[0].raw["data"]["message_id"] == "REDACTED_MESSAGE_ID"


@respx.mock
def test_uploaded_files_shape_string_data(client: XMagicClient, tmp_path: Path) -> None:
    fixture = _load_json_fixture("drive_uploaded_file_response.json")
    p = tmp_path / "note.txt"
    p.write_text("hello")

    respx.post(f"{DEFAULT_BASE_URL}/uploaded-files").mock(
        return_value=Response(200, json=fixture)
    )

    uploaded = client.files.upload(p)
    assert uploaded.id == "REDACTED_UPLOADED_FILE_ID"
    assert uploaded.filename == "note.txt"


@respx.mock
def test_drive_uses_knowledge_base_routes(client: XMagicClient, tmp_path: Path) -> None:
    empty_list = _load_json_fixture("drive_list_folders_empty.json")
    create_response = _load_json_fixture("drive_create_folder_response.json")
    uploaded_response = _load_json_fixture("drive_uploaded_file_response.json")
    attach_response = _load_json_fixture("drive_attach_data_source_response.json")
    list_files_response = _load_json_fixture("drive_list_files_response.json")

    def kb_list_response(request):
        if request.url.params.get("parent_kb_id") == "REDACTED_KB_ID":
            return Response(200, json=list_files_response)
        return Response(200, json=empty_list)

    kb_route = respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases").mock(side_effect=kb_list_response)

    create_route = respx.post(f"{DEFAULT_BASE_URL}/knowledge-bases").mock(
        return_value=Response(200, json=create_response)
    )

    uploaded_route = respx.post(f"{DEFAULT_BASE_URL}/uploaded-files").mock(
        return_value=Response(200, json=uploaded_response)
    )

    attach_route = respx.post(
        f"{DEFAULT_BASE_URL}/knowledge-bases/REDACTED_KB_ID/data-sources/documents"
    ).mock(return_value=Response(200, json=attach_response))

    delete_route = respx.delete(f"{DEFAULT_BASE_URL}/knowledge-bases/REDACTED_KB_ID").mock(
        return_value=Response(200, json={"message": "Knowledge base and all its contents deleted successfully"})
    )

    # Empty account: GET /knowledge-bases returns `data.results == []`.
    folders = client.drive.list_folders()
    assert folders == []

    created = client.drive.create_folder("sdk-contract-capture")
    assert created.id == "REDACTED_KB_ID"
    assert create_route.called

    local_file = tmp_path / "capture.txt"
    local_file.write_text("hello")
    uploaded = client.drive.upload_file("REDACTED_KB_ID", local_file)
    assert uploaded.id == "REDACTED_DATA_SOURCE_ID"
    assert uploaded.knowledge_base_id == "REDACTED_KB_ID"
    assert uploaded_route.called

    sent = attach_route.calls.last.request.read().decode()
    assert '"file_id":"REDACTED_UPLOADED_FILE_ID"' in sent
    assert '"data_source_title":"capture.txt"' in sent

    listed_files = client.drive.list_files("REDACTED_KB_ID")
    assert [f.id for f in listed_files] == ["REDACTED_DATA_SOURCE_ID"]
    assert kb_route.called

    client.drive.delete_folder("REDACTED_KB_ID")
    assert delete_route.called

    # One folder-list request and one file-list request both hit /knowledge-bases.
    assert kb_route.call_count == 2


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("XMAGIC_LIVE_TESTS") != "1",
    reason="Set XMAGIC_LIVE_TESTS=1 to run live contract tests",
)
def test_live_drive_contracts(tmp_path: Path) -> None:
    """Full create/upload/list/delete round trip against the real backend.

    Creates a real (temporary) knowledge-base folder and file, then deletes
    the folder in a ``finally`` block to leave the account clean.
    """
    repo_root = Path(__file__).resolve().parents[1]
    api_key, _ = _resolve_live_credentials(repo_root)

    if not api_key:
        pytest.skip("XMAGIC_API_KEY not found in environment, .env, or config.toml")

    with XMagicClient(api_key=api_key) as c:
        folder = c.drive.create_folder("xmagic-sdk-live-drive-test")
        try:
            assert folder.id

            local_file = tmp_path / "live-drive-test.txt"
            local_file.write_text("live drive contract test")
            uploaded = c.drive.upload_file(folder.id, local_file)
            assert uploaded.id
            assert uploaded.knowledge_base_id == folder.id

            files = c.drive.list_files(folder.id)
            assert any(f.id == uploaded.id for f in files)
        finally:
            c.drive.delete_folder(folder.id)


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("XMAGIC_LIVE_TESTS") != "1",
    reason="Set XMAGIC_LIVE_TESTS=1 to run live contract tests",
)
def test_live_chat_contracts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    api_key, agent_id = _resolve_live_credentials(repo_root)

    if not api_key:
        pytest.skip("XMAGIC_API_KEY not found in environment, .env, or config.toml")
    if not agent_id:
        pytest.skip(
            "XMAGIC_TEST_AGENT_ID is required for live tests "
            "(or set default_agent_id via `xmagic configure`)"
        )

    with XMagicClient(api_key=api_key) as c:
        chat = c.chats.create(agent_id, title="sdk live contract test")
        assert chat.id

        resp = c.chats.query(agent_id, chat.id, "Reply with exactly: live-ok")
        assert isinstance(resp.text, str)
        assert resp.text

        events = list(c.chats.stream(agent_id, chat.id, "Say stream-ok in one line"))
        assert events
        assert events[-1].type == "done"


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("XMAGIC_LIVE_TESTS") != "1",
    reason="Set XMAGIC_LIVE_TESTS=1 to run live contract tests",
)
def test_live_file_upload_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    api_key, _ = _resolve_live_credentials(repo_root)

    if not api_key:
        pytest.skip("XMAGIC_API_KEY not found in environment, .env, or config.toml")

    tmp = Path("/tmp") / "xmagic-sdk-live-upload.txt"
    tmp.write_text("contract test")

    with XMagicClient(api_key=api_key) as c:
        uploaded = c.files.upload(tmp)
        assert uploaded.id
