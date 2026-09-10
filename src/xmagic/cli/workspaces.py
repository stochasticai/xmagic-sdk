"""``xmagic workspaces`` — list or switch accessible workspaces."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from xmagic import XMagicClient
from xmagic.cli._output import fail, print_json
from xmagic.client.models import Workspace
from xmagic.errors import XMagicError

console = Console()


def _matching_name(workspaces: list[Workspace], name: str) -> list[Workspace]:
    needle = name.strip().casefold()
    return [workspace for workspace in workspaces if workspace.name.strip().casefold() == needle]


def workspace(
    name: str | None = typer.Argument(None, help="Workspace name to switch to."),
    workspace_id: str | None = typer.Option(None, "--id", help="Workspace id to switch to."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List accessible workspaces, or switch current workspace."""
    if workspace_id and name:
        raise typer.BadParameter("Use either <workspace_name> or --id, not both.")

    try:
        with XMagicClient() as client:
            state = client.workspaces.list()

            if not workspace_id and not name:
                if as_json:
                    print_json(state.model_dump(mode="json"))
                    return
                table = Table("current", "name", "id", "access")
                for item in state.workspaces:
                    marker = "*" if item.id == state.current_workspace_id else ""
                    table.add_row(marker, item.name, item.id, item.role or "")
                console.print(table)
                return

            target_id = workspace_id
            if name:
                matches = _matching_name(state.workspaces, name)
                if not matches:
                    fail(f"No workspace found with name '{name}'.")
                if len(matches) > 1:
                    ids = ", ".join(match.id for match in matches)
                    fail(f"Workspace name '{name}' is ambiguous. Use an id instead: {ids}")
                target_id = matches[0].id

            assert target_id is not None
            updated = client.workspaces.switch(target_id)
            if as_json:
                print_json(updated.model_dump(mode="json"))
                return
            console.print(f"[green]Switched current workspace to {target_id}.[/green]")
            if updated.current_workspace_id and updated.current_workspace_id != target_id:
                console.print(
                    f"[yellow]Backend current workspace is {updated.current_workspace_id} after switch.[/yellow]"
                )
    except XMagicError as e:
        fail(str(e))
