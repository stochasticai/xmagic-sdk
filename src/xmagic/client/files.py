"""File upload API (POST /uploaded-files).

Uploaded files return an id that can be referenced in chat queries via the
``uploaded_files`` parameter.

Response envelope confirmed against a live agent (2026-07-31):
``{"data": "<uploaded_file_id>"}`` -- always a bare id string, never wrapped
in a ``file`` object.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import UploadedFile

UPLOAD_PATH = "/uploaded-files"


def _upload_files_arg(path: Path) -> dict[str, Any]:
    """Build the multipart payload.

    Reads the file into memory so the transport's retry loop can safely re-send
    the body (an open handle would be exhausted after attempt 1).
    """
    return {"file": (path.name, path.read_bytes())}


class FilesAPI:
    """Upload documents for agent processing."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def upload(self, path: str | Path) -> UploadedFile:
        """Upload a local file; returns the file record with its id."""
        p = Path(path)
        body = self._t.request("POST", UPLOAD_PATH, files=_upload_files_arg(p))
        return UploadedFile(id=body["data"], filename=p.name)


class AsyncFilesAPI:
    """Async mirror of :class:`FilesAPI`."""

    def __init__(self, transport: AsyncHttpTransport) -> None:
        self._t = transport

    async def upload(self, path: str | Path) -> UploadedFile:
        """Upload a local file; returns the file record with its id."""
        p = Path(path)
        body = await self._t.request("POST", UPLOAD_PATH, files=_upload_files_arg(p))
        return UploadedFile(id=body["data"], filename=p.name)
