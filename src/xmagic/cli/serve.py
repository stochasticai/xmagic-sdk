"""``xmagic serve`` — local web app (reverse proxy + fallback UI)."""

from __future__ import annotations

import typer
from rich.console import Console

from xmagic.webapp.proxy import DEFAULT_PORT, DEFAULT_UPSTREAM, run_proxy

console = Console()


def serve(
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p"),
    upstream: str = typer.Option(
        DEFAULT_UPSTREAM,
        "--upstream",
        help="Upstream xMagic web app (point at your self-hosted instance if any).",
    ),
) -> None:
    """Run the xMagic web app locally via a reverse proxy."""
    try:
        run_proxy(port=port, upstream=upstream)
    except (ImportError, NotImplementedError) as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1) from None
