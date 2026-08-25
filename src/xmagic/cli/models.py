"""``xmagic models`` — what you can put after ``-m``.

Reads LiteLLM's catalogue, which is the only model list this SDK has access to.
xMagic publishes none: `model` in an `xmagic:` ref is an agent id, and no
documented endpoint takes or lists a model (DESIGN.md §10.6). So this command
answers the question for every provider except the one whose name is on the tin,
and says so rather than implying a coverage it does not have.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

console = Console()
# Warnings go to stderr so `--json` stdout stays machine-readable.
err_console = Console(stderr=True)
app = typer.Typer(no_args_is_help=True)

_SOURCE_NOTE = (
    "LiteLLM's catalogue — xMagic publishes no model list. Use any ref with `xmagic chat -m <ref>`."
)


def _flag(value: bool | None) -> str:
    # "?" and "no" are different answers: roughly a third of LiteLLM's chat
    # models carry no capability flag, and printing "no" for those would invent
    # a fact about them.
    return {True: "yes", False: "no", None: "[dim]?[/dim]"}[value]


def _cost(value: float | None) -> str:
    return "[dim]—[/dim]" if value is None else f"${value:,.2f}"


def _context(value: int | None) -> str:
    return "[dim]—[/dim]" if value is None else f"{value:,}"


@app.command("list")
def list_models_cmd(
    provider: str = typer.Option(None, "--provider", "-p", help="Exact provider, e.g. groq."),
    search: str = typer.Option(None, "--search", "-s", help="Substring match on the ref."),
    mode: str = typer.Option("chat", "--mode", help="LiteLLM mode, or 'any' for all of them."),
    limit: int = typer.Option(40, "--limit", help="Rows to show. 0 for all."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List models LiteLLM can reach, with their capabilities and prices."""
    from xmagic.providers.catalogue import list_models

    try:
        found = list_models(provider=provider, search=search, mode=None if mode == "any" else mode)
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    if not found:
        console.print("[yellow]No models match.[/yellow] Try `xmagic models providers`.")
        return

    shown = found if limit <= 0 else found[:limit]
    truncated = len(shown) < len(found)

    if as_json:
        console.print_json(
            json.dumps(
                [
                    {
                        "ref": m.ref,
                        "provider": m.provider,
                        "mode": m.mode,
                        "context_window": m.context_window,
                        "input_cost_per_1m": m.input_cost_per_1m,
                        "output_cost_per_1m": m.output_cost_per_1m,
                        "tools": m.tools,
                        "vision": m.vision,
                    }
                    for m in shown
                ]
            )
        )
        if truncated:
            # Not silent: a script that got 40 of 2,390 rows and was told nothing
            # would look like a complete answer.
            err_console.print(
                f"warning: showing {len(shown)} of {len(found)} matches (--limit 0 for all)"
            )
        return

    table = Table()
    # The ref is the payload -- it gets copied into `-m` -- so it wraps rather
    # than ellipsizing in a narrow terminal.
    table.add_column("ref", overflow="fold")
    for column in ("context", "tools", "vision", "$/1M in", "$/1M out"):
        table.add_column(column)
    for m in shown:
        table.add_row(
            m.ref,
            _context(m.context_window),
            _flag(m.tools),
            _flag(m.vision),
            _cost(m.input_cost_per_1m),
            _cost(m.output_cost_per_1m),
        )
    console.print(table)
    if truncated:
        console.print(
            f"[dim]Showing {len(shown)} of {len(found)}. Narrow with --provider/--search, "
            "or --limit 0 for all.[/dim]"
        )
    console.print(f"[dim]{_SOURCE_NOTE}[/dim]")


@app.command("providers")
def list_providers_cmd(
    mode: str = typer.Option("chat", "--mode", help="LiteLLM mode, or 'any' for all of them."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List providers LiteLLM can reach, and how many models each has."""
    from xmagic.providers.catalogue import list_providers

    try:
        found = list_providers(mode=None if mode == "any" else mode)
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    if as_json:
        console.print_json(json.dumps([{"provider": p, "models": n} for p, n in found]))
        return

    table = Table("provider", "models")
    for name, count in found:
        table.add_row(name, str(count))
    console.print(table)
    console.print(f"[dim]{_SOURCE_NOTE} Filter with `xmagic models list -p <provider>`.[/dim]")
