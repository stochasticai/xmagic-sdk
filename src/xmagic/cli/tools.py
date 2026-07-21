"""``xmagic tools`` — custom-tool registration helpers.

xMagic currently documents dashboard-only registration (Custom tools ->
Create tool). This command prints a registration checklist; API-backed
registration will be wired when/if an endpoint is published (DESIGN.md §10).
"""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command()
def register(
    name: str = typer.Option(..., "--name", help="Tool name."),
    url: str = typer.Option(..., "--url", help="Public HTTPS MCP endpoint (…/mcp)."),
    description: str = typer.Option("", "--description"),
) -> None:
    """Print the dashboard registration checklist for a custom tool."""
    if not url.startswith("https://"):
        console.print("[red]xMagic requires a public HTTPS server URL.[/red]")
        raise typer.Exit(1)
    console.print("[bold]Register in the xMagic dashboard[/bold] (no public API yet):")
    console.print("  1. Sidebar -> Custom tools -> Create tool")
    console.print(f"  2. Tool name:   {name}")
    console.print(f"  3. Description: {description or '<add one — shown in Studio>'}")
    console.print(f"  4. Server URL:  {url}")
    console.print("  5. API key:     your TOOL_API_KEY value (rotate regularly)")
    console.print("  6. Attach the tool to a Job in Studio and deploy the Agent")
