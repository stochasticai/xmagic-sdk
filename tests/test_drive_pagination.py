"""Drive listings walk every page.

The request parameters are undocumented and were measured live on 2026-09-15
(issue #5, Q15): ``page`` is zero-indexed, ``page_size`` is 1..200, and both
are echoed in ``data.pagination`` beside ``total_count``. These tests pin the
walk we control: the parameters sent, the pages requested, when the walk
stops, and that an unpaginated or single-page body still works. The stop rules
read the response rather than trust the request, so a server that ignores the
parameters terminates too.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import respx
from httpx import Request, Response

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.client.drive import PAGE_SIZE, _take_page
from xmagic.config import DEFAULT_BASE_URL

KB_URL = f"{DEFAULT_BASE_URL}/knowledge-bases"


def _folder(i: int) -> dict[str, Any]:
    return {"id": f"kb-{i}", "name": f"folder {i}", "user_defined_tags": []}


def _file(i: int, folder: str) -> dict[str, Any]:
    return {"id": f"ds-{i}", "knowledge_base_id": folder, "type": "data_source"}


def _paged(items: list[dict[str, Any]]) -> Any:
    """A side effect that pages ``items`` exactly as the platform does."""

    def respond(request: Request) -> Response:
        page = int(request.url.params.get("page", 0))
        size = int(request.url.params.get("page_size", 20))
        start = page * size
        return Response(
            200,
            json={
                "data": {
                    "results": items[start : start + size],
                    "pagination": {"page": page, "page_size": size, "total_count": len(items)},
                }
            },
        )

    return respond


def _pages_requested(route: respx.Route) -> list[tuple[str | None, str | None]]:
    return [
        (call.request.url.params.get("page"), call.request.url.params.get("page_size"))
        for call in route.calls
    ]


@pytest.fixture
def client() -> Iterator[XMagicClient]:
    c = XMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL)
    yield c
    c.close()


@respx.mock
def test_list_folders_walks_every_page_at_the_maximum_size(client: XMagicClient) -> None:
    route = respx.get(KB_URL).mock(side_effect=_paged([_folder(i) for i in range(450)]))

    folders = client.drive.list_folders()

    assert [f.id for f in folders] == [f"kb-{i}" for i in range(450)]
    assert _pages_requested(route) == [("0", "200"), ("1", "200"), ("2", "200")]
    assert PAGE_SIZE == 200


@respx.mock
def test_list_files_walks_every_page_and_keeps_the_parent(client: XMagicClient) -> None:
    route = respx.get(KB_URL).mock(side_effect=_paged([_file(i, "kb-1") for i in range(201)]))

    files = client.drive.list_files("kb-1")

    assert len(files) == 201
    assert files[-1].id == "ds-200"
    assert _pages_requested(route) == [("0", "200"), ("1", "200")]
    assert {call.request.url.params.get("parent_kb_id") for call in route.calls} == {"kb-1"}


@respx.mock
def test_an_exact_multiple_does_not_request_an_empty_page(client: XMagicClient) -> None:
    route = respx.get(KB_URL).mock(side_effect=_paged([_folder(i) for i in range(400)]))

    assert len(client.drive.list_folders()) == 400
    assert route.call_count == 2


@respx.mock
def test_a_short_first_page_is_the_only_request(client: XMagicClient) -> None:
    route = respx.get(KB_URL).mock(side_effect=_paged([_folder(1), _folder(2)]))

    assert [f.id for f in client.drive.list_folders()] == ["kb-1", "kb-2"]
    assert route.call_count == 1


@respx.mock
def test_a_body_without_pagination_is_one_page(client: XMagicClient) -> None:
    route = respx.get(KB_URL).mock(
        return_value=Response(200, json={"data": {"results": [_folder(1)]}})
    )

    assert [f.id for f in client.drive.list_folders()] == ["kb-1"]
    assert route.call_count == 1


@respx.mock
def test_a_server_that_ignores_the_parameters_still_terminates(client: XMagicClient) -> None:
    # The platform before 2026-09-15 as we understood it: always page 0 of 20,
    # whatever we send. The walk must end rather than spin.
    same_page = {
        "data": {
            "results": [_folder(i) for i in range(20)],
            "pagination": {"page": 0, "page_size": 20, "total_count": 44},
        }
    }
    route = respx.get(KB_URL).mock(return_value=Response(200, json=same_page))

    folders = client.drive.list_folders()

    assert route.call_count == 3  # 20 + 20 + 20 >= 44, then stop
    assert len(folders) == 60


def test_take_page_stops_on_an_empty_page() -> None:
    items: list[Any] = []
    body = {"data": {"results": [], "pagination": {"page": 5, "page_size": 200, "total_count": 9}}}
    assert _take_page(items, body, 5) is None
    assert items == []


@respx.mock
async def test_async_listing_walks_the_same_pages() -> None:
    route = respx.get(KB_URL).mock(side_effect=_paged([_folder(i) for i in range(250)]))
    async with AsyncXMagicClient(api_key="test-key", base_url=DEFAULT_BASE_URL) as client:
        folders = await client.drive.list_folders()
        files = await client.drive.list_files("kb-0")

    assert len(folders) == 250
    assert files == []  # the fake data are folders, and the filter is by shape
    assert _pages_requested(route)[:2] == [("0", "200"), ("1", "200")]


@respx.mock
def test_total_count_wins_over_a_server_that_serves_fewer_than_it_echoes(
    client: XMagicClient,
) -> None:
    # A silent cap below the echoed page_size must not end the walk early:
    # the server's own total says more exist. Never observed live; the
    # account that measured the parameters had 44 folders, so a full page of
    # 200 was never seen.
    items = [_folder(i) for i in range(250)]

    def capped(request: Request) -> Response:
        page = int(request.url.params.get("page", 0))
        size = int(request.url.params.get("page_size", 20))
        start = page * 100
        return Response(
            200,
            json={
                "data": {
                    "results": items[start : start + 100],
                    "pagination": {"page": page, "page_size": size, "total_count": 250},
                }
            },
        )

    route = respx.get(KB_URL).mock(side_effect=capped)

    assert len(client.drive.list_folders()) == 250
    assert route.call_count == 3


def test_take_page_with_no_stop_evidence_is_one_page() -> None:
    # A pagination block with neither total_count nor page_size gives the walk
    # nothing to end on, so it must not ask for a second page.
    items: list[Any] = []
    body = {"data": {"results": [_folder(1)], "pagination": {"page": 0}}}
    assert _take_page(items, body, 0) is None
    assert len(items) == 1
