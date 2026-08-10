"""``xmagic agents`` — list agents, edit temporary config as YAML, and deploy."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from xmagic import XMagicClient
from xmagic.client.agents import config_id_from_temporary
from xmagic.config import Settings
from xmagic.config_codec import json_to_yaml, yaml_to_json
from xmagic.errors import (
    EditorError,
    NotFoundError,
    PermissionDeniedError,
    ServerError,
    XMagicError,
)

console = Console()
app = typer.Typer(invoke_without_command=True, no_args_is_help=False)


def _default_version_name() -> str:
    """Generate a version name matching the frontend's ``dayjs`` format.

    Produces strings like ``"August 6, 2:30:45 PM"``.
    """
    now = datetime.now()
    hour = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    return f"{now.strftime('%B')} {now.day}, {hour}:{now.strftime('%M:%S')} {ampm}"


def _default_editor() -> str:
    """Return the editor command; GUI VS Code users should set ``code --wait``."""
    if visual := os.environ.get("VISUAL"):
        return visual
    if editor := os.environ.get("EDITOR"):
        return editor
    return "notepad.exe" if os.name == "nt" else "nano"


def _edit_file(path: Path) -> None:
    editor = _default_editor()
    command = shlex.split(editor, posix=(os.name != "nt"))
    command.append(str(path))
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError as e:
        raise EditorError(f"Editor executable was not found: {editor}") from e
    if result.returncode != 0:
        raise EditorError(f"Editor exited with status code {result.returncode}")


def _list_agents() -> None:
    with XMagicClient() as client:
        agents = client.agents.list()
    table = Table("name", "id", "role")
    for item in agents:
        table.add_row(item.name or "", item.id, item.role or "")
    console.print(table)


def _ensure_agent_in_current_workspace(client: XMagicClient, agent_id: str) -> None:
    """Ensure the agent belongs to the current workspace."""
    state = client.workspaces.list()
    current_workspace_id = state.current_workspace_id
    if not current_workspace_id:
        raise XMagicError(
            "The current workspace could not be determined; refusing to deploy. Run 'xmagic workspaces' and try again."
        )
    agent = client.agents.get(agent_id)
    if agent.get("organization_id") != current_workspace_id:
        raise XMagicError(
            f"Agent {agent_id} was not found in the current workspace. Switch workspaces with 'xmagic workspaces' before deploying."
        )


@app.callback(invoke_without_command=True)
def agent(ctx: typer.Context) -> None:
    """List agents in the current workspace context."""
    if ctx.invoked_subcommand:
        return
    try:
        _list_agents()
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


@app.command("config")
def config(
    agent_id: str | None = typer.Option(
        None, "--agent", help="Agent id. Falls back to configured default agent."
    ),
    compose: str | None = typer.Option(
        None,
        "--composer",
        "-C",
        help="Send a prompt to Composer to update the agent configuration.",
    ),
) -> None:
    """
    Edit the agent temporary config in YAML and push updates to backend.
    \n\n
    Environment Variables:\n
    EDITOR    Path or command for text editor to use.\n
            Note for VS Code / GUI editor users: Non-blocking editors return\n
            immediately. Set EDITOR="code --wait" (or pass -w) so the command\n
            waits for you to save and close the file before continuing.
    """
    settings = Settings.load()
    target_agent_id = agent_id or settings.default_agent_id
    if not target_agent_id:
        raise typer.BadParameter(
            "Provide --agent or set default_agent_id with xmagic configure --agent."
        )
    if compose is not None:
        from xmagic.cli.chat import run_chat

        run_chat(compose, None, target_agent_id, [], "configuration", True)
        return

    temp_path: Path | None = None
    try:
        with XMagicClient() as client:
            config_json = client.agents.export_temporary_config(target_agent_id)
            original_yaml = json_to_yaml(config_json)
            with tempfile.NamedTemporaryFile(
                mode="w",
                prefix=f"xmagic-agent-{target_agent_id}-",
                suffix=".yaml",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(original_yaml)
                temp_path = Path(tmp.name)
            _edit_file(temp_path)
            edited_yaml = temp_path.read_text(encoding="utf-8")
            if edited_yaml == original_yaml:
                console.print(
                    "[yellow]No changes detected. Temporary config was not updated.[/yellow]"
                )
                return
            client.agents.update_temporary_config(target_agent_id, yaml_to_json(edited_yaml))
            console.print(f"[green]Updated temporary config for agent {target_agent_id}.[/green]")
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


@app.command("deploy")
def deploy(
    agent_id: str | None = typer.Option(
        None, "--agent", help="Agent id. Falls back to configured default agent."
    ),
    version: str | None = typer.Option(
        None, "--version", help="Version name. Defaults to current date and time."
    ),
    phone_id: str | None = typer.Option(
        None, "--phone", help="Phone id to attach without prompting."
    ),
    no_phone: bool = typer.Option(
        False, "--no-phone", help="Do not list or attach a phone number."
    ),
) -> None:
    """Save the current temporary config as a named version and deploy it."""
    settings = Settings.load()
    target_agent_id = agent_id or settings.default_agent_id
    if not target_agent_id:
        raise typer.BadParameter(
            "Provide --agent or set default_agent_id with xmagic configure --agent."
        )
    if phone_id and no_phone:
        raise typer.BadParameter("Use either --phone or --no-phone, not both.")
    version_name = version or _default_version_name()

    try:
        with XMagicClient() as client:
            _ensure_agent_in_current_workspace(client, target_agent_id)
            temp = client.agents.get_temporary_config(target_agent_id)
            temp_config_id = config_id_from_temporary(temp)
            selected_phone_id: str | None = None
            selected_subagent_id: str | None = None
            phones = []
            if not no_phone:
                try:
                    phones = client.phones.list()
                except (NotFoundError, PermissionDeniedError, ServerError) as e:
                    console.print(f"[yellow]Phone numbers unavailable ({e}); skipping.[/yellow]")
            if phone_id:
                if not any(phone.id == phone_id for phone in phones):
                    raise XMagicError(f"Phone {phone_id} was not found in the organisation.")
                selected_phone_id = phone_id
            elif phones:
                table = Table("", "phone number", "currently attached to")
                for i, phone in enumerate(phones, start=1):
                    attached = phone.persona_id_associated_to or "—"
                    if phone.subagent_id_associated_to:
                        attached = f"{attached} / subagent {phone.subagent_id_associated_to}"
                    table.add_row(str(i), phone.phone_number, attached)
                console.print(table)
                try:
                    choice = int(
                        typer.prompt(
                            "Attach a phone number? Enter number from table (0 to skip)",
                            default="0",
                        )
                    )
                except (ValueError, typer.Abort, EOFError):
                    choice = 0
                if 1 <= choice <= len(phones):
                    selected_phone_id = phones[choice - 1].id
                    try:
                        subagents = client.agents.list_subagents(target_agent_id, temp_config_id)
                    except XMagicError:
                        subagents = []
                    if subagents:
                        sub_table = Table("", "subagent")
                        sub_table.add_row("0", "All subagents")
                        for i, subagent in enumerate(subagents, start=1):
                            sub_table.add_row(str(i), subagent.name or subagent.id)
                        console.print(sub_table)
                        try:
                            sub_choice = int(
                                typer.prompt(
                                    "Select a subagent to manage incoming calls (0 = All subagents)",
                                    default="0",
                                )
                            )
                        except (ValueError, typer.Abort, EOFError):
                            sub_choice = 0
                        if 1 <= sub_choice <= len(subagents):
                            subagent = subagents[sub_choice - 1]
                            selected_subagent_id = (
                                subagent.id_shared_between_versions or subagent.id
                            )

            if selected_phone_id:
                client.phones.associate(selected_phone_id, target_agent_id, selected_subagent_id)
                console.print("[green]Phone number associated.[/green]")
            saved = client.agents.save_config(target_agent_id, version_name)
            client.agents.deploy_config(target_agent_id, saved.id)
        console.print(
            f"[green]Deployed version '{version_name}' for agent {target_agent_id}.[/green]"
        )
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
