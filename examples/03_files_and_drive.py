"""Files and Drive: attach a file to a question, then index one in a knowledge base.

Two distinct flows that both start with an upload:

1. **Per-query file** — upload, then pass its id as `uploaded_files` on a query.
   Scoped to that question.
2. **Drive (knowledge base)** — upload into a folder, where xMagic indexes it so
   the agent can retrieve from it across chats.

Run:
    export XMAGIC_API_KEY="xm-..."
    export XMAGIC_AGENT_ID="<agent_id>"     # or: xmagic configure --agent <id>
    uv run python examples/03_files_and_drive.py            # cleans up after itself
    uv run python examples/03_files_and_drive.py --keep     # leaves the folder behind
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from xmagic import XMagicClient
from xmagic.errors import ConfigurationError, XMagicAPIError

FOLDER_NAME = "xmagic-sdk-example"

SAMPLE = """\
# Q3 Engineering Notes

- Shipped the streaming client in July.
- Deferred the async client to the following milestone.
- Open risk: MCP transport is assumed to be streamable HTTP.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the Drive folder this example creates (default: delete it)",
    )
    args = parser.parse_args()

    try:
        client = XMagicClient()
    except ConfigurationError as e:
        print(e, file=sys.stderr)
        return 2

    with client:
        agent_id = os.environ.get("XMAGIC_AGENT_ID") or client.settings.default_agent_id
        if not agent_id:
            print(
                "No agent id. Set XMAGIC_AGENT_ID, or run `xmagic configure --agent <id>`.",
                file=sys.stderr,
            )
            return 2

        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "q3-notes.md"
            sample.write_text(SAMPLE, encoding="utf-8")

            try:
                # --- 1. Per-query file ------------------------------------
                uploaded = client.files.upload(sample)
                print(f"uploaded: {uploaded.filename} -> {uploaded.id}")

                chat = client.chats.create(agent_id, title="SDK example: files")
                response = client.chats.query(
                    agent_id,
                    chat.id,
                    "What open risk do these notes mention?",
                    uploaded_files=[uploaded.id],
                )
                print(f"\n{response.text}\n")

                # --- 2. Drive (knowledge base) ----------------------------
                folder = client.drive.create_folder(FOLDER_NAME)
                print(f"drive folder: {folder.name} ({folder.id})")

                try:
                    drive_file = client.drive.upload_file(folder.id, sample)
                    print(f"indexed: {drive_file.title} ({drive_file.id})")

                    files = client.drive.list_files(folder.id)
                    print(f"folder now holds {len(files)} file(s): {[f.title for f in files]}")
                finally:
                    if args.keep:
                        print(f"\nKeeping folder {folder.id} — delete it in the dashboard.")
                    else:
                        client.drive.delete_folder(folder.id)
                        print(f"\nDeleted folder {folder.id}.")

            except XMagicAPIError as e:
                print(f"API error: {e}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
