"""``xmagic worklists`` — list, edit, and run background tasks."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from xmagic import XMagicClient
from xmagic.cli._editor import edit_file as _edit_file
from xmagic.cli._output import fail, note, print_json
from xmagic.client.models import WorklistTask, WorklistTaskPage, WorklistTaskStatus
from xmagic.config import Settings
from xmagic.errors import XMagicAPIError, XMagicError
from xmagic.worklist_codec import (
    CREATE_TEMPLATE,
    prefill_input_files,
    schedule_to_edit_yaml,
    task_to_edit_yaml,
    yaml_to_create_payload,
    yaml_to_schedule_update_payload,
    yaml_to_update_payload,
)

console = Console()
app = typer.Typer(invoke_without_command=True, no_args_is_help=False)
schedules_app = typer.Typer(no_args_is_help=True)
app.add_typer(schedules_app, name="schedules", help="Manage recurring worklist schedules.")

_ERROR_HINTS = {
    "WORKLIST_TASK_ALREADY_EXECUTED": "Only pending or needs-review tasks can be edited.",
    "WORKLIST_TASK_ALREADY_IN_PROGRESS": "The task is already running.",
    "WORKLIST_TASK_NEEDS_REVIEW": "Resolve the task's review state before triggering it.",
    "WORKLIST_TASK_NOT_RERUNNABLE": "Only completed, failed, or cancelled tasks can be rerun.",
    "WORKLIST_TASK_NOT_ARCHIVABLE": "Archive a completed, failed, or cancelled task.",
    "WORKLIST_TASK_NOT_STOPPABLE": "Only an in-progress task can be cancelled.",
    "WORKLIST_SCHEDULE_INACTIVE": "The schedule has been deactivated and cannot be edited.",
    "WORKLIST_SCHEDULE_ALREADY_PAUSED": "The schedule is already paused.",
    "WORKLIST_SCHEDULE_NOT_PAUSED": "The schedule is not paused.",
    "WORKLIST_RECURRENCE_END_CONDITIONS_MET": "The recurrence has no remaining run dates.",
}


INPUTS_FOLDER = "worklist-inputs"

_INPUT_OPTION = typer.Option(
    None,
    "--input",
    "-i",
    exists=True,
    dir_okay=False,
    help="Local file to upload as an input; repeatable. Uploaded when you save.",
)
_FOLDER_OPTION = typer.Option(
    None,
    "--folder",
    help=(
        "Id of the Drive folder to upload inputs into "
        f"(default: a folder named '{INPUTS_FOLDER}', created if missing)."
    ),
)


def _inputs_folder(client: XMagicClient, folder_id: str | None) -> str:
    """Where inputs land: the id ``--folder`` gives, else a folder named
    ``worklist-inputs``, found by name across the whole listing or created once."""
    if folder_id:
        return folder_id
    for folder in client.drive.list_folders():
        if folder.name == INPUTS_FOLDER:
            return folder.id
    created = client.drive.create_folder(INPUTS_FOLDER)
    note(f"Created Drive folder {INPUTS_FOLDER} ({created.id}) for worklist inputs.")
    return created.id


def _resolve_input_files(
    client: XMagicClient,
    payload: dict[str, Any],
    folder_id: str | None,
    base: list[str],
) -> None:
    """Upload the payload's ``input_files`` and append their storage paths.

    ``input_files`` is a CLI-side key: the API takes ``input_s3_file_paths``
    only, so the local paths are uploaded here, attached to a Drive folder,
    and the resulting paths appended to whatever ``input_s3_file_paths`` the
    payload carries (or ``base``, the task's current list, when it does not).

    One file at a time, each reported as it lands: a failure part-way through
    then says which files are already in the folder, so the user can reuse or
    delete them rather than guess.
    """
    files = [Path(p) for p in payload.pop("input_files", [])]
    if not files:
        return
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise ValueError(f"input file not found: {', '.join(missing)}")
    target = _inputs_folder(client, folder_id)
    uploaded: list[str] = []
    for local in files:
        (remote,) = client.worklists.upload_inputs(target, [local])
        note(f"Uploaded {local.name} -> {remote}")
        uploaded.append(remote)
    payload["input_s3_file_paths"] = [*payload.get("input_s3_file_paths", base), *uploaded]


def _agent_id(agent_id: str | None) -> str:
    target = agent_id or Settings.load().default_agent_id
    if not target:
        raise typer.BadParameter(
            "Provide --agent or set default_agent_id with xmagic configure --agent."
        )
    return target


def _handle_error(error: XMagicError | ValueError | RuntimeError) -> None:
    hint = None
    if isinstance(error, XMagicAPIError) and error.error_code in _ERROR_HINTS:
        hint = _ERROR_HINTS[error.error_code]
    fail(str(error), hint)


def _task_json(task: WorklistTask) -> dict[str, Any]:
    return task.model_dump(mode="json")


def _print_task_table(task: WorklistTask) -> None:
    table = Table("field", "value")
    values = (
        ("id", task.id),
        ("name", task.name),
        ("status", task.status.value),
        ("description", task.detailed_description),
        ("created", task.created_at or "—"),
        ("started", task.started_execution_at or "—"),
        ("finished", task.finished_execution_at or "—"),
        ("error", task.error_if_any or "—"),
        ("output files", ", ".join(task.output_s3_file_paths) or "—"),
    )
    for field, value in values:
        table.add_row(field, escape(str(value)))
    console.print(table)


def _print_task_page(page: WorklistTaskPage) -> None:
    table = Table("name", "id", "status", "schedule", "created")
    for task in page.tasks:
        schedule = "recurring" if task.recurrency_schedule_id else "one-off"
        table.add_row(
            escape(task.name),
            task.id,
            task.status.value,
            schedule,
            task.created_at or "—",
        )
    console.print(table)
    console.print(f"[dim]Showing {len(page.tasks)} of {page.total} task(s).[/dim]")


def _latest_result(
    client: XMagicClient, agent_id: str, task: WorklistTask
) -> dict[str, Any] | None:
    if not task.run_chat_id or not task.run_message_ids:
        return None
    message = client.chats.get_message(
        agent_id,
        task.run_chat_id,
        task.run_message_ids[-1],
        downloadable_output=True,
    )
    return message.model_dump(mode="json")


def _print_review_item(task: WorklistTask, result: dict[str, Any] | None) -> None:
    _print_task_table(task)
    if not result:
        console.print("[dim]No execution result is attached to this task.[/dim]")
        return
    console.print("[bold]Latest result[/bold]")
    console.print(result.get("response") or "—")
    outputs = result.get("downloadable_output") or {}
    for asset_id, url in outputs.items():
        console.print(f"[dim]{escape(asset_id)}: {escape(url)}[/dim]")


def _confirm_review_task(
    client: XMagicClient,
    agent_id: str,
    task: WorklistTask,
) -> None:
    message = typer.prompt(
        "Message to agent (press Enter to complete; type /skip to leave for later)",
        default="",
        show_default=False,
    ).strip()
    if message == "/skip":
        console.print(f"[yellow]Skipped worklist task {task.id}.[/yellow]")
        return

    client.worklists.review(agent_id, task.id, message=message or None, task=task)
    if not message:
        console.print(f"[green]Completed worklist task {task.id}.[/green]")
        return
    console.print(
        f"[green]Sent follow-up message for {task.id}. The agent will continue working.[/green]"
    )


def _needs_review_tasks(
    client: XMagicClient, agent_id: str, task_id: str | None
) -> list[WorklistTask]:
    if task_id:
        task = client.worklists.get(agent_id, task_id)
        if task.status != WorklistTaskStatus.NEEDS_REVIEW:
            raise ValueError(
                f"Worklist task {task.id} has status '{task.status.value}', not 'needs_review'."
            )
        return [task]

    page = client.worklists.list(
        agent_id,
        status=WorklistTaskStatus.NEEDS_REVIEW,
        limit=200,
    )
    return page.tasks


def _edit_yaml(content: str, prefix: str) -> str | None:
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix=prefix,
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as temporary:
            temporary.write(content)
            path = Path(temporary.name)
        _edit_file(path)
        edited = path.read_text(encoding="utf-8")
        if edited == content:
            return None
        return edited
    finally:
        if path and path.exists():
            path.unlink(missing_ok=True)


def _list(
    agent_id: str | None,
    status: str | None,
    archived: bool | None,
    recurring: bool | None,
    chat_id: str | None,
    skip: int,
    limit: int,
    as_json: bool,
) -> None:
    try:
        with XMagicClient() as client:
            page = client.worklists.list(
                _agent_id(agent_id),
                status=status,
                is_archived=archived,
                is_recurring=recurring,
                creation_chat_id=chat_id,
                skip=skip,
                limit=limit,
            )
        if as_json:
            print_json(page.model_dump(mode="json"))
        else:
            _print_task_page(page)
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.callback(invoke_without_command=True)
def worklists(
    ctx: typer.Context,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    status: str | None = typer.Option(None, "--status", help="Filter by task status."),
    archived: bool | None = typer.Option(None, "--archived/--not-archived"),
    recurring: bool | None = typer.Option(None, "--recurring/--not-recurring"),
    chat_id: str | None = typer.Option(None, "--chat", help="Filter by creation chat id."),
    skip: int = typer.Option(0, "--skip", min=0),
    limit: int = typer.Option(50, "--limit", min=1, max=200),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List worklist tasks, or run a task subcommand."""
    if ctx.invoked_subcommand:
        return
    _list(agent_id, status, archived, recurring, chat_id, skip, limit, as_json)


@app.command("get")
def get_task(
    task_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Get a task and its latest execution result."""
    try:
        with XMagicClient() as client:
            target_agent = _agent_id(agent_id)
            task = client.worklists.get(target_agent, task_id)
            result = _latest_result(client, target_agent, task)
        if as_json:
            print_json({"task": _task_json(task), "result": result})
            return
        _print_task_table(task)
        if result:
            console.print("[bold]Latest result[/bold]")
            response = result.get("response") or "—"
            console.print(response)
            outputs = result.get("downloadable_output") or {}
            for asset_id, url in outputs.items():
                console.print(f"[dim]{escape(asset_id)}: {escape(url)}[/dim]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.command("review")
def review_tasks(
    task_id: str | None = typer.Argument(None, help="Review only this task id."),
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
) -> None:
    """Review tasks waiting in the needs_review state."""
    try:
        target_agent = _agent_id(agent_id)
        with XMagicClient() as client:
            tasks = _needs_review_tasks(client, target_agent, task_id)
            if not tasks:
                console.print("[green]No worklist tasks need review.[/green]")
                return

            for task in tasks:
                console.print(f"[bold]Reviewing worklist task {task.id}[/bold]")
                _print_review_item(task, _latest_result(client, target_agent, task))
                _confirm_review_task(
                    client,
                    target_agent,
                    task,
                )
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.command("create")
def create_task(
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    inputs: list[Path] | None = _INPUT_OPTION,
    folder_id: str | None = _FOLDER_OPTION,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Create a worklist task by editing a YAML template.

    Local files go in as inputs two ways: --input FILE (repeatable), which
    pre-fills the template's input_files list, or by listing them under
    input_files in the YAML. On save each is uploaded into a Drive folder and
    its storage path appended to input_s3_file_paths.
    """
    try:
        # Resolved first: with no agent to create the task for, nothing should
        # be edited, let alone uploaded into Drive.
        target_agent = _agent_id(agent_id)
        template = prefill_input_files(CREATE_TEMPLATE, [str(p) for p in inputs or []])
        edited = _edit_yaml(template, "xmagic-worklist-")
        if edited is None and inputs:
            # The pre-filled inputs are themselves the change.
            edited = template
        if edited is None:
            console.print("[yellow]No changes detected. Task was not created.[/yellow]")
            return
        payload = yaml_to_create_payload(edited)
        with XMagicClient() as client:
            _resolve_input_files(client, payload, folder_id, [])
            task = client.worklists.create(target_agent, payload)
        if as_json:
            print_json(_task_json(task))
            return
        console.print(f"[green]Created worklist task {task.id} ({task.status.value}).[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.command("edit")
def edit_task(
    task_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    inputs: list[Path] | None = _INPUT_OPTION,
    folder_id: str | None = _FOLDER_OPTION,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Edit a task's YAML-editable fields.

    --input FILE (repeatable) or an input_files list in the YAML uploads local
    files on save and appends their storage paths to input_s3_file_paths.
    """
    try:
        target_agent = _agent_id(agent_id)
        with XMagicClient() as client:
            task = client.worklists.get(target_agent, task_id)
        original = _task_json(task)
        template = prefill_input_files(task_to_edit_yaml(original), [str(p) for p in inputs or []])
        edited = _edit_yaml(template, f"xmagic-worklist-{task_id}-")
        if edited is None and inputs:
            # The pre-filled inputs are themselves the change.
            edited = template
        if edited is None:
            console.print("[yellow]No changes detected. Task was not updated.[/yellow]")
            return
        payload = yaml_to_update_payload(edited, original)
        if not payload:
            console.print("[yellow]No changes detected. Task was not updated.[/yellow]")
            return
        with XMagicClient() as client:
            _resolve_input_files(
                client, payload, folder_id, list(original.get("input_s3_file_paths") or [])
            )
            updated = client.worklists.update(target_agent, task_id, payload)
        if as_json:
            print_json(_task_json(updated))
            return
        console.print(f"[green]Updated worklist task {updated.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


def _confirm_delete(task_id: str, yes: bool) -> None:
    if not yes and not typer.confirm(f"Delete worklist task {task_id}?", err=True):
        console.print("[yellow]Deletion cancelled.[/yellow]")
        raise typer.Exit()


@app.command("delete")
def delete_task(
    task_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Delete a worklist task."""
    try:
        _confirm_delete(task_id, yes)
        with XMagicClient() as client:
            client.worklists.delete(_agent_id(agent_id), task_id)
        if as_json:
            print_json({"deleted": task_id})
            return
        console.print(f"[green]Deleted worklist task {task_id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.command("cancel")
def cancel_task(
    task_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Cancel an in-progress worklist task."""
    try:
        with XMagicClient() as client:
            task = client.worklists.stop(_agent_id(agent_id), task_id)
        if as_json:
            print_json(_task_json(task))
            return
        console.print(f"[green]Cancelled worklist task {task.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.command("trigger")
def trigger_task(
    task_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Trigger a pending worklist task."""
    try:
        with XMagicClient() as client:
            task = client.worklists.trigger(_agent_id(agent_id), task_id)
        if as_json:
            print_json(_task_json(task))
            return
        console.print(f"[green]Triggered worklist task {task.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@app.command("rerun")
def rerun_task(
    task_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Clone and rerun a completed, failed, or cancelled task."""
    try:
        with XMagicClient() as client:
            task = client.worklists.rerun(_agent_id(agent_id), task_id)
        if as_json:
            print_json(_task_json(task))
            return
        console.print(f"[green]Started rerun as worklist task {task.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@schedules_app.command("get")
def get_schedule(
    schedule_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Get a recurring worklist schedule."""
    try:
        with XMagicClient() as client:
            schedule = client.worklists.get_schedule(_agent_id(agent_id), schedule_id)
        if as_json:
            print_json(schedule.model_dump(mode="json"))
        else:
            console.print_json(json.dumps(schedule.model_dump(mode="json"), indent=2))
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@schedules_app.command("edit")
def edit_schedule(
    schedule_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Edit a recurring worklist schedule's YAML-editable fields."""
    try:
        target_agent = _agent_id(agent_id)
        with XMagicClient() as client:
            schedule = client.worklists.get_schedule(target_agent, schedule_id)
        original = schedule.model_dump(mode="json")
        edited = _edit_yaml(
            schedule_to_edit_yaml(original), f"xmagic-worklist-schedule-{schedule_id}-"
        )
        if edited is None:
            console.print("[yellow]No changes detected. Schedule was not updated.[/yellow]")
            return
        payload = yaml_to_schedule_update_payload(edited, original)
        if not payload:
            console.print("[yellow]No changes detected. Schedule was not updated.[/yellow]")
            return
        with XMagicClient() as client:
            updated = client.worklists.update_schedule(target_agent, schedule_id, payload)
        if as_json:
            print_json(updated.model_dump(mode="json"))
            return
        console.print(f"[green]Updated recurring schedule {updated.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@schedules_app.command("pause")
def pause_schedule(
    schedule_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Pause a recurring worklist schedule."""
    try:
        with XMagicClient() as client:
            schedule = client.worklists.pause_schedule(_agent_id(agent_id), schedule_id)
        if as_json:
            print_json(schedule.model_dump(mode="json"))
            return
        console.print(f"[green]Paused schedule {schedule.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@schedules_app.command("resume")
def resume_schedule(
    schedule_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Resume a paused recurring worklist schedule."""
    try:
        with XMagicClient() as client:
            schedule = client.worklists.resume_schedule(_agent_id(agent_id), schedule_id)
        if as_json:
            print_json(schedule.model_dump(mode="json"))
            return
        console.print(f"[green]Resumed schedule {schedule.id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)


@schedules_app.command("delete")
def delete_schedule(
    schedule_id: str,
    agent_id: str | None = typer.Option(None, "--agent", help="Agent id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Deactivate a recurring worklist schedule."""
    try:
        if not yes and not typer.confirm(f"Deactivate schedule {schedule_id}?", err=True):
            console.print("[yellow]Deactivation cancelled.[/yellow]")
            raise typer.Exit()
        with XMagicClient() as client:
            client.worklists.delete_schedule(_agent_id(agent_id), schedule_id)
        if as_json:
            print_json({"deactivated": schedule_id})
            return
        console.print(f"[green]Deactivated schedule {schedule_id}.[/green]")
    except (XMagicError, ValueError, RuntimeError) as error:
        _handle_error(error)
