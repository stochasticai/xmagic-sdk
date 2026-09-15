"""An in-process fake of the xMagic backend, for tests of code that uses the SDK.

The real client runs unchanged; only the network is replaced. ``FakeXMagic``
is an ``httpx`` transport that answers the endpoints the SDK speaks, keeps
in-memory state (chats, messages, uploads, Drive folders), and renders every
response from the same recorded fixtures the SDK's own contract tests replay.
A test that passes against it therefore exercises the same request and
response shapes the live API was observed to use.

Usage::

    from xmagic.testing import FakeXMagic

    fake = FakeXMagic()
    fake.agent("agent-1").replies("Paris")
    client = fake.client()

    chat = client.chats.create("agent-1")
    assert client.chats.query("agent-1", chat.id, "Capital of France?").text == "Paris"
    assert fake.calls[-1].json == {"query": "Capital of France?", "is_stream": False}

What is faked: chats (create, query, stream, get and delete message), file
uploads, and Drive (folders, files, download). Everything else answers
``400`` with ``error_code="not_faked"``, which the client raises as
``BadRequestError`` naming the route, so an unfaked call fails loudly rather
than returning an invented shape.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from xmagic.client import AsyncXMagicClient, XMagicClient
from xmagic.config import DEFAULT_BASE_URL
from xmagic.testing._fixtures import load_fixture

Reply = str | Callable[[str], str]
"""A scripted answer: the text itself, or a function of the query."""


@dataclass
class RecordedCall:
    """One request the code under test made, for assertions.

    ``path`` is relative to the API base (``/agents/a/chats``), ``params`` is
    the query string, and ``json`` is the decoded body when it was JSON. The
    API key is deliberately not recorded.
    """

    method: str
    path: str
    params: dict[str, str]
    json: Any | None


@dataclass
class FakeMessage:
    """A query and the reply the fake gave it."""

    id: str
    chat_id: str
    agent_id: str
    query: str
    response: str
    uploaded_files: list[str] = field(default_factory=list)


@dataclass
class FakeChat:
    """A chat session and its messages, in order."""

    id: str
    agent_id: str
    title: str | None
    chat_type: str
    messages: list[FakeMessage] = field(default_factory=list)


@dataclass
class FakeUpload:
    """A file received on ``POST /uploaded-files``."""

    id: str
    filename: str
    content: bytes


@dataclass
class FakeFile:
    """A data source attached to a Drive folder."""

    id: str
    folder_id: str
    title: str
    uploaded_file_id: str


@dataclass
class FakeFolder:
    """A Drive folder (knowledge base) and the files in it."""

    id: str
    name: str
    tags: list[str] = field(default_factory=list)
    files: dict[str, FakeFile] = field(default_factory=dict)


@dataclass
class _Failure:
    status: int
    error_code: str
    message: str


class AgentScript:
    """The replies one agent gives, in order.

    Replies are consumed one per query; once the script runs out, the last
    reply repeats. With no script at all, the agent echoes the query, so a
    test that has not scripted an answer still sees its own input come back
    rather than an invented sentence.
    """

    def __init__(self) -> None:
        self._queued: deque[Reply] = deque()
        self._last: Reply | None = None

    def replies(self, *answers: Reply) -> AgentScript:
        """Queue answers; each is a string or a ``(query) -> str`` callable."""
        self._queued.extend(answers)
        return self

    def answer(self, query: str) -> str:
        if self._queued:
            self._last = self._queued.popleft()
        if self._last is None:
            return query
        return self._last(query) if callable(self._last) else self._last


_Handler = Callable[["FakeXMagic", "re.Match[str]", Any, dict[str, str]], httpx.Response]


class FakeXMagic:
    """The fake backend. See the module docstring for what it answers.

    ``transport`` is an ``httpx.MockTransport`` usable by both the sync and
    async clients; :meth:`client` and :meth:`async_client` build clients
    already wired to it. ``calls``, ``chats``, ``uploads`` and ``folders`` are
    the state a test inspects afterwards.
    """

    def __init__(self, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._prefix = urlsplit(self.base_url).path.rstrip("/")
        self.calls: list[RecordedCall] = []
        self.chats: dict[str, FakeChat] = {}
        self.uploads: dict[str, FakeUpload] = {}
        self.folders: dict[str, FakeFolder] = {}
        self._agents: dict[str, AgentScript] = {}
        self._failures: deque[_Failure] = deque()
        self._counters: dict[str, int] = {}
        self.transport = httpx.MockTransport(self._handle)

    # -- configuration ------------------------------------------------------

    def agent(self, agent_id: str) -> AgentScript:
        """The script for ``agent_id``; any id is accepted and created on first use."""
        return self._agents.setdefault(agent_id, AgentScript())

    def fail_next(
        self,
        status: int,
        *,
        error_code: str | None = None,
        message: str | None = None,
        times: int = 1,
    ) -> None:
        """Answer the next ``times`` requests with an error, whatever they are.

        The body is the backend's ``{"error": {"error_code", "message"}}`` shape,
        so the client raises the same typed error it would for the real thing.
        A ``429`` carries a small ``Retry-After``, so a client left at its
        default retry count recovers within milliseconds rather than backing
        off for seconds.
        """
        for _ in range(times):
            self._failures.append(
                _Failure(status, error_code or f"fake_{status}", message or f"Injected {status}")
            )

    def client(self, **kw: Any) -> XMagicClient:
        """A sync client bound to this fake. ``kw`` reaches the client (``max_retries=0``...)."""
        return XMagicClient(
            api_key="fake-key", base_url=self.base_url, http_transport=self.transport, **kw
        )

    def async_client(self, **kw: Any) -> AsyncXMagicClient:
        """An async client bound to this fake. Build it inside a running event loop."""
        return AsyncXMagicClient(
            api_key="fake-key", base_url=self.base_url, http_transport=self.transport, **kw
        )

    # -- dispatch -------------------------------------------------------------

    def _next_id(self, kind: str) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return f"{kind}-{self._counters[kind]}"

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if self._prefix and path.startswith(self._prefix):
            path = path[len(self._prefix) :]
        params = {key: value for key, value in request.url.params.items()}
        content = request.read()
        content_type = request.headers.get("content-type", "")
        payload = _json_or_none(content_type, content)
        self._last_multipart = (
            _multipart_file(content_type, content) if "multipart" in content_type else None
        )
        self.calls.append(RecordedCall(request.method, path, params, payload))

        if self._failures:
            failure = self._failures.popleft()
            headers = {"Retry-After": "0.01"} if failure.status == 429 else {}
            return _error(failure.status, failure.error_code, failure.message, headers=headers)

        for method, pattern, handler in _ROUTES:
            if method != request.method:
                continue
            match = pattern.match(path)
            if match:
                return handler(self, match, payload, params)
        return _error(
            400,
            "not_faked",
            f"FakeXMagic does not fake {request.method} {path}. "
            "Faked: chats, uploaded files, and Drive. Mock this route yourself, "
            "or script the fake's transport around it.",
        )

    # -- chats ----------------------------------------------------------------

    def _create_chat(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        body = payload if isinstance(payload, dict) else {}
        chat = FakeChat(
            id=self._next_id("chat"),
            agent_id=match["agent"],
            title=body.get("title"),
            chat_type=body.get("chat_type", "standard"),
        )
        self.chats[chat.id] = chat
        return httpx.Response(200, json=_chat_body(chat))

    def _query(self, match: re.Match[str], payload: Any, params: dict[str, str]) -> httpx.Response:
        chat = self.chats.get(match["chat"])
        if chat is None or chat.agent_id != match["agent"]:
            return _error(404, "not_found", f"Chat {match['chat']} not found")
        body = payload if isinstance(payload, dict) else {}
        uploaded = list(body.get("uploaded_files") or [])
        for file_id in uploaded:
            if file_id not in self.uploads:
                return _error(404, "not_found", f"Uploaded file {file_id} not found")
        query = str(body.get("query", ""))
        message = FakeMessage(
            id=self._next_id("msg"),
            chat_id=chat.id,
            agent_id=chat.agent_id,
            query=query,
            response=self.agent(chat.agent_id).answer(query),
            uploaded_files=uploaded,
        )
        chat.messages.append(message)
        if body.get("is_stream"):
            return _sse_response(message)
        result = load_fixture("query_response.json")
        result["data"].update({"message_id": message.id, "text": message.response})
        return httpx.Response(200, json=result)

    def _find_message(self, match: re.Match[str]) -> FakeMessage | httpx.Response:
        chat = self.chats.get(match["chat"])
        if chat is None or chat.agent_id != match["agent"]:
            return _error(404, "not_found", f"Chat {match['chat']} not found")
        for message in chat.messages:
            if message.id == match["msg"]:
                return message
        return _error(404, "not_found", f"Message {match['msg']} not found")

    def _get_message(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        found = self._find_message(match)
        if isinstance(found, httpx.Response):
            return found
        result = load_fixture("get_message_response.json")
        result["data"].update(
            {
                "id": found.id,
                "chat_id": found.chat_id,
                "agent_id": found.agent_id,
                "query": found.query,
                "response": found.response,
            }
        )
        return httpx.Response(200, json=result)

    def _delete_message(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        found = self._find_message(match)
        if isinstance(found, httpx.Response):
            return found
        self.chats[found.chat_id].messages.remove(found)
        return httpx.Response(200, json={"message": "Message deleted successfully"})

    # -- uploads --------------------------------------------------------------

    def _upload(self, match: re.Match[str], payload: Any, params: dict[str, str]) -> httpx.Response:
        # The body is multipart, not JSON; `_handle` parsed the file part out
        # of the raw request before dispatch.
        if self._last_multipart is None:
            return _error(
                400, "bad_request", "POST /uploaded-files expects a multipart 'file' part"
            )
        filename, content = self._last_multipart
        upload = FakeUpload(id=self._next_id("file"), filename=filename, content=content)
        self.uploads[upload.id] = upload
        return httpx.Response(200, json={"data": upload.id})

    # -- drive ----------------------------------------------------------------

    def _list_kb(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        parent = params.get("parent_kb_id")
        if parent is None:
            results = [_folder_json(folder) for folder in self.folders.values()]
        else:
            folder = self.folders.get(parent)
            if folder is None:
                return _error(404, "not_found", f"Knowledge base {parent} not found")
            results = [_file_json(file, listing=True) for file in folder.files.values()]
        # The platform pages the listing: `page` is zero-indexed, `page_size`
        # is 1..200 (422 outside), both echoed back. Honoured here so a
        # consumer's test sees the same walk the client does live.
        try:
            page = int(params.get("page", 0))
            page_size = int(params.get("page_size", 20))
        except ValueError:
            return _error(422, "validation_error", "page and page_size must be integers")
        if page < 0 or not 1 <= page_size <= 200:
            return _error(422, "validation_error", "page >= 0 and 1 <= page_size <= 200")
        total = len(results)
        start = page * page_size
        result = load_fixture("drive_list_files_response.json")
        result["data"]["results"] = results[start : start + page_size]
        result["data"]["pagination"] = {"page": page, "page_size": page_size, "total_count": total}
        if parent is None:
            result["data"].pop("folder_info", None)
        else:
            result["data"]["folder_info"] = {
                "id": parent,
                "name": self.folders[parent].name,
                "is_root": True,
                "parent_kb_id": None,
            }
        return httpx.Response(200, json=result)

    def _create_folder(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        body = payload if isinstance(payload, dict) else {}
        folder = FakeFolder(
            id=self._next_id("folder"),
            name=str(body.get("knowledge_base_name", "")),
            tags=list(body.get("user_defined_tags") or []),
        )
        self.folders[folder.id] = folder
        return httpx.Response(200, json={"data": _folder_json(folder)})

    def _folder_or_404(self, match: re.Match[str]) -> FakeFolder | httpx.Response:
        folder = self.folders.get(match["folder"])
        if folder is None:
            return _error(404, "not_found", f"Knowledge base {match['folder']} not found")
        return folder

    def _get_folder(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        folder = self._folder_or_404(match)
        if isinstance(folder, httpx.Response):
            return folder
        return httpx.Response(200, json={"data": _folder_json(folder)})

    def _update_folder(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        folder = self._folder_or_404(match)
        if isinstance(folder, httpx.Response):
            return folder
        body = payload if isinstance(payload, dict) else {}
        if "knowledge_base_name" in body:
            folder.name = str(body["knowledge_base_name"])
        if "user_defined_tags" in body:
            folder.tags = list(body["user_defined_tags"])
        return httpx.Response(200, json={"data": _folder_json(folder)})

    def _delete_folder(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        folder = self._folder_or_404(match)
        if isinstance(folder, httpx.Response):
            return folder
        del self.folders[folder.id]
        return httpx.Response(
            200, json={"message": "Knowledge base and all its contents deleted successfully"}
        )

    def _attach(self, match: re.Match[str], payload: Any, params: dict[str, str]) -> httpx.Response:
        folder = self._folder_or_404(match)
        if isinstance(folder, httpx.Response):
            return folder
        body = payload if isinstance(payload, dict) else {}
        upload = self.uploads.get(str(body.get("file_id", "")))
        if upload is None:
            return _error(404, "not_found", f"Uploaded file {body.get('file_id')!r} not found")
        file = FakeFile(
            id=self._next_id("doc"),
            folder_id=folder.id,
            title=str(body.get("data_source_title") or upload.filename),
            uploaded_file_id=upload.id,
        )
        folder.files[file.id] = file
        return httpx.Response(200, json={"data": _file_json(file, listing=False)})

    def _selected_files(
        self, folder: FakeFolder, params: dict[str, str]
    ) -> list[FakeFile] | httpx.Response:
        ids = [i for i in params.get("data_source_id", "").split(",") if i]
        missing = [i for i in ids if i not in folder.files]
        if missing:
            return _error(404, "not_found", f"Data source {missing[0]} not found")
        return [folder.files[i] for i in ids]

    def _delete_files(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        folder = self._folder_or_404(match)
        if isinstance(folder, httpx.Response):
            return folder
        selected = self._selected_files(folder, params)
        if isinstance(selected, httpx.Response):
            return selected
        for file in selected:
            del folder.files[file.id]
        return httpx.Response(200, json={"message": "Data sources deleted successfully"})

    def _download(
        self, match: re.Match[str], payload: Any, params: dict[str, str]
    ) -> httpx.Response:
        folder = self._folder_or_404(match)
        if isinstance(folder, httpx.Response):
            return folder
        selected = self._selected_files(folder, params)
        if isinstance(selected, httpx.Response):
            return selected
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in selected:
                archive.writestr(file.title, self.uploads[file.uploaded_file_id].content)
        return httpx.Response(
            200, content=buffer.getvalue(), headers={"content-type": "application/zip"}
        )

    # The file part of the most recent request, set by `_handle` before
    # dispatch so the upload handler shares the routing signature.
    _last_multipart: tuple[str, bytes] | None = None


def _json_or_none(content_type: str, content: bytes) -> Any | None:
    if not content or "json" not in content_type:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


def _error(
    status: int, error_code: str, message: str, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"error_code": error_code, "message": message}}, headers=headers
    )


def _chat_body(chat: FakeChat) -> dict[str, Any]:
    body = load_fixture("create_chat_response.json")
    body["data"]["chat"].update(
        {
            "id": chat.id,
            "agent_id": chat.agent_id,
            "title": chat.title,
            "chat_type": chat.chat_type,
            "message_count": len(chat.messages),
        }
    )
    return body


def _folder_json(folder: FakeFolder) -> dict[str, Any]:
    data: dict[str, Any] = load_fixture("drive_create_folder_response.json")["data"]
    data.update({"id": folder.id, "name": folder.name, "user_defined_tags": list(folder.tags)})
    return data


def _file_json(file: FakeFile, *, listing: bool) -> dict[str, Any]:
    """A data source as the attach response or as a listing item renders it.

    The two recorded shapes differ (the listing adds ``_class_id`` and
    ``type``), and the client's ``_files_from`` keys on ``type``.
    """
    data: dict[str, Any]
    if listing:
        data = load_fixture("drive_list_files_response.json")["data"]["results"][0]
    else:
        data = load_fixture("drive_attach_data_source_response.json")["data"]
    data.update({"id": file.id, "title": file.title, "knowledge_base_id": file.folder_id})
    return data


def _frame(type_: str, text: str = "", data: Any = None) -> dict[str, Any]:
    """One SSE payload in the recorded wire shape (``stream_sse_frames.txt``)."""
    return {
        "text": text,
        "extended_text": None,
        "type": type_,
        "subtype": None,
        "data": data,
        "elapsed_ms": None,
    }


def _sse_response(message: FakeMessage) -> httpx.Response:
    """The recorded streaming sequence: metadata, response chunks, end_response, [DONE].

    The reply is split at word boundaries so a caller sees several ``response``
    events, as it would live, rather than one event carrying the whole text.
    """
    frames = [_frame("metadata", data={"message_id": message.id})]
    frames += [
        _frame("response", text=piece) for piece in re.findall(r"\S+\s*|\s+", message.response)
    ]
    frames.append(_frame("end_response"))
    body = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n"
    return httpx.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream; charset=utf-8"}
    )


def _multipart_file(content_type: str, body: bytes) -> tuple[str, bytes] | None:
    """The ``(filename, bytes)`` of the first file part of a multipart body, or None."""
    boundary = re.search(r'boundary="?([^";]+)"?', content_type)
    if boundary is None:
        return None
    delimiter = b"--" + boundary.group(1).encode()
    for part in body.split(delimiter):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--":
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        filename = re.search(rb'filename="([^"]*)"', head)
        if filename:
            return filename.group(1).decode(), data
    return None


_ROUTES: list[tuple[str, re.Pattern[str], _Handler]] = [
    ("POST", re.compile(r"^/agents/(?P<agent>[^/]+)/chats$"), FakeXMagic._create_chat),
    (
        "POST",
        re.compile(r"^/agents/(?P<agent>[^/]+)/chats/(?P<chat>[^/]+)/query$"),
        FakeXMagic._query,
    ),
    (
        "GET",
        re.compile(r"^/agents/(?P<agent>[^/]+)/chats/(?P<chat>[^/]+)/message/(?P<msg>[^/]+)$"),
        FakeXMagic._get_message,
    ),
    (
        "DELETE",
        re.compile(r"^/agents/(?P<agent>[^/]+)/chats/(?P<chat>[^/]+)/message/(?P<msg>[^/]+)$"),
        FakeXMagic._delete_message,
    ),
    ("POST", re.compile(r"^/uploaded-files$"), FakeXMagic._upload),
    ("GET", re.compile(r"^/knowledge-bases$"), FakeXMagic._list_kb),
    ("POST", re.compile(r"^/knowledge-bases$"), FakeXMagic._create_folder),
    ("GET", re.compile(r"^/knowledge-bases/(?P<folder>[^/]+)$"), FakeXMagic._get_folder),
    ("PATCH", re.compile(r"^/knowledge-bases/(?P<folder>[^/]+)$"), FakeXMagic._update_folder),
    ("DELETE", re.compile(r"^/knowledge-bases/(?P<folder>[^/]+)$"), FakeXMagic._delete_folder),
    (
        "POST",
        re.compile(r"^/knowledge-bases/(?P<folder>[^/]+)/data-sources/documents$"),
        FakeXMagic._attach,
    ),
    (
        "DELETE",
        re.compile(r"^/knowledge-bases/(?P<folder>[^/]+)/data-sources$"),
        FakeXMagic._delete_files,
    ),
    (
        "GET",
        re.compile(r"^/knowledge-bases/(?P<folder>[^/]+)/data-sources/actions/download$"),
        FakeXMagic._download,
    ),
]
