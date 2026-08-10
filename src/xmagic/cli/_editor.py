"""Shared temporary-file editor helpers for interactive CLI commands."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def default_editor() -> str:
    """Choose the editor from ``VISUAL``, ``EDITOR``, or the OS default."""
    if visual := os.environ.get("VISUAL"):
        return visual
    if editor := os.environ.get("EDITOR"):
        return editor
    return "notepad.exe" if os.name == "nt" else "nano"


def edit_file(path: Path) -> None:
    """Open ``path`` in the configured editor and wait for it to exit."""
    editor = default_editor()
    command = shlex.split(editor, posix=(os.name != "nt"))
    command.append(str(path))
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError as error:
        raise RuntimeError(f"Editor executable was not found: {editor}") from error
    if result.returncode != 0:
        raise RuntimeError(f"Editor exited with status code {result.returncode}")
