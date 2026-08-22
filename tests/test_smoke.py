"""Smoke tests: imports, model refs, skills packaging, MCP scaffold."""

from pathlib import Path
from types import ModuleType

import pytest
from _helpers import import_scaffolded_server


def test_imports() -> None:
    import xmagic

    assert xmagic.__version__


def test_model_ref_parsing() -> None:
    from xmagic.providers import ModelRef

    ref = ModelRef.parse("anthropic:claude-sonnet-4-5")
    assert (ref.provider, ref.model) == ("anthropic", "claude-sonnet-4-5")
    assert ModelRef.parse("agent123").provider == "xmagic"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from xmagic import XMagicClient
    from xmagic.errors import ConfigurationError

    monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
    with pytest.raises(ConfigurationError):
        XMagicClient()


def test_skill_roundtrip(tmp_path: Path) -> None:
    from xmagic.skills import new_skill, pack_skill, validate_skill

    skill_dir = new_skill("demo-skill", tmp_path, description="test skill")
    manifest = validate_skill(skill_dir)
    assert manifest.name == "demo-skill"
    zip_path = pack_skill(skill_dir)
    assert zip_path.exists() and zip_path.suffix == ".zip"


def test_mcp_scaffold(tmp_path: Path) -> None:
    from xmagic.mcp import scaffold_mcp_server

    project = scaffold_mcp_server("my-tool", tmp_path)
    for expected in ("Dockerfile", "compose.yaml", "pyproject.toml", "README.md"):
        assert (project / expected).is_file()
    server = project / "src" / "my_tool" / "server.py"
    assert server.is_file()
    content = server.read_text()
    assert "MCPServer" in content and "streamable_http_app" in content
    assert "{name}" not in content  # template fully rendered


def test_mcp_scaffold_rejects_bad_names(tmp_path: Path) -> None:
    from xmagic.mcp import scaffold_mcp_server

    with pytest.raises(ValueError):
        scaffold_mcp_server("../evil", tmp_path)


def _import_generated_server(tmp_path: Path, name: str) -> tuple[ModuleType, Path]:
    """Scaffold a project and import the server it rendered."""
    from xmagic.mcp import scaffold_mcp_server

    module_name = name.replace("-", "_")
    project = scaffold_mcp_server(name, tmp_path)
    module = import_scaffolded_server(project, module_name)
    return module, project / "src" / module_name / "server.py"


def test_mcp_generated_server_imports_and_enforces_auth(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    module, path = _import_generated_server(tmp_path, "import-check")

    content = path.read_text()
    assert "ApiKeyMiddleware" in content
    assert "TOOL_API_KEY" in content
    assert "{{" not in content  # all escapes rendered
    # Mounted where the generated README tells users to register the tool.
    assert "/mcp" in [getattr(route, "path", None) for route in module.app.routes]


async def test_mcp_generated_server_answers_a_real_tool_call(tmp_path: Path) -> None:
    """Drive the generated server over MCP, in-process.

    `Client` accepts a server instance and speaks the protocol over an in-memory
    transport, so this exercises the real request path -- no container, no port,
    no tunnel. It is the check that would have caught the mcp 2.0 break.
    """
    pytest.importorskip("mcp")
    import json

    from mcp import Client
    from mcp.types import TextContent

    module, _ = _import_generated_server(tmp_path, "roundtrip-check")
    async with Client(module.server) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {"ping", "example_lookup"}
        result = await client.call_tool("ping", {"message": "hello"})

    # Narrowed rather than assumed: `content` is a union of five block types
    # and only one of them carries `.text`.
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert json.loads(block.text) == {"ok": True, "message": "hello"}


def test_mcp_generated_dockerfile_installs_deps_before_src(tmp_path: Path) -> None:
    from xmagic.mcp import scaffold_mcp_server

    project = scaffold_mcp_server("docker-check", tmp_path)
    dockerfile = (project / "Dockerfile").read_text()
    # deps-only install (installing "." before COPY src/ would fail the build)
    assert "-r pyproject.toml" in dockerfile
    assert "socket.create_connection" in dockerfile  # healthcheck is a TCP probe


def test_cli_version_and_chat_requires_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from xmagic.cli.main import app

    monkeypatch.delenv("XMAGIC_API_KEY", raising=False)
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
    runner = CliRunner()

    assert runner.invoke(app, ["version"]).exit_code == 0
    # chat with no --model/--agent/default agent must fail with usage error
    assert runner.invoke(app, ["chat", "hi"]).exit_code != 0


def test_cli_chat_model_without_colon_defaults_to_xmagic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-m agent123` (no colon) must resolve to xmagic provider with a non-empty model."""
    from xmagic.providers import ModelRef

    ref = ModelRef.parse("agent123")
    assert ref.provider == "xmagic"
    assert ref.model == "agent123"  # regression: was '' via ref.partition(':')[2]
