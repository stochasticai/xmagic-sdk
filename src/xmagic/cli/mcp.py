"""``xmagic mcp`` — scaffold and run containerized MCP servers."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from xmagic.mcp import scaffold_mcp_server

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command()
def init(
    name: str = typer.Argument(..., help="Project name, e.g. my-tool."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Parent directory."),
) -> None:
    """Scaffold a containerized MCP server for an xMagic custom tool."""
    try:
        target = scaffold_mcp_server(name, directory)
    except (ValueError, FileExistsError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Created {target}[/green]")
    console.print("Next steps:")
    console.print(f"  cd {target}")
    console.print("  docker compose up --build          # MCP at http://localhost:8000/mcp")
    console.print("  cloudflared tunnel --url http://localhost:8000   # public HTTPS for dev")
    console.print("  Register the HTTPS /mcp URL: xMagic -> Custom tools -> Create tool")


@app.command()
def dev(
    path: Path = typer.Argument(Path("."), help="MCP project directory."),
    tunnel: bool = typer.Option(False, "--tunnel", help="Print tunnel instructions."),
) -> None:
    """Run an MCP server project locally (docker compose wrapper). [Phase 2]"""
    console.print("[yellow]`xmagic mcp dev` lands in Phase 2 (see DESIGN.md). For now:[/yellow]")
    console.print(f"  docker compose -f {path / 'compose.yaml'} up --build")
    if tunnel:
        console.print("  cloudflared tunnel --url http://localhost:8000")
