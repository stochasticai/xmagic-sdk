"""Drive (knowledge base) API: folder/file CRUD with automatic indexing.

Routes and responses are verified against the xMagic backend implementation:

- GET    /knowledge-bases                                   -> {"data": {"results": [...]}}
- POST   /knowledge-bases                                    -> {"data": {<folder fields>}}
- DELETE /knowledge-bases/{knowledge_base_id}                -> {"message": ...} (no "data")
- POST   /uploaded-files                                     -> {"data": "<uploaded_file_id>"}
- POST   /knowledge-bases/{knowledge_base_id}/data-sources/documents -> {"data": {<data-source fields>}}
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
        body = self._t.request("GET", "/knowledge-bases")
        items = body["data"]["results"]
        folders = [
            item
            for item in items
            if isinstance(item, dict)
            and item.get("type") != "data_source"
            and not item.get("knowledge_base_id")
        ]
        return [DriveFolder.model_validate(i) for i in folders]

    def create_folder(self, name: str, **extra: Any) -> DriveFolder:
        payload = {"knowledge_base_name": name, "user_defined_tags": []}
        payload.update(extra)
        body = self._t.request("POST", "/knowledge-bases", json=payload)
        return DriveFolder.model_validate(body["data"])

    def delete_folder(self, folder_id: str) -> None:
        self._t.request("DELETE", f"/knowledge-bases/{folder_id}")

    def upload_file(self, folder_id: str, path: str | Path) -> DriveFile:
        """Upload a file into a folder; xMagic indexes it automatically.

        Reads the file into memory so the transport's retry loop can safely
        re-send the body.

        Backend flow is two-step:
            1) upload bytes to ``/uploaded-files``
            2) attach that uploaded file to the target knowledge base
        """
        p = Path(path)
        uploaded = self._t.request(
            "POST", "/uploaded-files", files={"file": (p.name, p.read_bytes())}
        )
        uploaded_file_id = uploaded["data"]

        body = self._t.request(
            "POST",
            f"/knowledge-bases/{folder_id}/data-sources/documents",
            json={
                "data_source_title": p.name,
                "file_id": uploaded_file_id,
                "trigger_indexing": False,
            },
        )
        return DriveFile.model_validate(body["data"])

    def list_files(self, folder_id: str) -> list[DriveFile]:
        body = self._t.request("GET", "/knowledge-bases", params={"parent_kb_id": folder_id})
        items = body["data"]["results"]
        files = [
            item
            for item in items
            if isinstance(item, dict)
            and (item.get("type") == "data_source" or item.get("knowledge_base_id"))
        ]
        return [DriveFile.model_validate(i) for i in files]
