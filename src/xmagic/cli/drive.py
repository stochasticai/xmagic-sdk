"""``xmagic drive`` — knowledge-base folders and files."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from xmagic import XMagicClient
from xmagic.errors import XMagicError

console = Console()
app = typer.Typer(no_args_is_help=True)


def _client() -> XMagicClient:
    try:
        return XMagicClient()
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("ls")
def list_folders() -> None:
    """List Drive folders (knowledge bases)."""
    client = _client()
    try:
        folders = client.drive.list_folders()
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    table = Table("id", "name")
    for f in folders:
        table.add_row(f.id, f.name or "")
    console.print(table)


@app.command()
def upload(
    folder_id: str = typer.Argument(...),
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Upload a file into a folder (auto-indexed by xMagic)."""
    client = _client()
    try:
        f = client.drive.upload_file(folder_id, path)
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Uploaded {path.name} -> file id {f.id}[/green]")
