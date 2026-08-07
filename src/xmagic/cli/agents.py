"""``xmagic agents`` — list agents, edit temporary config as YAML, and deploy."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from xmagic import XMagicClient
from xmagic.client.models import ChatType
from xmagic.config import Settings
from xmagic.config_codec import json_to_yaml, yaml_to_json
from xmagic.errors import XMagicError

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


def _temp_config_id(payload: dict[str, Any]) -> str:
    """Extract the config id from a temporary config payload dict."""
    for key in ("id", "_id", "config_id", "configuration_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("Temporary config id not found in response")


def _default_editor() -> str:
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
        raise RuntimeError(f"Editor executable was not found: {editor}") from e
    if result.returncode != 0:
        raise RuntimeError(f"Editor exited with status code {result.returncode}")


def _list_agents() -> None:
    with XMagicClient() as client:
        agents = client.agents.list()
    table = Table("name", "id", "role")
    for item in agents:
        table.add_row(item.name or "", item.id, item.role or "")
    console.print(table)


def _ensure_agent_in_current_workspace(client: XMagicClient, agent_id: str) -> None:
    """Reject deployment and identify the workspace owning an out-of-scope agent."""
    state = client.workspaces.list()
    current_workspace_id = state.current_workspace_id
    if any(agent.id == agent_id for agent in client.agents.list()):
        return

    found_workspace = None
    try:
        for workspace in state.workspaces:
            if workspace.id == current_workspace_id:
                continue
            client.workspaces.switch(workspace.id)
            if any(agent.id == agent_id for agent in client.agents.list()):
                found_workspace = workspace
                break
    finally:
        if current_workspace_id:
            client.workspaces.switch(current_workspace_id)

    if found_workspace:
        raise ValueError(
            f"Agent {agent_id} belongs to workspace '{found_workspace.name}' "
            f"({found_workspace.id}). Switch to that workspace with "
            f"'xmagic workspaces {found_workspace.id}' before deploying."
        )
    raise ValueError(f"Agent {agent_id} was not found in any accessible workspace.")


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
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id. Falls back to configured default agent."),
    compose: str | None = typer.Option(None, "--composer", "-C", help="Send a prompt to Composer to update the agent configuration."),
) -> None:
    """Edit the agent temporary config in YAML and push updates to backend."""
    settings = Settings.load()
    target_agent_id = agent_id or settings.default_agent_id
    if not target_agent_id:
        raise typer.BadParameter("Provide --agent or set default_agent_id with xmagic configure --agent.")
    if compose is not None:
        from xmagic.cli.chat import chat as _chat

        _chat(prompt=compose, agent=target_agent_id, chat_type=ChatType.CONFIGURATION, stream=True, model=None, file=[])
        return

    temp_path: Path | None = None
    try:
        with XMagicClient() as client:
            config_json = client.agents.export_temporary_config(target_agent_id)
            original_yaml = json_to_yaml(config_json)
            with tempfile.NamedTemporaryFile(mode="w", prefix=f"xmagic-agent-{target_agent_id}-", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
                tmp.write(original_yaml)
                temp_path = Path(tmp.name)
            _edit_file(temp_path)
            edited_yaml = temp_path.read_text(encoding="utf-8")
            if edited_yaml == original_yaml:
                console.print("[yellow]No changes detected. Temporary config was not updated.[/yellow]")
                return
            client.agents.update_temporary_config(target_agent_id, yaml_to_json(edited_yaml))
            console.print(f"[green]Updated temporary config for agent {target_agent_id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


@app.command("deploy")
def deploy(
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id. Falls back to configured default agent."),
    version: str | None = typer.Option(None, "--version", help="Version name. Defaults to current date and time."),
) -> None:
    """Save the current temporary config as a named version and deploy it."""
    settings = Settings.load()
    target_agent_id = agent_id or settings.default_agent_id
    if not target_agent_id:
        raise typer.BadParameter("Provide --agent or set default_agent_id with xmagic configure --agent.")
    version_name = version or _default_version_name()

    try:
        with XMagicClient() as client:
            _ensure_agent_in_current_workspace(client, target_agent_id)
            temp = client.agents.get_temporary_config(target_agent_id)
            temp_config_id = _temp_config_id(temp)
            selected_phone_id: str | None = None
            selected_subagent_id: str | None = None
            try:
                phones = client.phones.list()
            except XMagicError:
                phones = []

            if phones:
                phone_table = Table("", "phone number", "currently attached to")
                for i, phone in enumerate(phones, start=1):
                    attached = phone.persona_id_associated_to or "—"
                    if phone.subagent_id_associated_to:
                        attached = f"{attached} / subagent {phone.subagent_id_associated_to}"
                    phone_table.add_row(str(i), phone.phone_number, attached)
                console.print(phone_table)
                try:
                    choice = int(typer.prompt("Attach a phone number? Enter number from table (0 to skip)", default="0"))
                except ValueError:
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
                            sub_choice = int(typer.prompt("Select a subagent to manage incoming calls (0 = All subagents)", default="0"))
                        except ValueError:
                            sub_choice = 0
                        if 1 <= sub_choice <= len(subagents):
                            subagent = subagents[sub_choice - 1]
                            selected_subagent_id = subagent.id_shared_between_versions or subagent.id

            if selected_phone_id:
                client.phones.associate(selected_phone_id, target_agent_id, selected_subagent_id)
                console.print("[green]Phone number associated.[/green]")
            saved = client.agents.save_config(target_agent_id, version_name)
            client.agents.deploy_config(target_agent_id, saved.id)
        console.print(f"[green]Deployed version '{version_name}' for agent {target_agent_id}.[/green]")
    except (XMagicError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None