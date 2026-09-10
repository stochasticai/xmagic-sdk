"""Output for scripts: JSON on stdout, everything else on stderr.

Every command that produces data takes ``--json``. Under it, stdout carries one
JSON document and nothing else -- no table, no dim footnote, no "uploaded x"
progress line -- so ``xmagic ... --json | jq`` works without cleaning up first.
Errors go to stderr regardless of the flag, with the exit code carrying the
verdict, which is what a script branches on.

JSON is written with :mod:`json`, not Rich's ``print_json``: Rich highlights and
re-indents, and its console is bound to a terminal width. A script should get
the bytes :func:`json.dumps` produced.
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

err_console = Console(stderr=True)


def print_json(data: Any) -> None:
    """One JSON document on stdout, indented for humans, valid for machines."""
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def note(message: str) -> None:
    """A progress or context line that must not land in a piped stdout."""
    err_console.print(f"[dim]{escape(message)}[/dim]")


def fail(message: str, hint: str | None = None) -> NoReturn:
    """Report an error on stderr and exit 1.

    ``escape``, because error text is data: without it Rich reads bracketed
    content as markup and silently drops it.
    """
    err_console.print(f"[red]{escape(message)}[/red]")
    if hint:
        err_console.print(f"[yellow]Hint: {escape(hint)}[/yellow]")
    raise typer.Exit(1)
