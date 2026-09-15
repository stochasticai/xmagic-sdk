"""Drive (knowledge base) API: folder/file CRUD with automatic indexing.

Routes and responses are verified against the xMagic backend implementation:

- GET    /knowledge-bases?page=N&page_size=M                -> {"data": {"results": [...], "pagination": {...}}}
- POST   /knowledge-bases                                    -> {"data": {<folder fields>}}
- DELETE /knowledge-bases/{knowledge_base_id}                -> {"message": ...} (no "data")
- POST   /uploaded-files                                     -> {"data": "<uploaded_file_id>"}
- POST   /knowledge-bases/{knowledge_base_id}/data-sources/documents -> {"data": {<data-source fields>}}

These four come from the published API reference (docs.xmagic.ai/api-reference,
read 2026-08-06) rather than from a live call, so they are documented but not yet
observed. The distinction matters: the shapes above were confirmed against a real
agent; these are taken on the documentation's word.

- GET    /knowledge-bases/{knowledge_base_id}                -> {"data": {<folder fields>}}
- PATCH  /knowledge-bases/{knowledge_base_id}                -> {"data": {<folder fields>}}
- DELETE /knowledge-bases/{knowledge_base_id}/data-sources   -> {"message": ...}
- GET    /knowledge-bases/{knowledge_base_id}/data-sources/actions/download
                                                             -> application/zip (bytes)

Two discrepancies found while implementing them:

- The reference shows folders carrying ``_id``; every fixture recorded live on
  2026-07-31 carries ``id``, which is what ``DriveFolder`` expects. Observation
  beats example, so we read ``id``.
- **Listing is paginated, and the parameters are undocumented.** Measured live
  on 2026-09-15: ``GET /knowledge-bases`` takes ``page`` (zero-indexed) and
  ``page_size`` (1 to 200, validated with a 422 outside that range; default 20)
  and echoes both in ``data.pagination`` beside ``total_count``. A page past
  the end returns 200 with empty ``results``. Any other parameter name
  (``limit``, ``offset``, ``per_page``) is ignored. ``data.knowledge_bases`` is
  byte-for-byte the same list as ``data.results`` and is not read. The
  ``?parent_kb_id=`` file listing paginates the same way.

  ``list_folders`` and ``list_files`` walk every page at the maximum size and
  return the whole listing, because a Drive listing is something callers
  iterate, not something they page through by hand. That is deliberately
  unlike worklists, where ``skip``/``limit`` are explicit (``worklists.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xmagic.client.files import UPLOAD_PATH, _upload_files_arg
from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import DriveFile, DriveFolder

KB_PATH = "/knowledge-bases"

# The largest page the platform accepts (201 is rejected with a 422, measured
# 2026-09-15). Fewer round trips for large Drives, and the number the fake
# honours too.
PAGE_SIZE = 200


def _folder_path(folder_id: str) -> str:
    return f"{KB_PATH}/{folder_id}"


def _documents_path(folder_id: str) -> str:
    return f"{KB_PATH}/{folder_id}/data-sources/documents"


def _data_sources_path(folder_id: str) -> str:
    return f"{KB_PATH}/{folder_id}/data-sources"


def _download_path(folder_id: str) -> str:
    return f"{_data_sources_path(folder_id)}/actions/download"


def _update_folder_payload(name: str | None, tags: list[str] | None) -> dict[str, Any]:
    """Only send what the caller asked to change; PATCH is a partial update."""
    payload: dict[str, Any] = {}
    if name is not None:
        payload["knowledge_base_name"] = name
    if tags is not None:
        payload["user_defined_tags"] = tags
    if not payload:
        raise ValueError("update_folder needs a name or tags to change.")
    return payload


def _data_source_params(file_ids: str | list[str]) -> dict[str, str]:
    """The API takes one comma-separated `data_source_id`, not repeated params."""
    ids = [file_ids] if isinstance(file_ids, str) else list(file_ids)
    if not ids:
        raise ValueError("Provide at least one data source id.")
    return {"data_source_id": ",".join(ids)}


def _page_params(page: int, folder_id: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "page_size": PAGE_SIZE}
    if folder_id is not None:
        params["parent_kb_id"] = folder_id
    return params


def _take_page(items: list[Any], body: dict[str, Any], page: int) -> int | None:
    """Append one page's results to ``items``; return the next page, or None.

    The stop rules read the response, not our request, so a server that ignores
    the parameters still terminates: no results, a short page (fewer than the
    ``page_size`` the server echoes), or ``total_count`` reached all end the
    walk. A body with no ``pagination`` block is treated as the only page.
    """
    data = body["data"]
    results = data["results"]
    items.extend(results)
    pagination = data.get("pagination")
    if not results or not isinstance(pagination, dict):
        return None
    total = pagination.get("total_count")
    size = pagination.get("page_size")
    if isinstance(size, int) and len(results) < size:
        return None
    if isinstance(total, int) and len(items) >= total:
        return None
    return page + 1


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


def _folders_from(items: list[Any]) -> list[DriveFolder]:
    """Keep only top-level folders: data sources and nested items are files."""
    folders = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("type") != "data_source"
        and not item.get("knowledge_base_id")
    ]
    return [DriveFolder.model_validate(i) for i in folders]


def _files_from(items: list[Any]) -> list[DriveFile]:
    """Keep only the items that are data sources within a folder."""
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

    def _list_all(self, folder_id: str | None) -> list[Any]:
        items: list[Any] = []
        page: int | None = 0
        while page is not None:
            body = self._t.request("GET", KB_PATH, params=_page_params(page, folder_id))
            page = _take_page(items, body, page)
        return items

    def list_folders(self) -> list[DriveFolder]:
        """Every top-level folder, across all pages."""
        return _folders_from(self._list_all(None))

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
        """Every file in a folder, across all pages."""
        return _files_from(self._list_all(folder_id))

    def get_folder(self, folder_id: str, *, include_counts: bool = False) -> DriveFolder:
        """Fetch one folder. ``include_counts`` adds child folder and file counts."""
        params = {"include_counts": include_counts} if include_counts else None
        body = self._t.request("GET", _folder_path(folder_id), params=params)
        return DriveFolder.model_validate(body["data"])

    def update_folder(
        self, folder_id: str, *, name: str | None = None, tags: list[str] | None = None
    ) -> DriveFolder:
        """Rename a folder and/or replace its tags."""
        payload = _update_folder_payload(name, tags)
        body = self._t.request("PATCH", _folder_path(folder_id), json=payload)
        return DriveFolder.model_validate(body["data"])

    def delete_files(self, folder_id: str, file_ids: str | list[str]) -> None:
        """Delete one or more data sources from a folder."""
        self._t.request(
            "DELETE", _data_sources_path(folder_id), params=_data_source_params(file_ids)
        )

    def download_files(self, folder_id: str, file_ids: str | list[str]) -> bytes:
        """Export data sources as a ZIP archive, returned as bytes.

        Always a ZIP, even for a single file -- so callers get one shape rather
        than having to branch on how many ids they passed.
        """
        return self._t.request_bytes(
            "GET", _download_path(folder_id), params=_data_source_params(file_ids)
        )


class AsyncDriveAPI:
    """Async mirror of :class:`DriveAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def _list_all(self, folder_id: str | None) -> list[Any]:
        items: list[Any] = []
        page: int | None = 0
        while page is not None:
            body = await self._t.request("GET", KB_PATH, params=_page_params(page, folder_id))
            page = _take_page(items, body, page)
        return items

    async def list_folders(self) -> list[DriveFolder]:
        """Every top-level folder, across all pages."""
        return _folders_from(await self._list_all(None))

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
        """Every file in a folder, across all pages."""
        return _files_from(await self._list_all(folder_id))

    async def get_folder(self, folder_id: str, *, include_counts: bool = False) -> DriveFolder:
        """Fetch one folder. ``include_counts`` adds child folder and file counts."""
        params = {"include_counts": include_counts} if include_counts else None
        body = await self._t.request("GET", _folder_path(folder_id), params=params)
        return DriveFolder.model_validate(body["data"])

    async def update_folder(
        self, folder_id: str, *, name: str | None = None, tags: list[str] | None = None
    ) -> DriveFolder:
        """Rename a folder and/or replace its tags."""
        payload = _update_folder_payload(name, tags)
        body = await self._t.request("PATCH", _folder_path(folder_id), json=payload)
        return DriveFolder.model_validate(body["data"])

    async def delete_files(self, folder_id: str, file_ids: str | list[str]) -> None:
        """Delete one or more data sources from a folder."""
        await self._t.request(
            "DELETE", _data_sources_path(folder_id), params=_data_source_params(file_ids)
        )

    async def download_files(self, folder_id: str, file_ids: str | list[str]) -> bytes:
        """Export data sources as a ZIP archive, returned as bytes."""
        return await self._t.request_bytes(
            "GET", _download_path(folder_id), params=_data_source_params(file_ids)
        )
