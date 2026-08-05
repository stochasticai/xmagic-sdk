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

from xmagic.client.files import UPLOAD_PATH, _upload_files_arg
from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import DriveFile, DriveFolder

KB_PATH = "/knowledge-bases"


def _folder_path(folder_id: str) -> str:
    return f"{KB_PATH}/{folder_id}"


def _documents_path(folder_id: str) -> str:
    return f"{KB_PATH}/{folder_id}/data-sources/documents"


def _create_folder_payload(name: str, extra: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"knowledge_base_name": name, "user_defined_tags": []}
    payload.update(extra)
    return payload


def _attach_payload(filename: str, uploaded_file_id: str) -> dict[str, Any]:
    return {
        "data_source_title": filename,
        "file_id": uploaded_file_id,
        "trigger_indexing": False,
    }


def _folders_from(body: dict[str, Any]) -> list[DriveFolder]:
    """Keep only top-level folders: data sources and nested items are files."""
    items = body["data"]["results"]
    folders = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("type") != "data_source"
        and not item.get("knowledge_base_id")
    ]
    return [DriveFolder.model_validate(i) for i in folders]


def _files_from(body: dict[str, Any]) -> list[DriveFile]:
    """Keep only the items that are data sources within a folder."""
    items = body["data"]["results"]
    files = [
        item
        for item in items
        if isinstance(item, dict)
        and (item.get("type") == "data_source" or item.get("knowledge_base_id"))
    ]
    return [DriveFile.model_validate(i) for i in files]


class DriveAPI:
    """Knowledge-base folders and files."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def list_folders(self) -> list[DriveFolder]:
        return _folders_from(self._t.request("GET", KB_PATH))

    def create_folder(self, name: str, **extra: Any) -> DriveFolder:
        body = self._t.request("POST", KB_PATH, json=_create_folder_payload(name, extra))
        return DriveFolder.model_validate(body["data"])

    def delete_folder(self, folder_id: str) -> None:
        self._t.request("DELETE", _folder_path(folder_id))

    def upload_file(self, folder_id: str, path: str | Path) -> DriveFile:
        """Upload a file into a folder; xMagic indexes it automatically.

        Backend flow is two-step:
            1) upload bytes to ``/uploaded-files``
            2) attach that uploaded file to the target knowledge base
        """
        p = Path(path)
        uploaded = self._t.request("POST", UPLOAD_PATH, files=_upload_files_arg(p))
        body = self._t.request(
            "POST", _documents_path(folder_id), json=_attach_payload(p.name, uploaded["data"])
        )
        return DriveFile.model_validate(body["data"])

    def list_files(self, folder_id: str) -> list[DriveFile]:
        return _files_from(self._t.request("GET", KB_PATH, params={"parent_kb_id": folder_id}))


class AsyncDriveAPI:
    """Async mirror of :class:`DriveAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def list_folders(self) -> list[DriveFolder]:
        return _folders_from(await self._t.request("GET", KB_PATH))

    async def create_folder(self, name: str, **extra: Any) -> DriveFolder:
        body = await self._t.request("POST", KB_PATH, json=_create_folder_payload(name, extra))
        return DriveFolder.model_validate(body["data"])

    async def delete_folder(self, folder_id: str) -> None:
        await self._t.request("DELETE", _folder_path(folder_id))

    async def upload_file(self, folder_id: str, path: str | Path) -> DriveFile:
        """Upload a file into a folder; xMagic indexes it automatically."""
        p = Path(path)
        uploaded = await self._t.request("POST", UPLOAD_PATH, files=_upload_files_arg(p))
        body = await self._t.request(
            "POST", _documents_path(folder_id), json=_attach_payload(p.name, uploaded["data"])
        )
        return DriveFile.model_validate(body["data"])

    async def list_files(self, folder_id: str) -> list[DriveFile]:
        body = await self._t.request("GET", KB_PATH, params={"parent_kb_id": folder_id})
        return _files_from(body)
