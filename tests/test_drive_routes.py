"""The four Drive routes taken from the published API reference.

Unlike the shapes in `test_client_contracts.py`, these were never observed
against a live agent -- they come from docs.xmagic.ai/api-reference (read
2026-08-06). These tests therefore pin *our* request construction, which is what
we control, and only assert the documented response shape. The live tests are
what would catch the documentation being wrong.

Both clients are covered, because `test_async_mirrors_sync_signatures` enforces
that the two APIs match method for method and it would be easy to satisfy that
structurally while diverging on the wire.

One documentation error is already known: the reference shows folders carrying
`_id`, while every live fixture recorded on 2026-07-31 carries `id`. These tests
use `id`, because an observation beats an example.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from io import BytesIO

import pytest
import respx
from httpx import Response

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.config import DEFAULT_BASE_URL

FOLDER = "kb-1"
FOLDER_BODY = {
    "data": {
        "id": FOLDER,
        "name": "Company Policies",
        "parent_kb_id": None,
        "is_root": True,
        "child_folders_count": 3,
        "files_count": 12,
        "user_defined_tags": ["hr", "policies"],
    }
}


@pytest.fixture
def client() -> Iterator[XMagicClient]:
    c = XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL)
    yield c
    c.close()


def _zip_bytes() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("policy.pdf", b"%PDF-1.4 fake")
    return buf.getvalue()


@respx.mock
def test_get_folder_omits_the_flag_unless_asked(client: XMagicClient) -> None:
    route = respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}").mock(
        return_value=Response(200, json=FOLDER_BODY)
    )
    folder = client.drive.get_folder(FOLDER)

    assert folder.id == FOLDER
    # No `include_counts` in the query at all, rather than `include_counts=false`
    # -- the API documents it as optional and we should not send noise.
    assert "include_counts" not in str(route.calls.last.request.url)


@respx.mock
def test_get_folder_can_request_counts(client: XMagicClient) -> None:
    route = respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}").mock(
        return_value=Response(200, json=FOLDER_BODY)
    )
    client.drive.get_folder(FOLDER, include_counts=True)

    assert "include_counts=true" in str(route.calls.last.request.url)


@respx.mock
def test_update_folder_sends_only_what_changed(client: XMagicClient) -> None:
    import json

    route = respx.patch(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}").mock(
        return_value=Response(200, json=FOLDER_BODY)
    )
    client.drive.update_folder(FOLDER, name="Renamed")

    # PATCH is a partial update: sending tags=None would clear them.
    assert json.loads(route.calls.last.request.content) == {"knowledge_base_name": "Renamed"}


def test_update_folder_with_nothing_to_change_is_rejected(client: XMagicClient) -> None:
    with pytest.raises(ValueError, match="name or tags"):
        client.drive.update_folder(FOLDER)


@respx.mock
def test_delete_files_joins_ids_into_one_param(client: XMagicClient) -> None:
    route = respx.delete(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}/data-sources").mock(
        return_value=Response(200, json={"message": "Successfully deleted 2 data source(s)"})
    )
    client.drive.delete_files(FOLDER, ["ds-1", "ds-2"])

    # The API documents one comma-separated `data_source_id`, not a repeated param.
    url = str(route.calls.last.request.url)
    assert "data_source_id=ds-1%2Cds-2" in url or "data_source_id=ds-1,ds-2" in url


@respx.mock
def test_delete_files_accepts_a_bare_id(client: XMagicClient) -> None:
    route = respx.delete(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}/data-sources").mock(
        return_value=Response(200, json={"message": "ok"})
    )
    client.drive.delete_files(FOLDER, "ds-1")

    assert "data_source_id=ds-1" in str(route.calls.last.request.url)


def test_empty_id_list_is_rejected_before_any_request(client: XMagicClient) -> None:
    with pytest.raises(ValueError, match="at least one"):
        client.drive.delete_files(FOLDER, [])


@respx.mock
def test_download_returns_zip_bytes_not_json(client: XMagicClient) -> None:
    payload = _zip_bytes()
    respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}/data-sources/actions/download").mock(
        return_value=Response(200, content=payload, headers={"content-type": "application/zip"})
    )
    result = client.drive.download_files(FOLDER, ["ds-1"])

    # The one documented endpoint that does not answer JSON, so it must bypass
    # the normal parse path entirely.
    assert isinstance(result, bytes)
    assert zipfile.ZipFile(BytesIO(result)).namelist() == ["policy.pdf"]


@respx.mock
def test_download_error_still_raises_a_typed_error(client: XMagicClient) -> None:
    from xmagic.errors import NotFoundError

    respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}/data-sources/actions/download").mock(
        return_value=Response(404, json={"message": "no such data source"})
    )

    # Errors are JSON even when success is not, so the raw path must not skip
    # error handling.
    with pytest.raises(NotFoundError):
        client.drive.download_files(FOLDER, ["missing"])


@respx.mock
async def test_async_mirror_hits_the_same_routes() -> None:
    respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}").mock(
        return_value=Response(200, json=FOLDER_BODY)
    )
    respx.get(f"{DEFAULT_BASE_URL}/knowledge-bases/{FOLDER}/data-sources/actions/download").mock(
        return_value=Response(200, content=_zip_bytes())
    )

    async with AsyncXMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        folder = await client.drive.get_folder(FOLDER)
        blob = await client.drive.download_files(FOLDER, "ds-1")

    assert folder.id == FOLDER
    assert zipfile.ZipFile(BytesIO(blob)).namelist() == ["policy.pdf"]
