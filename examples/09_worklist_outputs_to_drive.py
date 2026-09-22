"""Worklist outputs to Drive: file what completed tasks produced.

A completed task keeps its results on the last message of its run chat.
`downloadable_output` there maps a short key to a time-limited presigned URL for
each file the agent produced. This script walks every page of an agent's
completed tasks, downloads each output while its URL is valid, and uploads it
into a Drive folder, where xMagic indexes it and any agent can retrieve it.

It reads tasks and writes only to the destination folder (and, with --keep, a
local directory); nothing on the worklist is modified.

Run:
    export XMAGIC_API_KEY="xm-..."
    uv run python examples/09_worklist_outputs_to_drive.py <agent_id> <folder_id>
    uv run python examples/09_worklist_outputs_to_drive.py <agent_id> <folder_id> --task <task_id>
    uv run python examples/09_worklist_outputs_to_drive.py <agent_id> <folder_id> --keep ./outputs

Find a folder id with `xmagic drive ls`, or make one with `xmagic drive mkdir`.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from xmagic import XMagicClient
from xmagic.client.models import DriveFile, WorklistTask, WorklistTaskStatus
from xmagic.errors import ConfigurationError, XMagicAPIError


@dataclass
class Filed:
    """One output that made it into Drive."""

    task_id: str
    key: str
    local: Path
    file: DriveFile


def completed_tasks(
    client: XMagicClient, agent_id: str, *, page_size: int = 50
) -> Iterator[WorklistTask]:
    """Every completed task, following the pages the API hands back one at a time."""
    skip = 0
    while True:
        page = client.worklists.list(
            agent_id, status=WorklistTaskStatus.COMPLETED, skip=skip, limit=page_size
        )
        yield from page.tasks
        skip += len(page.tasks)
        if not page.tasks or skip >= page.total:
            return


def output_urls(client: XMagicClient, agent_id: str, task: WorklistTask) -> dict[str, str]:
    """The presigned download URLs of a task's outputs, keyed by the platform's short key.

    They hang off the run chat's last message, so a task that finished without
    a run message (some older tasks did) has outputs on the record but no URL
    the API will hand out; those are reported and skipped.
    """
    if not task.run_chat_id or not task.run_message_ids:
        return {}
    message = client.chats.get_message(
        agent_id, task.run_chat_id, task.run_message_ids[-1], downloadable_output=True
    )
    return dict(message.downloadable_output)


def filename_for(url: str, fallback: str) -> str:
    """The object's own name from the URL path, or the platform's key if it has none.

    The basename is taken again after decoding, so an encoded slash in the
    object name (``a%2Fb.txt``) cannot turn the local path into a subdirectory.
    """
    name = Path(unquote(Path(urlsplit(url).path).name)).name
    return name or fallback


def download(url: str, dest: Path) -> Path:
    """Stream a presigned URL to disk. No API key goes with it: the URL is the credential."""
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        with dest.open("wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
    return dest


def file_outputs(
    client: XMagicClient,
    agent_id: str,
    folder_id: str,
    dest_dir: Path,
    *,
    task_id: str | None = None,
    log: Callable[[str], None] = print,
) -> list[Filed]:
    """Download every output of the agent's completed tasks and upload each into Drive."""
    filed: list[Filed] = []
    used: set[Path] = set()
    tasks: Iterator[WorklistTask]
    if task_id:
        tasks = iter([client.worklists.get(agent_id, task_id)])
    else:
        tasks = completed_tasks(client, agent_id)

    for task in tasks:
        urls = output_urls(client, agent_id, task)
        if not urls:
            if task.output_s3_file_paths:
                log(
                    f"{task.id}  {task.name!r}: {len(task.output_s3_file_paths)} output(s) on record, no download URL exposed"
                )
            continue
        for key, url in urls.items():
            name = filename_for(url, key)
            local = dest_dir / f"{task.id}-{name}"
            if local in used:
                # Two outputs of one task with the same object name: keep both
                # on disk, so --keep really keeps every copy.
                local = dest_dir / f"{task.id}-{key}-{name}"
            used.add(local)
            download(url, local)
            uploaded = client.drive.upload_file(folder_id, local)
            filed.append(Filed(task.id, key, local, uploaded))
            log(
                f"{task.id}  {key} -> {local.name} ({local.stat().st_size} bytes) -> Drive {uploaded.id}"
            )
    return filed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("agent_id")
    parser.add_argument("folder_id", help="Destination Drive folder (xmagic drive ls / mkdir).")
    parser.add_argument("--task", help="Only this task, whatever its status.")
    parser.add_argument("--keep", type=Path, help="Keep local copies in this directory.")
    args = parser.parse_args()

    try:
        client = XMagicClient()
    except ConfigurationError as e:
        print(e, file=sys.stderr)
        return 2

    with client, tempfile.TemporaryDirectory() as tmp:
        dest = args.keep or Path(tmp)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            filed = file_outputs(client, args.agent_id, args.folder_id, dest, task_id=args.task)
        except XMagicAPIError as e:
            print(f"API error: {e}", file=sys.stderr)
            return 1
        except httpx.HTTPError as e:
            print(f"Download failed: {e}", file=sys.stderr)
            return 1

    print(f"\n{len(filed)} file(s) filed into folder {args.folder_id}.")
    if args.keep:
        print(f"Local copies kept under {args.keep}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
