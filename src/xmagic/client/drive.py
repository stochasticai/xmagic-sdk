"""Drive (knowledge base) API: folder/file CRUD with automatic indexing.

NOTE: Endpoint paths below follow the documented Drive API surface at a high
level; verify exact paths against https://docs.xmagic.ai/api-drive when wiring
tests (Phase 4 in DESIGN.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xmagic.client.http import HttpTransport
from xmagic.client.models import DriveFile, DriveFolder


class DriveAPI:
    """Knowledge-base folders and files."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def list_folders(self) -> list[DriveFolder]:
        body = self._t.request("GET", "/drive/folders")
        items = body.get("data", {}).get("folders", body.get("data", []))
        return [DriveFolder.model_validate(i) for i in items]

    def create_folder(self, name: str, **extra: Any) -> DriveFolder:
        body = self._t.request("POST", "/drive/folders", json={"name": name, **extra})
        data = body.get("data", body)
        return DriveFolder.model_validate(data.get("folder", data))

    def delete_folder(self, folder_id: str) -> None:
        self._t.request("DELETE", f"/drive/folders/{folder_id}")

    def upload_file(self, folder_id: str, path: str | Path) -> DriveFile:
        """Upload a file into a folder; xMagic indexes it automatically.

        Reads the file into memory so the transport's retry loop can safely
        re-send the body.
        """
        p = Path(path)
        body = self._t.request(
            "POST", f"/drive/folders/{folder_id}/files", files={"file": (p.name, p.read_bytes())}
        )
        data = body.get("data", body)
        return DriveFile.model_validate(data.get("file", data))

    def list_files(self, folder_id: str) -> list[DriveFile]:
        body = self._t.request("GET", f"/drive/folders/{folder_id}/files")
        items = body.get("data", {}).get("files", body.get("data", []))
        return [DriveFile.model_validate(i) for i in items]
