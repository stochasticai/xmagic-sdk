"""Local tool invocation: the MCP client helpers and the `xmagic tools` commands.

`Client` accepts a server instance over an in-memory transport, so these drive a
real MCP request path without a container, a port, or a tunnel -- including a
server produced by `xmagic mcp init`, which is how the scaffold finally gets an
integration test rather than a syntax check.
"""

from __future__ import annotations

import json

import pytest

from xmagic.cli.tools import _parse_args
from xmagic.errors import XMagicError
from xmagic.mcp.client import call_tool, list_tools

pytest.importorskip("mcp")


@pytest.fixture
def server():
    from mcp.server.mcpserver import MCPServer

    srv = MCPServer("fixture")

    @srv.tool()
    def greet(name: str, excited: bool = False) -> dict:
        """Say hello to someone."""
        return {"greeting": f"hello {name}", "excited": excited}

    return srv


async def test_list_tools_reports_names_and_schema(server) -> None:
    tools = await list_tools(server)

    assert [t.name for t in tools] == ["greet"]
    assert tools[0].description.startswith("Say hello")
    assert set(tools[0].input_schema["properties"]) == {"name", "excited"}


async def test_call_tool_returns_the_tool_output(server) -> None:
    result = await call_tool(server, "greet", {"name": "world", "excited": True})

    assert not result.is_error
    assert json.loads(result.text) == {"greeting": "hello world", "excited": True}


async def test_unreachable_server_raises_a_readable_error() -> None:
    # A tool that simply is not running is the most common outcome while
    # developing one. It must read as that, not as an anyio task-group traceback.
    with pytest.raises(XMagicError) as excinfo:
        await list_tools("http://127.0.0.1:1/mcp")

    message = str(excinfo.value)
    assert "http://127.0.0.1:1/mcp" in message
    assert "failed" in message


async def test_scaffolded_server_answers_its_own_ping(tmp_path) -> None:
    """`xmagic mcp init` output, driven over MCP end to end."""
    import importlib.util

    from xmagic.mcp import scaffold_mcp_server

    project = scaffold_mcp_server("invoke-check", tmp_path)
    path = project / "src" / "invoke_check" / "server.py"
    spec = importlib.util.spec_from_file_location("invoke_check_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tools = await list_tools(module.server)
    assert {t.name for t in tools} == {"ping", "example_lookup"}

    result = await call_tool(module.server, "ping", {"message": "hi"})
    assert json.loads(result.text) == {"ok": True, "message": "hi"}


class TestArgumentParsing:
    """`--arg k=v` should reach a typed tool with types intact."""

    def test_bare_values_stay_strings(self) -> None:
        assert _parse_args(["name=world"], None) == {"name": "world"}

    def test_json_looking_values_are_coerced(self) -> None:
        # Otherwise `--arg count=3` sends "3" and a tool typed `int` rejects it.
        assert _parse_args(["count=3", "on=true", "ratio=1.5"], None) == {
            "count": 3,
            "on": True,
            "ratio": 1.5,
        }

    def test_json_args_and_arg_merge_with_arg_winning(self) -> None:
        assert _parse_args(["a=2"], '{"a": 1, "b": 9}') == {"a": 2, "b": 9}

    def test_missing_equals_is_rejected(self) -> None:
        import typer

        with pytest.raises(typer.BadParameter):
            _parse_args(["oops"], None)

    def test_non_object_json_is_rejected(self) -> None:
        import typer

        with pytest.raises(typer.BadParameter):
            _parse_args(None, "[1, 2]")
