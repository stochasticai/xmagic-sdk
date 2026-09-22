"""``xmagic.testing.FakeXMagic``: the in-process backend consumers test against.

Two promises are checked here. The fake answers every route the SDK's chats,
files, and Drive resources speak, through the real client code and both
transports. And what it answers with is the recorded live shape: each body it
renders carries the same keys as the fixture it was rendered from, so a
consumer's test and this package's contract tests pin the same wire format.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.config import DEFAULT_BASE_URL
from xmagic.errors import (
    BadRequestError,
    NotFoundError,
    RateLimitError,
    ServerError,
    XMagicAPIError,
)
from xmagic.providers.base import ChatMessage
from xmagic.providers.xmagic import XMagicProvider
from xmagic.testing import FakeXMagic, fixture_path, load_fixture, sse_frames

# -- chats -------------------------------------------------------------------------


def test_scripted_replies_are_consumed_in_order_and_the_last_repeats() -> None:
    fake = FakeXMagic()
    fake.agent("a").replies("one", "two")
    client = fake.client()
    chat = client.chats.create("a")

    answers = [client.chats.query("a", chat.id, f"q{i}").text for i in range(4)]

    assert answers == ["one", "two", "two", "two"]


def test_callable_reply_sees_the_query_and_unscripted_agents_echo() -> None:
    fake = FakeXMagic()
    fake.agent("a").replies(lambda q: q.upper())
    client = fake.client()
    chat = client.chats.create("a")

    assert client.chats.query("a", chat.id, "shout").text == "SHOUT"

    other = client.chats.create("b")
    assert client.chats.query("b", other.id, "unscripted").text == "unscripted"


def test_chat_and_query_bodies_carry_the_recorded_keys() -> None:
    fake = FakeXMagic()
    client = fake.client()

    chat = client.chats.create("a", title="Demo")
    resp = client.chats.query("a", chat.id, "hi")

    assert chat.title == "Demo"
    assert chat.agent_id == "a"
    recorded_chat = load_fixture("create_chat_response.json")["data"]["chat"]
    assert set(recorded_chat) <= set(chat.model_dump())
    recorded_query = load_fixture("query_response.json")["data"]
    assert set(recorded_query) <= set(resp.model_dump())
    assert resp.message_id == "msg-1"


def test_get_message_returns_what_was_asked_and_answered() -> None:
    fake = FakeXMagic()
    fake.agent("a").replies("42")
    client = fake.client()
    chat = client.chats.create("a")
    resp = client.chats.query("a", chat.id, "meaning?")
    assert resp.message_id is not None

    message = client.chats.get_message("a", chat.id, resp.message_id)

    assert (message.query, message.response) == ("meaning?", "42")
    recorded = load_fixture("get_message_response.json")["data"]
    assert set(recorded) <= set(message.model_dump())

    client.chats.delete_message("a", chat.id, resp.message_id)
    with pytest.raises(NotFoundError):
        client.chats.get_message("a", chat.id, resp.message_id)


def test_stream_follows_the_recorded_frame_sequence() -> None:
    fake = FakeXMagic()
    fake.agent("a").replies("1, 2, 3.")
    client = fake.client()
    chat = client.chats.create("a")

    events = list(client.chats.stream("a", chat.id, "count"))

    assert [e.type for e in events] == [
        "metadata",
        "response",
        "response",
        "response",
        "end_response",
        "done",
    ]
    assert "".join(e.text for e in events) == "1, 2, 3."
    assert events[0].raw["data"]["message_id"] == "msg-1"
    # Same frame keys as the live recording.
    recorded_frame = sse_frames("stream_sse_frames.txt").split("\n\n")[0]
    assert '"extended_text"' in recorded_frame
    assert set(events[1].raw.keys()) == {
        "text",
        "extended_text",
        "type",
        "subtype",
        "data",
        "elapsed_ms",
    }


def test_unknown_chat_or_wrong_agent_is_not_found() -> None:
    fake = FakeXMagic()
    client = fake.client()
    chat = client.chats.create("a")

    with pytest.raises(NotFoundError):
        client.chats.query("a", "chat-99", "hi")
    with pytest.raises(NotFoundError):
        client.chats.query("b", chat.id, "hi")


def test_calls_are_recorded_without_the_key() -> None:
    fake = FakeXMagic()
    client = fake.client()
    chat = client.chats.create("a", title="t")
    client.chats.query("a", chat.id, "hi", uploaded_files=None)

    assert [(c.method, c.path) for c in fake.calls] == [
        ("POST", "/agents/a/chats"),
        ("POST", f"/agents/a/chats/{chat.id}/query"),
    ]
    assert fake.calls[0].json == {"chat_type": "standard", "title": "t"}
    assert fake.calls[1].json == {"query": "hi", "is_stream": False}
    assert "fake-key" not in repr(fake.calls)


# -- uploads and drive ------------------------------------------------------------


def test_upload_then_reference_in_a_query(tmp_path: Path) -> None:
    fake = FakeXMagic()
    client = fake.client()
    note = tmp_path / "note.txt"
    note.write_bytes(b"hello\n")

    uploaded = client.files.upload(note)
    chat = client.chats.create("a")
    client.chats.query("a", chat.id, "summarize", uploaded_files=[uploaded.id])

    assert uploaded.filename == "note.txt"
    assert fake.uploads[uploaded.id].content == b"hello\n"
    assert fake.chats[chat.id].messages[0].uploaded_files == [uploaded.id]
    with pytest.raises(NotFoundError):
        client.chats.query("a", chat.id, "again", uploaded_files=["file-404"])


def test_drive_round_trip_including_download(tmp_path: Path) -> None:
    fake = FakeXMagic()
    client = fake.client()
    assert client.drive.list_folders() == []

    folder = client.drive.create_folder("docs", user_defined_tags=["q3"])
    local = tmp_path / "capture.txt"
    local.write_text("captured")
    file = client.drive.upload_file(folder.id, local)

    assert [f.id for f in client.drive.list_folders()] == [folder.id]
    assert client.drive.get_folder(folder.id).name == "docs"
    assert client.drive.update_folder(folder.id, name="notes").name == "notes"
    listed = client.drive.list_files(folder.id)
    assert [(f.id, f.title, f.knowledge_base_id) for f in listed] == [
        (file.id, "capture.txt", folder.id)
    ]

    archive = zipfile.ZipFile(io.BytesIO(client.drive.download_files(folder.id, file.id)))
    assert archive.read("capture.txt") == b"captured"

    client.drive.delete_files(folder.id, [file.id])
    assert client.drive.list_files(folder.id) == []
    client.drive.delete_folder(folder.id)
    with pytest.raises(NotFoundError):
        client.drive.get_folder(folder.id)


def test_drive_bodies_carry_the_recorded_keys(tmp_path: Path) -> None:
    fake = FakeXMagic()
    client = fake.client()
    folder = client.drive.create_folder("docs")
    local = tmp_path / "a.txt"
    local.write_text("a")
    file = client.drive.upload_file(folder.id, local)
    listed = client.drive.list_files(folder.id)[0]

    assert set(load_fixture("drive_create_folder_response.json")["data"]) <= set(
        folder.model_dump()
    )
    assert set(load_fixture("drive_attach_data_source_response.json")["data"]) <= set(
        file.model_dump()
    )
    assert set(load_fixture("drive_list_files_response.json")["data"]["results"][0]) <= set(
        listed.model_dump()
    )


# -- failures and the unfaked -----------------------------------------------------


def test_unfaked_route_fails_loudly_naming_it() -> None:
    fake = FakeXMagic()
    client = fake.client()

    with pytest.raises(BadRequestError, match=r"not fake GET /agents/a/worklist"):
        client.worklists.list("a")


def test_fail_next_injects_a_typed_error_then_recovers() -> None:
    fake = FakeXMagic()
    client = fake.client(max_retries=0)
    fake.fail_next(500, message="boom")

    with pytest.raises(ServerError, match="boom"):
        client.chats.create("a")
    assert client.chats.create("a").id == "chat-1"


def test_fail_next_429_is_retried_through_the_real_retry_loop() -> None:
    fake = FakeXMagic()
    client = fake.client()  # default max_retries=3
    fake.fail_next(429, times=2)

    assert client.chats.create("a").id == "chat-1"
    assert [c.path for c in fake.calls] == ["/agents/a/chats"] * 3

    fake.fail_next(429, times=4)
    with pytest.raises(RateLimitError):
        client.chats.create("a")


# -- other ways in ------------------------------------------------------------------


async def test_async_client_shares_the_fake() -> None:
    fake = FakeXMagic()
    fake.agent("a").replies("async ok")
    async with fake.async_client() as client:
        chat = await client.chats.create("a")
        resp = await client.chats.query("a", chat.id, "hi")
        events = [e async for e in client.chats.stream("a", chat.id, "again")]

    assert resp.text == "async ok"
    assert "".join(e.text for e in events) == "async ok"
    assert len(fake.chats[chat.id].messages) == 2


def test_transport_can_be_wired_into_a_hand_built_client() -> None:
    fake = FakeXMagic()
    client = XMagicClient(api_key="k", base_url=DEFAULT_BASE_URL, http_transport=fake.transport)
    assert client.chats.create("a").id == "chat-1"
    client.close()


async def test_transport_can_be_wired_into_a_hand_built_async_client() -> None:
    fake = FakeXMagic()
    async with AsyncXMagicClient(
        api_key="k", base_url=DEFAULT_BASE_URL, http_transport=fake.transport
    ) as client:
        assert (await client.chats.create("a")).id == "chat-1"


def test_provider_accepts_the_fake_client() -> None:
    fake = FakeXMagic()
    fake.agent("agent-1").replies("Paris")
    provider = XMagicProvider(client=fake.client())
    messages = [ChatMessage(role="user", content="Capital of France?")]

    completion = provider.complete(messages, model="agent-1")
    chunks = list(provider.stream(messages, model="agent-1"))

    assert completion.text == "Paris"
    assert completion.id == "msg-1"
    assert "".join(c.text for c in chunks) == "Paris"
    assert chunks[-1].done and chunks[-1].id == "msg-2"
    assert provider.chat_id == "chat-1"


def test_fixture_helpers_name_what_exists() -> None:
    assert fixture_path("query_response.json").is_file()
    with pytest.raises(FileNotFoundError, match=r"query_response\.json"):
        fixture_path("nope.json")
    body = load_fixture("query_response.json")
    assert "_comment" not in body
    body["data"]["text"] = "edited"
    assert load_fixture("query_response.json")["data"]["text"] == "capture-ok"


def test_drive_listing_pages_like_the_platform() -> None:
    fake = FakeXMagic()
    client = fake.client()
    ids = [client.drive.create_folder(f"f{i}").id for i in range(201)]

    assert [f.id for f in client.drive.list_folders()] == ids

    walks = [c.params for c in fake.calls if c.method == "GET" and c.path == "/knowledge-bases"]
    assert walks == [
        {"page": "0", "page_size": "200"},
        {"page": "1", "page_size": "200"},
    ]

    with pytest.raises(XMagicAPIError):
        fake.client()._transport.request("GET", "/knowledge-bases", params={"page_size": 201})
