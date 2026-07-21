"""File upload API (POST /uploaded-files).

Uploaded files return an id that can be referenced in chat queries via the
``uploaded_files`` parameter.
"""

from __future__ import annotations

from pathlib import Path

from xmagic.client.http import HttpTransport
from xmagic.client.models import UploadedFile


class FilesAPI:
    """Upload documents for agent processing."""

    def __init__(self, transport: HttpTransport) -> None:
        self._t = transport

    def upload(self, path: str | Path) -> UploadedFile:
        """Upload a local file; returns the file record with its id.

        Reads the file into memory so the transport's retry loop can safely
        re-send the body (an open handle would be exhausted after attempt 1).
        """
        p = Path(path)
        body = self._t.request(
            "POST", "/uploaded-files", files={"file": (p.name, p.read_bytes())}
        )
        data = body.get("data", body)
        return UploadedFile.model_validate(data.get("file", data))
