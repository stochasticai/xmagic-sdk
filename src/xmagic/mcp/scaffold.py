"""Project generator behind ``xmagic mcp init``.

Generates a containerized MCP server (MCPServer, streamable-HTTP at /mcp) with a
Dockerfile that satisfies xMagic's custom-tool contract: public HTTPS MCP
endpoint, optional API key, structured JSON responses, logging.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

_TEMPLATES = {
    "pyproject.toml.tmpl": "pyproject.toml",
    "requirements.txt.tmpl": "requirements.txt",
    "Dockerfile.tmpl": "Dockerfile",
    "compose.yaml.tmpl": "compose.yaml",
    "README.md.tmpl": "README.md",
    # Root-level entrypoint for xMagic's hosted deployment, which runs
    # ``python /code/mcp_server.py``. It imports the server from src/.
    "mcp_server.py.tmpl": "mcp_server.py",
}

# One list, rendered into both pyproject.toml and requirements.txt so the
# container build and the hosted deployment cannot resolve different versions.
DEPENDENCIES = (
    # Bounded to one major on purpose. An unbounded "mcp>=1.0" is what broke
    # this template once already: mcp 2.0 moved FastMCP to
    # mcp.server.mcpserver.MCPServer, so generated projects resolved to a
    # version whose import did not exist.
    "mcp>=2.0,<3",
    "starlette>=0.37",
    "uvicorn>=0.29",
)


def _module_name(name: str) -> str:
    module = re.sub(r"[^a-z0-9_]", "_", name.lower().replace("-", "_"))
    if not module or module[0].isdigit():
        module = f"tool_{module}"
    return module


def scaffold_mcp_server(name: str, directory: str | Path = ".") -> Path:
    """Create an MCP server project named ``name`` under ``directory``.

    Returns the project path. Raises FileExistsError if it already exists.
    """
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", name):
        raise ValueError(f"Invalid project name '{name}': use letters, digits, '-' and '_' only.")
    module = _module_name(name)
    target = Path(directory) / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")

    templates = resources.files("xmagic.mcp") / "templates"
    ctx = {
        "name": name,
        "module": module,
        "dependencies_toml": "\n".join(f'    "{dep}",' for dep in DEPENDENCIES),
        "dependencies_txt": "\n".join(DEPENDENCIES),
    }

    target.mkdir(parents=True)
    for tmpl, out_name in _TEMPLATES.items():
        content = (templates / tmpl).read_text(encoding="utf-8").format(**ctx)
        (target / out_name).write_text(content, encoding="utf-8")

    pkg_dir = target / "src" / module
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    server = (templates / "server.py.tmpl").read_text(encoding="utf-8").format(**ctx)
    (pkg_dir / "server.py").write_text(server, encoding="utf-8")
    (target / ".env.example").write_text("TOOL_API_KEY=change-me\n", encoding="utf-8")
    (target / ".gitignore").write_text(".env\n__pycache__/\n.venv/\n", encoding="utf-8")
    return target
