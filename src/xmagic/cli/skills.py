"""``xmagic skills`` — create, validate, and pack Skill archives."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from xmagic.skills import new_skill, pack_skill, validate_skill

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command()
def new(
    name: str = typer.Argument(..., help="Skill name."),
    directory: Path = typer.Option(Path("."), "--dir", "-d"),
    description: str = typer.Option("TODO", "--description"),
) -> None:
    """Scaffold a skill directory with a SKILL.md."""
    try:
        target = new_skill(name, directory, description)
    except FileExistsError:
        console.print(f"[red]{directory / name} already exists[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]Created {target}/SKILL.md[/green]")


@app.command()
def validate(path: Path = typer.Argument(..., help="Skill directory or SKILL.md.")) -> None:
    """Validate SKILL.md frontmatter (requires name + description)."""
    try:
        manifest = validate_skill(path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]OK[/green] name={manifest.name!r} description={manifest.description!r}")


@app.command()
def pack(
    path: Path = typer.Argument(..., help="Skill directory."),
    output: Path = typer.Option(None, "--output", "-o", help="Output zip path."),
) -> None:
    """Validate and zip a skill into an upload-ready archive."""
    try:
        out = pack_skill(path, output)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]Packed {out}[/green]")
    console.print("Upload in xMagic: Sidebar -> Skills -> Upload ZIP (no public API yet).")
