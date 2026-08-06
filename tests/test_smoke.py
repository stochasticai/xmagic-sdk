"""Smoke tests: imports, model refs, skills packaging, MCP scaffold."""

from pathlib import Path

import pytest


def test_imports():
    import xmagic

    assert xmagic.__version__


def test_model_ref_parsing():
    from xmagic.providers import ModelRef

    ref = ModelRef.parse("anthropic:claude-sonnet-4-5")
    assert (ref.provider, ref.model) == ("anthropic", "claude-sonnet-4-5")
    assert ModelRef.parse("agent123").provider == "xmagic"


def test_missing_api_key_raises(monkeypatch, tmp_path):
    from xmagic import XMagicClient
    from xmagic.errors import ConfigurationError

    monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
    with pytest.raises(ConfigurationError):
        XMagicClient()


def test_skill_roundtrip(tmp_path: Path):
    from xmagic.skills import new_skill, pack_skill, validate_skill

    skill_dir = new_skill("demo-skill", tmp_path, description="test skill")
    manifest = validate_skill(skill_dir)
    assert manifest.name == "demo-skill"
    zip_path = pack_skill(skill_dir)
    assert zip_path.exists() and zip_path.suffix == ".zip"


def test_mcp_scaffold(tmp_path: Path):
    from xmagic.mcp import scaffold_mcp_server

    project = scaffold_mcp_server("my-tool", tmp_path)
    for expected in ("Dockerfile", "compose.yaml", "pyproject.toml", "README.md"):
        assert (project / expected).is_file()
    server = project / "src" / "my_tool" / "server.py"
    assert server.is_file()
    content = server.read_text()
    assert "MCPServer" in content and "streamable_http_app" in content
    assert "{name}" not in content  # template fully rendered


def test_mcp_scaffold_rejects_bad_names(tmp_path: Path):
    from xmagic.mcp import scaffold_mcp_server

    with pytest.raises(ValueError):
        scaffold_mcp_server("../evil", tmp_path)


def _import_generated_server(tmp_path: Path, name: str):
    """Scaffold a project and actually import its rendered server.

    This used to be a `py_compile` check, which only parses. It cannot catch an
    import that no longer resolves -- which is precisely how
    `from mcp.server.fastmcp import FastMCP` survived in the template after mcp
    2.0 moved that class to `mcp.server.mcpserver.MCPServer`. The generated
    project's dependency was an unbounded `mcp>=1.0`, so `xmagic mcp init`
    produced projects that compiled and could not start.
    """
    import importlib.util

    from xmagic.mcp import scaffold_mcp_server

    module_name = name.replace("-", "_")
    project = scaffold_mcp_server(name, tmp_path)
    path = project / "src" / module_name / "server.py"
    spec = importlib.util.spec_from_file_location(f"generated_{module_name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def test_mcp_generated_server_imports_and_enforces_auth(tmp_path: Path):
    pytest.importorskip("mcp")
    module, path = _import_generated_server(tmp_path, "import-check")

    content = path.read_text()
    assert "ApiKeyMiddleware" in content
    assert "TOOL_API_KEY" in content
    assert "{{" not in content  # all escapes rendered
    # Mounted where the generated README tells users to register the tool.
    assert "/mcp" in [getattr(route, "path", None) for route in module.app.routes]


async def test_mcp_generated_server_answers_a_real_tool_call(tmp_path: Path):
    """Drive the generated server over MCP, in-process.

    `Client` accepts a server instance and speaks the protocol over an in-memory
    transport, so this exercises the real request path -- no container, no port,
    no tunnel. It is the check that would have caught the mcp 2.0 break.
    """
    pytest.importorskip("mcp")
    import json

    from mcp import Client

    module, _ = _import_generated_server(tmp_path, "roundtrip-check")
    async with Client(module.server) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {"ping", "example_lookup"}
        result = await client.call_tool("ping", {"message": "hello"})

    assert json.loads(result.content[0].text) == {"ok": True, "message": "hello"}


def test_mcp_generated_dockerfile_installs_deps_before_src(tmp_path: Path):
    from xmagic.mcp import scaffold_mcp_server

    project = scaffold_mcp_server("docker-check", tmp_path)
    dockerfile = (project / "Dockerfile").read_text()
    # deps-only install (installing "." before COPY src/ would fail the build)
    assert "-r pyproject.toml" in dockerfile
    assert "socket.create_connection" in dockerfile  # healthcheck is a TCP probe


def test_cli_version_and_chat_requires_target(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from xmagic.cli.main import app

    monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
    runner = CliRunner()

    assert runner.invoke(app, ["version"]).exit_code == 0
    # chat with no --model/--agent/default agent must fail with usage error
    assert runner.invoke(app, ["chat", "hi"]).exit_code != 0


def test_cli_chat_model_without_colon_defaults_to_xmagic(tmp_path: Path, monkeypatch):
    """`-m agent123` (no colon) must resolve to xmagic provider with a non-empty model."""
    from xmagic.providers import ModelRef

    ref = ModelRef.parse("agent123")
    assert ref.provider == "xmagic"
    assert ref.model == "agent123"  # regression: was '' via ref.partition(':')[2]
