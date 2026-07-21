"""``xmagic`` CLI entry point.

Command groups:

- xmagic configure      interactive setup
- xmagic chat           talk to an agent or any provider:model
- xmagic mcp            scaffold/run MCP servers for custom tools
- xmagic skills         new / validate / pack skill archives
- xmagic tools          custom-tool registration helpers
- xmagic drive          knowledge-base folders and files
- xmagic serve          local web app
"""

from __future__ import annotations

import typer
from rich.console import Console

from xmagic import __version__
from xmagic.cli import chat, configure, drive, mcp, serve, skills, tools

console = Console()

app = typer.Typer(
    name="xmagic",
    help="CLI for xMagic, Stochastic's AI agent platform.",
    no_args_is_help=True,
)

app.command("configure")(configure.configure)
app.command("chat")(chat.chat)
app.command("serve")(serve.serve)
app.add_typer(mcp.app, name="mcp", help="Scaffold and run MCP servers for custom tools.")
app.add_typer(skills.app, name="skills", help="Create, validate, and pack Skills.")
app.add_typer(tools.app, name="tools", help="Custom-tool registration helpers.")
app.add_typer(drive.app, name="drive", help="Knowledge-base (Drive) operations.")


@app.command()
def version() -> None:
    """Print the xmagic-sdk version."""
    console.print(f"xmagic-sdk {__version__}")


if __name__ == "__main__":
    app()
