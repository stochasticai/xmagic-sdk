"""Shared test helpers.

Not a test module (pytest collects `test_*.py`), so it can be imported by the
files that need it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def import_scaffolded_server(project: Path, module_name: str) -> ModuleType:
    """Import the ``server.py`` that ``xmagic mcp init`` rendered.

    Importing rather than compiling is the point: `py_compile` only parses, and
    an import that no longer resolves is exactly how
    `from mcp.server.fastmcp import FastMCP` survived in the template after mcp
    2.0 moved that class -- generating projects that compiled and could not
    start.
    """
    path = project / "src" / module_name / "server.py"
    spec = importlib.util.spec_from_file_location(f"scaffolded_{module_name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution so anything in the template that looks itself
    # up by module name resolves the way it would in the generated project.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
