"""``xmagic workspaces`` behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL

WORKSPACES_URL = f"{DEFAULT_BASE_URL}/users/workspaces"
SWITCH_URL = f"{DEFAULT_BASE_URL}/users/workspaces/switch"

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))


@respx.mock
def test_workspace_lists_accessible_workspaces() -> None:
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "w1",
                    "workspaces": [
                        {"id": "w1", "name": "Alpha", "role": "admin"},
                        {"id": "w2", "name": "Beta", "role": "member"},
                    ],
                }
            },
        )
    )

    result = runner.invoke(app, ["workspaces"])

    assert result.exit_code == 0, result.output
    assert "Alpha" in result.output
    assert "w1" in result.output
    assert "admin" in result.output


@respx.mock
def test_workspace_switches_by_id_option() -> None:
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "w1",
                    "workspaces": [
                        {"id": "w1", "name": "Alpha", "role": "admin"},
                        {"id": "w2", "name": "Beta", "role": "member"},
                    ],
                }
            },
        )
    )
    switch = respx.post(SWITCH_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "w2",
                    "workspaces": [
                        {"id": "w1", "name": "Alpha", "role": "admin"},
                        {"id": "w2", "name": "Beta", "role": "member"},
                    ],
                }
            },
        )
    )

    result = runner.invoke(app, ["workspaces", "--id", "w2"])

    assert result.exit_code == 0, result.output
    assert "Switched current workspace to w2" in result.output
    assert switch.calls.last.request.url.params["workspace_id"] == "w2"


@respx.mock
def test_workspace_switches_by_positional_name() -> None:
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "w1",
                    "workspaces": [
                        {"id": "w1", "name": "Alpha", "role": "admin"},
                        {"id": "w2", "name": "Beta", "role": "member"},
                    ],
                }
            },
        )
    )
    switch = respx.post(SWITCH_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "w2",
                    "workspaces": [
                        {"id": "w1", "name": "Alpha", "role": "admin"},
                        {"id": "w2", "name": "Beta", "role": "member"},
                    ],
                }
            },
        )
    )

    result = runner.invoke(app, ["workspaces", "Beta"])

    assert result.exit_code == 0, result.output
    assert switch.calls.last.request.url.params["workspace_id"] == "w2"


@respx.mock
def test_workspace_name_ambiguity_errors() -> None:
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "w1",
                    "workspaces": [
                        {"id": "w1", "name": "Alpha", "role": "admin"},
                        {"id": "w2", "name": "Alpha", "role": "member"},
                    ],
                }
            },
        )
    )

    result = runner.invoke(app, ["workspaces", "Alpha"])

    assert result.exit_code == 1
    assert "ambiguous" in result.output
