"""``xmagic drive`` — knowledge-base folders and files, from the command line.

Every route the client implements (``client/drive.py``) is reachable here::

    xmagic drive ls [FOLDER_ID] [-R]        folders, a folder's files, or every folder's files
    xmagic drive mkdir NAME                 create a folder
    xmagic drive info FOLDER_ID             one folder, with its counts
    xmagic drive rename FOLDER_ID NAME      rename a folder
    xmagic drive upload FOLDER_ID PATH      upload a file into a folder
    xmagic drive download FOLDER_ID FILE... export files as a ZIP, optionally extracted
    xmagic drive rm FOLDER_ID [FILE...]     delete files, or the whole folder

``rm`` with no file ids deletes the folder and everything in it, so it asks
first unless ``--yes``. Every command takes ``--json`` (``cli/_output.py``).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from xmagic import XMagicClient
from xmagic.cli._output import fail, note, print_json
from xmagic.client.models import DriveFile, DriveFolder
from xmagic.errors import XMagicError

console = Console()
app = typer.Typer(no_args_is_help=True)

_JSON = typer.Option(False, "--json", help="Machine-readable output.")


def _client() -> XMagicClient:
    try:
        return XMagicClient()
    except XMagicError as e:
        fail(str(e))


def _dump(model: DriveFolder | DriveFile) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _folders_table(folders: list[DriveFolder]) -> Table:
    table = Table("id", "name")
    for f in folders:
        table.add_row(f.id, f.name or "")
    return table


def _files_table(files: list[DriveFile]) -> Table:
    table = Table("id", "title")
    for f in files:
        table.add_row(f.id, f.title or "")
    return table


@app.command("ls")
def list_(
    folder_id: str | None = typer.Argument(None, help="List this folder's files."),
    recursive: bool = typer.Option(
        False, "--recursive", "-R", help="Every folder and the files in it."
    ),
    as_json: bool = _JSON,
) -> None:
    """List Drive folders, or the files in one folder.

    With no argument, the folders. With FOLDER_ID, its files. With -R, every
    folder followed by its files; under --json that is a list of
    {"folder": ..., "files": [...]} objects.
    """
    client = _client()
    try:
        if folder_id is not None:
            files = client.drive.list_files(folder_id)
            if as_json:
                print_json([_dump(f) for f in files])
            else:
                console.print(_files_table(files))
            return
        folders = client.drive.list_folders()
        if not recursive:
            if as_json:
                print_json([_dump(f) for f in folders])
            else:
                console.print(_folders_table(folders))
            return
        tree = [(folder, client.drive.list_files(folder.id)) for folder in folders]
    except XMagicError as e:
        fail(str(e))
    if as_json:
        print_json([{"folder": _dump(f), "files": [_dump(x) for x in files]} for f, files in tree])
        return
    table = Table("folder", "name", "file id", "title")
    for folder, files in tree:
        if not files:
            table.add_row(folder.id, folder.name or "", "", "")
        for i, f in enumerate(files):
            table.add_row(
                folder.id if i == 0 else "",
                folder.name or "" if i == 0 else "",
                f.id,
                f.title or "",
            )
    console.print(table)


@app.command()
def mkdir(
    name: str = typer.Argument(..., help="Folder name."),
    as_json: bool = _JSON,
) -> None:
    """Create a folder (knowledge base)."""
    client = _client()
    try:
        folder = client.drive.create_folder(name)
    except XMagicError as e:
        fail(str(e))
    if as_json:
        print_json(_dump(folder))
        return
    console.print(f"[green]Created folder {folder.name or name} -> id {folder.id}[/green]")


@app.command()
def info(
    folder_id: str = typer.Argument(...),
    as_json: bool = _JSON,
) -> None:
    """Show one folder, with its child and file counts."""
    client = _client()
    try:
        folder = client.drive.get_folder(folder_id, include_counts=True)
    except XMagicError as e:
        fail(str(e))
    if as_json:
        print_json(_dump(folder))
        return
    table = Table("field", "value")
    for key, value in _dump(folder).items():
        if value not in (None, [], {}, ""):
            table.add_row(key, str(value))
    console.print(table)


@app.command()
def rename(
    folder_id: str = typer.Argument(...),
    name: str = typer.Argument(..., help="The new name."),
    as_json: bool = _JSON,
) -> None:
    """Rename a folder."""
    client = _client()
    try:
        folder = client.drive.update_folder(folder_id, name=name)
    except XMagicError as e:
        fail(str(e))
    if as_json:
        print_json(_dump(folder))
        return
    console.print(f"[green]Renamed {folder.id} -> {folder.name or name}[/green]")


@app.command()
def upload(
    folder_id: str = typer.Argument(...),
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    as_json: bool = _JSON,
) -> None:
    """Upload a file into a folder (auto-indexed by xMagic)."""
    client = _client()
    try:
        f = client.drive.upload_file(folder_id, path)
    except XMagicError as e:
        fail(str(e))
    if as_json:
        print_json(_dump(f))
        return
    console.print(f"[green]Uploaded {path.name} -> file id {f.id}[/green]")


@app.command()
def download(
    folder_id: str = typer.Argument(...),
    file_ids: list[str] = typer.Argument(..., help="One or more file ids in the folder."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Where to write the ZIP (default: <folder_id>.zip)."
    ),
    extract: Path | None = typer.Option(
        None, "--extract", help="Extract the files into this directory instead of keeping a ZIP."
    ),
    as_json: bool = _JSON,
) -> None:
    """Download files from a folder.

    xMagic exports files as one ZIP archive, even for a single file. By
    default the archive is written next to you as <folder_id>.zip; --output
    names it, and --extract unpacks it into a directory and keeps no archive
    unless --output is also given.
    """
    client = _client()
    try:
        data = client.drive.download_files(folder_id, file_ids)
    except XMagicError as e:
        fail(str(e))
    zip_path: Path | None = output if output is not None else None
    if zip_path is None and extract is None:
        zip_path = Path(f"{folder_id}.zip")
    if zip_path is not None:
        zip_path.write_bytes(data)
    extracted: list[str] = []
    if extract is not None:
        extract.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(extract)
                extracted = [str(extract / name) for name in archive.namelist()]
        except zipfile.BadZipFile:
            fail("The server did not return a ZIP archive; nothing was extracted.")
    if as_json:
        print_json(
            {
                "folder_id": folder_id,
                "file_ids": list(file_ids),
                "zip": str(zip_path) if zip_path is not None else None,
                "extracted": extracted,
            }
        )
        return
    if zip_path is not None:
        console.print(f"[green]Wrote {zip_path} ({len(data)} bytes)[/green]")
    for path in extracted:
        console.print(f"[green]Extracted {path}[/green]")


@app.command()
def rm(
    folder_id: str = typer.Argument(...),
    file_ids: list[str] | None = typer.Argument(
        None, help="File ids to delete. With none, the whole folder is deleted."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation."),
    as_json: bool = _JSON,
) -> None:
    """Delete files from a folder, or the folder itself.

    With file ids, only those files go. With none, the folder and everything
    in it go, after a confirmation that --yes skips.
    """
    client = _client()
    ids = list(file_ids or [])
    if (
        not ids
        and not yes
        and not typer.confirm(f"Delete folder {folder_id} and everything in it?")
    ):
        note("Nothing deleted.")
        raise typer.Exit(1)
    try:
        if ids:
            client.drive.delete_files(folder_id, ids)
        else:
            client.drive.delete_folder(folder_id)
    except XMagicError as e:
        fail(str(e))
    if as_json:
        if ids:
            print_json({"folder_id": folder_id, "deleted_files": ids})
        else:
            print_json({"folder_id": folder_id, "deleted_folder": True})
        return
    if ids:
        console.print(f"[green]Deleted {len(ids)} file(s) from {folder_id}[/green]")
    else:
        console.print(f"[green]Deleted folder {folder_id}[/green]")
