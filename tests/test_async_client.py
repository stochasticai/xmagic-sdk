"""Contract tests for AsyncXMagicClient.

These replay the *same* recorded fixtures as ``test_client_contracts.py`` (see
that module's docstring for provenance). If the async client ever diverges from
the sync one on the wire, these fail.

``test_async_mirrors_sync_signatures`` guards the mirror structurally, so a new
method or a changed argument on one side cannot land without the other.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from xmagic import AsyncXMagicClient
from xmagic.client.agents import AgentsAPI, AsyncAgentsAPI
from xmagic.client.chats import AsyncChatsAPI, ChatsAPI
from xmagic.client.drive import AsyncDriveAPI, DriveAPI
from xmagic.client.files import AsyncFilesAPI, FilesAPI
from xmagic.client.phones import AsyncPhonesAPI, PhonesAPI
from xmagic.client.models import ChatType
from xmagic.client.worklists import AsyncWorklistsAPI, WorklistsAPI
from xmagic.client.workspaces import AsyncWorkspacesAPI, WorkspacesAPI
from xmagic.config import DEFAULT_BASE_URL
from xmagic.errors import ConfigurationError, RateLimitError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json_fixture(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text())
    return loaded


def _sse_frames_from_fixture(name: str) -> str:
    text = (FIXTURES_DIR / name).read_text()
    lines = [line for line in text.splitlines() if line.startswith("data: ")]
    return "\n\n".join(lines) + "\n\n"


@pytest.fixture
async def client() -> AsyncIterator[AsyncXMagicClient]:
    c = AsyncXMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL)
    try:
        yield c
    finally:
        await c.aclose()


@respx.mock
async def test_create_chat_request_and_response_shape(client: AsyncXMagicClient) -> None:
    fixture = _load_json_fixture("create_chat_response.json")
    route = respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats").mock(
        return_value=Response(200, json=fixture)
    )

    chat = await client.chats.create("agent-1", title="Demo", chat_type=ChatType.STANDARD)

    assert chat.id == "REDACTED_CHAT_ID"
    # Identity, not `.value`: `chat_type` is optional on the model, and the
    # wire spelling is pinned by the request assertion below.
    assert chat.chat_type is ChatType.STANDARD
    sent = route.calls.last.request.read().decode()
    assert '"title":"Demo"' in sent
    assert '"chat_type":"standard"' in sent


@respx.mock
async def test_query_request_and_response_shape(client: AsyncXMagicClient) -> None:
    fixture = _load_json_fixture("query_response.json")
    route = respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query").mock(
        return_value=Response(200, json=fixture)
    )

    resp = await client.chats.query("agent-1", "chat-1", "Hello", uploaded_files=["file-1"])

    assert resp.message_id == "REDACTED_MESSAGE_ID"
    assert resp.text == "capture-ok"
    sent = route.calls.last.request.read().decode()
    assert '"query":"Hello"' in sent
    assert '"is_stream":false' in sent
    assert '"uploaded_files":["file-1"]' in sent


@respx.mock
async def test_stream_yields_same_events_as_sync(client: AsyncXMagicClient) -> None:
    respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/query").mock(
        return_value=Response(
            200,
            text=_sse_frames_from_fixture("stream_sse_frames.txt"),
            headers={"content-type": "text/event-stream"},
        )
    )

    events = [e async for e in client.chats.stream("agent-1", "chat-1", "hello")]

    # Identical to the sync assertions in test_client_contracts.py.
    assert [e.type for e in events] == ["metadata", "response", "response", "end_response", "done"]
    assert [e.text for e in events] == ["", "1,", " 2, 3.", "", ""]
    assert events[0].raw["data"]["message_id"] == "REDACTED_MESSAGE_ID"


@respx.mock
async def test_get_message_response_shape(client: AsyncXMagicClient) -> None:
    fixture = _load_json_fixture("get_message_response.json")
    respx.get(f"{DEFAULT_BASE_URL}/agents/agent-1/chats/chat-1/message/msg-1").mock(
        return_value=Response(200, json=fixture)
    )

    message = await client.chats.get_message("agent-1", "chat-1", "msg-1")

    assert message.id == "REDACTED_MESSAGE_ID"
    assert message.response == "getmsg-ok"


@respx.mock
async def test_file_upload_shape(client: AsyncXMagicClient, tmp_path: Path) -> None:
    fixture = _load_json_fixture("drive_uploaded_file_response.json")
    p = tmp_path / "note.txt"
    p.write_text("hello")

    respx.post(f"{DEFAULT_BASE_URL}/uploaded-files").mock(return_value=Response(200, json=fixture))

    uploaded = await client.files.upload(p)

    assert uploaded.id == "REDACTED_UPLOADED_FILE_ID"
    assert uploaded.filename == "note.txt"


@respx.mock
async def test_drive_two_step_upload(client: AsyncXMagicClient, tmp_path: Path) -> None:
    uploaded_response = _load_json_fixture("drive_uploaded_file_response.json")
    attach_response = _load_json_fixture("drive_attach_data_source_response.json")
    list_files_response = _load_json_fixture("drive_list_files_response.json")

    respx.post(f"{DEFAULT_BASE_URL}/uploaded-files").mock(
        return_value=Response(200, json=uploaded_response)
    )
    attach_route = respx.post(
        f"{DEFAULT_BASE_URL}/knowledge-bases/REDACTED_KB_ID/data-sources/documents"
    ).mock(return_value=Response(200, json=attach_response))
    respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases").mock(
        return_value=Response(200, json=list_files_response)
    )

    local_file = tmp_path / "capture.txt"
    local_file.write_text("hello")

    uploaded = await client.drive.upload_file("REDACTED_KB_ID", local_file)
    assert uploaded.id == "REDACTED_DATA_SOURCE_ID"

    sent = attach_route.calls.last.request.read().decode()
    assert '"file_id":"REDACTED_UPLOADED_FILE_ID"' in sent

    listed = await client.drive.list_files("REDACTED_KB_ID")
    assert [f.id for f in listed] == ["REDACTED_DATA_SOURCE_ID"]


@respx.mock
async def test_retries_use_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff must not block the event loop, and must honor Retry-After."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("xmagic.client.http.asyncio.sleep", fake_sleep)

    respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats").mock(
        side_effect=[
            Response(429, headers={"Retry-After": "5"}, json={}),
            Response(503, json={}),
            Response(200, json={"data": {"chat": {"id": "chat-1"}}}),
        ]
    )

    async with AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        chat = await client.chats.create("agent-1")

    assert chat.id == "chat-1"
    # The header value verbatim, then the jittered attempt-1 backoff from [1, 2].
    assert delays[0] == 5.0
    assert 1.0 <= delays[1] <= 2.0
    assert len(delays) == 2


@respx.mock
async def test_retries_exhausted_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("xmagic.client.http.asyncio.sleep", fake_sleep)
    respx.post(f"{DEFAULT_BASE_URL}/agents/agent-1/chats").mock(
        return_value=Response(429, json={"message": "rate limit exceeded"})
    )

    async with AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL, max_retries=1) as c:
        with pytest.raises(RateLimitError) as exc:
            await c.chats.create("agent-1")

    assert exc.value.status_code == 429


async def test_missing_api_key_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", "/nonexistent/xmagic.toml")

    with pytest.raises(ConfigurationError):
        AsyncXMagicClient()


async def test_context_manager_closes_transport() -> None:
    async with AsyncXMagicClient(api_key="k", base_url=DEFAULT_BASE_URL) as client:
        assert client.chats is not None
    assert client._transport._client.is_closed


@pytest.mark.parametrize(
    ("sync_cls", "async_cls"),
    [
        (ChatsAPI, AsyncChatsAPI),
        (FilesAPI, AsyncFilesAPI),
        (DriveAPI, AsyncDriveAPI),
        (WorkspacesAPI, AsyncWorkspacesAPI),
        (AgentsAPI, AsyncAgentsAPI),
        (PhonesAPI, AsyncPhonesAPI),
        (WorklistsAPI, AsyncWorklistsAPI),
    ],
)
def test_async_mirrors_sync_signatures(sync_cls: type, async_cls: type) -> None:
    """The async API is a 1:1 mirror — same methods, same arguments.

    Structural rather than behavioral: it catches a method added to one side, or
    an argument renamed on one side, which fixture tests would silently miss.
    """

    def public_methods(cls: type) -> dict[str, inspect.Signature]:
        return {
            name: inspect.signature(fn)
            for name, fn in vars(cls).items()
            if callable(fn) and not name.startswith("_")
        }

    sync_methods = public_methods(sync_cls)
    async_methods = public_methods(async_cls)

    assert sync_methods.keys() == async_methods.keys()
    for name, sync_sig in sync_methods.items():
        assert list(sync_sig.parameters) == list(async_methods[name].parameters), name
