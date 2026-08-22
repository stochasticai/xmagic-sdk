"""The authenticated ``xmagic tools --url`` path, over a real socket.

The other half of local tool invocation is covered in
``test_tool_invocation.py``, which drives a server object over MCP's in-memory
transport. That path never constructs an HTTP client, so everything about the
branch real users take -- a URL plus an API key -- went untested until here, and
a real defect survived because of it (issue #32: the branch built an ``httpx``
client for a transport that calls ``.sse()`` on it, which only ``httpx2`` has).

So this serves the server ``xmagic mcp init`` actually generates, middleware and
all, on a loopback port, and drives it through both the client helpers and the
CLI. Slower than in-memory, and worth it: no other test sends a byte over a
socket, and the class of bug above is invisible to every test that does not.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

from xmagic.cli.main import app
from xmagic.errors import XMagicError
from _helpers import import_scaffolded_server
from xmagic.mcp.client import _target, call_tool, list_tools

pytest.importorskip("mcp")
pytest.importorskip("uvicorn")

API_KEY = "correct-horse-battery-staple"
runner = CliRunner()


@pytest.fixture(scope="module")
def authenticated_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A scaffolded server, key-protected, listening on an ephemeral port."""
    import uvicorn

    from xmagic.mcp import scaffold_mcp_server

    # The template reads TOOL_API_KEY at import time and only adds the
    # middleware when it is set, so this has to be in place before the import.
    # monkeypatch is function-scoped; this fixture is not.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TOOL_API_KEY", API_KEY)
        project = scaffold_mcp_server("auth-check", tmp_path_factory.mktemp("scaffold"))
        module = import_scaffolded_server(project, "auth_check")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(module.app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("the test MCP server did not start")

    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()


async def test_list_tools_over_http_with_a_key(authenticated_url: str) -> None:
    tools = await list_tools(authenticated_url, API_KEY)

    assert {t.name for t in tools} == {"ping", "example_lookup"}
    assert set(next(t for t in tools if t.name == "ping").input_schema["properties"]) == {"message"}


async def test_call_tool_over_http_with_a_key(authenticated_url: str) -> None:
    result = await call_tool(authenticated_url, "ping", {"message": "hi"}, API_KEY)

    assert not result.is_error
    assert json.loads(result.text) == {"ok": True, "message": "hi"}


async def test_a_wrong_key_reads_as_an_auth_problem(authenticated_url: str) -> None:
    # The 401 the middleware returns does not survive mcp's error handling as a
    # status code, so the message can only hint -- but it must hint at the key,
    # not surface an SSE content-type complaint from three layers down.
    with pytest.raises(XMagicError) as excinfo:
        await list_tools(authenticated_url, "wrong-key")

    message = str(excinfo.value)
    assert authenticated_url in message
    assert "--api-key" in message


async def test_no_key_at_all_is_rejected(authenticated_url: str) -> None:
    with pytest.raises(XMagicError):
        await list_tools(authenticated_url)


class TestCLI:
    """The same path as a user reaches it: `xmagic tools ... --url --api-key`."""

    def test_list_prints_the_tools(self, authenticated_url: str) -> None:
        result = runner.invoke(
            app, ["tools", "list", "--url", authenticated_url, "--api-key", API_KEY, "--json"]
        )

        assert result.exit_code == 0, result.output
        assert {t["name"] for t in json.loads(result.output)} == {"ping", "example_lookup"}

    def test_call_returns_the_tool_output(self, authenticated_url: str) -> None:
        argv = ["tools", "call", "ping", "--url", authenticated_url, "--api-key", API_KEY]
        result = runner.invoke(app, [*argv, "--arg", "message=from-cli", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(json.loads(result.output)["text"]) == {"ok": True, "message": "from-cli"}

    def test_a_wrong_key_exits_nonzero(self, authenticated_url: str) -> None:
        result = runner.invoke(
            app, ["tools", "list", "--url", authenticated_url, "--api-key", "wrong-key"]
        )

        assert result.exit_code == 1
        assert "--api-key" in result.output


class TestTarget:
    """`_target` decides which HTTP library the transport gets handed.

    A plain unit test, and the one that pins the #28 defect directly: the rest of
    this file would go green again with an `httpx` client for any tool that never
    opens a standalone SSE stream.
    """

    def test_a_url_with_a_key_gets_an_httpx2_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mcp.client import streamable_http

        captured: dict[str, Any] = {}

        def fake_client(url: str, **kwargs: Any) -> str:
            captured.update(url=url, **kwargs)
            return "transport"

        monkeypatch.setattr(streamable_http, "streamable_http_client", fake_client)

        assert _target("https://example.test/mcp", "k") == "transport"
        assert captured["url"] == "https://example.test/mcp"
        # The distribution, not just the duck type: `httpx` also has AsyncClient,
        # and handing one over is exactly the bug this guards.
        assert type(captured["http_client"]).__module__.split(".")[0] == "httpx2"
        assert captured["http_client"].headers["x-api-key"] == "k"
        assert captured["http_client"].headers["authorization"] == "Bearer k"

    def test_a_url_without_a_key_is_passed_through(self) -> None:
        # `Client` builds its own transport from a bare URL; no headers needed.
        assert _target("https://example.test/mcp", None) == "https://example.test/mcp"

    def test_a_server_object_is_passed_through(self) -> None:
        sentinel = object()

        assert _target(sentinel, API_KEY) is sentinel
