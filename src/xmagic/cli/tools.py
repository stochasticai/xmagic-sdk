"""``xmagic tools`` — develop, exercise, and register custom tools.

``list`` and ``call`` speak MCP straight to a running server, so a tool can be
tested without a tunnel, a dashboard registration, or an agent choosing to
invoke it. ``register`` still prints a checklist: xMagic documents dashboard-only
registration, and API-backed registration lands if an endpoint is published
(DESIGN.md §10).

Grouped here rather than under ``xmagic mcp`` because users reach for this when
they want to *test a tool*, not when they want to speak a protocol (DESIGN.md
§6.1 left the choice open).
"""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.markup import escape

from xmagic.errors import XMagicError

console = Console()
app = typer.Typer(no_args_is_help=True)


def _parse_args(pairs: list[str] | None, json_args: str | None) -> dict:
    """Build tool arguments from repeated ``--arg k=v`` and/or a JSON blob."""
    arguments: dict = {}
    if json_args:
        try:
            loaded = json.loads(json_args)
        except json.JSONDecodeError as e:
            raise typer.BadParameter(f"--json-args is not valid JSON: {e}") from None
        if not isinstance(loaded, dict):
            raise typer.BadParameter("--json-args must be a JSON object.")
        arguments.update(loaded)
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"--arg must be key=value, got '{pair}'.")
        # Let JSON-looking values through as real types, so numbers and booleans
        # reach a typed tool as numbers and booleans rather than strings.
        try:
            arguments[key] = json.loads(value)
        except json.JSONDecodeError:
            arguments[key] = value
    return arguments


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


@app.command("list")
def list_tools_cmd(
    url: str = typer.Option(..., "--url", help="MCP endpoint, e.g. http://localhost:8000/mcp."),
    api_key: str = typer.Option(None, "--api-key", help="Sent as x-api-key and Bearer."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List the tools a running MCP server advertises."""
    from xmagic.mcp.client import list_tools

    try:
        tools = asyncio.run(list_tools(url, api_key))
    except (XMagicError, ImportError) as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from None

    if as_json:
        console.print_json(
            json.dumps(
                [
                    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                    for t in tools
                ]
            )
        )
        return
    if not tools:
        console.print("[yellow]The server advertises no tools.[/yellow]")
        return
    for tool in tools:
        params = ", ".join((tool.input_schema.get("properties") or {}).keys())
        console.print(f"[bold]{escape(tool.name)}[/bold]({escape(params)})")
        if tool.description:
            console.print(f"  [dim]{escape(tool.description.strip().splitlines()[0])}[/dim]")


@app.command("call")
def call_tool_cmd(
    name: str = typer.Argument(..., help="Tool name, as shown by `xmagic tools list`."),
    url: str = typer.Option(..., "--url", help="MCP endpoint, e.g. http://localhost:8000/mcp."),
    arg: list[str] = typer.Option(None, "--arg", "-a", help="key=value. Repeatable."),
    json_args: str = typer.Option(None, "--json-args", help="Arguments as a JSON object."),
    api_key: str = typer.Option(None, "--api-key", help="Sent as x-api-key and Bearer."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Invoke one tool on a running MCP server."""
    from xmagic.mcp.client import call_tool

    arguments = _parse_args(arg, json_args)
    try:
        result = asyncio.run(call_tool(url, name, arguments, api_key))
    except (XMagicError, ImportError) as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from None

    if as_json:
        console.print_json(
            json.dumps(
                {"is_error": result.is_error, "text": result.text, "structured": result.structured}
            )
        )
    else:
        console.print(escape(result.text) if result.text else "[dim](no content)[/dim]")
    # A tool that ran and reported failure is a failed command, so scripts and
    # CI can branch on the exit code instead of parsing output.
    if result.is_error:
        raise typer.Exit(1)
