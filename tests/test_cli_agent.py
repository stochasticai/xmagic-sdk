"""``xmagic agents`` behavior tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from xmagic.cli.main import app
from xmagic.config import DEFAULT_BASE_URL

AGENTS_URL = f"{DEFAULT_BASE_URL}/agents"
AGENT_DETAIL_URL = f"{DEFAULT_BASE_URL}/agents/agent-1"
WORKSPACES_URL = f"{DEFAULT_BASE_URL}/users/workspaces"
SWITCH_WORKSPACE_URL = f"{DEFAULT_BASE_URL}/users/workspaces/switch"
TEMP_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/configs/temporary"
EXPORT_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/configs/cfg-1/config"
PATCH_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/configs/temporary"
SAVE_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/configs"
DEPLOY_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/configs/saved-cfg-1/deploy"
PHONES_URL = f"{DEFAULT_BASE_URL}/phones"
PHONE_ASSOC_URL = f"{DEFAULT_BASE_URL}/phones/phone-1"
JOBS_URL = f"{DEFAULT_BASE_URL}/agents/agent-1/configs/cfg-1/jobs"

runner = CliRunner()


def _export_payload() -> dict[str, Any]:
    return {
        "config_values": {},
        "subagents": [],
        "agent_level_tools": [],
        "agent_level_quick_actions": [],
    }


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XMAGIC_API_KEY", "test-key")
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(tmp_path / "none.toml"))
    respx.get(AGENTS_URL).mock(
        return_value=Response(
            200,
            json={"data": [{"id": "agent-1", "name": "Sales Agent"}]},
        )
    )
    respx.get(AGENT_DETAIL_URL).mock(
        return_value=Response(200, json={"data": {"id": "agent-1", "organization_id": "org-1"}})
    )
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200,
            json={"data": {"current_workspace_id": "org-1", "workspaces": []}},
        )
    )
    respx.post(SWITCH_WORKSPACE_URL).mock(return_value=Response(200, json={"data": {}}))


@respx.mock
def test_agent_lists_agents() -> None:
    respx.get(AGENTS_URL).mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {"id": "agent-1", "name": "Sales Agent", "role": "admin"},
                    {"id": "agent-2", "name": "Support Agent", "role": "member"},
                ]
            },
        )
    )

    result = runner.invoke(app, ["agents"])

    assert result.exit_code == 0, result.output
    assert "Sales Agent" in result.output
    assert "agent-1" in result.output


@respx.mock
def test_agent_config_skips_patch_when_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("xmagic.cli.agents._edit_file", lambda path: None)

    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(EXPORT_URL).mock(return_value=Response(200, json=_export_payload()))
    patch_route = respx.patch(PATCH_URL).mock(return_value=Response(200, json={"success": True}))

    result = runner.invoke(app, ["agents", "config", "--agent", "agent-1"])

    assert result.exit_code == 0, result.output
    assert "No changes detected" in result.output
    assert not patch_route.called


@respx.mock
def test_agent_config_patches_edited_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    def edit_file(path: Path) -> None:
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "config_values:\n  welcome_message: hi\n", encoding="utf-8")

    monkeypatch.setattr("xmagic.cli.agents._edit_file", edit_file)

    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(EXPORT_URL).mock(return_value=Response(200, json=_export_payload()))
    patch_route = respx.patch(PATCH_URL).mock(return_value=Response(200, json={"success": True}))

    result = runner.invoke(app, ["agents", "config", "--agent", "agent-1"])

    assert result.exit_code == 0, result.output
    assert "Updated temporary config for agent agent-1" in result.output
    sent = patch_route.calls.last.request.read().decode()
    assert '"config_json"' in sent
    assert '"welcome_message":"hi"' in sent


@respx.mock
def test_agent_config_uses_default_agent_from_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[xmagic]",
                'api_key = "test-key"',
                f'base_url = "{DEFAULT_BASE_URL}"',
                'default_agent_id = "agent-1"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(config_path))
    monkeypatch.setattr("xmagic.cli.agents._edit_file", lambda path: None)

    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(EXPORT_URL).mock(return_value=Response(200, json=_export_payload()))

    result = runner.invoke(app, ["agents", "config"])

    assert result.exit_code == 0, result.output
    assert "No changes detected" in result.output


# ── deploy tests ──────────────────────────────────────────────────────────────


def _phones_payload(phones: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": {"org_phone_numbers": phones, "shared_phone_numbers": []}}


def _saved_config_payload() -> dict[str, Any]:
    return {"data": {"id": "saved-cfg-1", "version_name": "v1"}}


@respx.mock
def test_deploy_no_phones_deploys_cleanly() -> None:
    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(PHONES_URL).mock(return_value=Response(200, json=_phones_payload([])))
    save_route = respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    deploy_route = respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))

    result = runner.invoke(app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"])

    assert result.exit_code == 0, result.output
    assert "Deployed version 'v1'" in result.output
    assert save_route.called
    assert deploy_route.called


@respx.mock
def test_deploy_skips_phone_when_user_enters_zero() -> None:
    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(PHONES_URL).mock(
        return_value=Response(
            200,
            json=_phones_payload(
                [
                    {
                        "id": "phone-1",
                        "phone_number": "+14155551234",
                        "persona_id_associated_to": None,
                    },
                ]
            ),
        )
    )
    respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))
    assoc_route = respx.post(PHONE_ASSOC_URL).mock(
        return_value=Response(200, json={"success": True})
    )

    # user inputs "0" to skip phone selection
    result = runner.invoke(
        app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"], input="0\n"
    )

    assert result.exit_code == 0, result.output
    assert not assoc_route.called
    assert "Deployed version 'v1'" in result.output


@respx.mock
def test_deploy_attaches_phone_no_subagents() -> None:
    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(PHONES_URL).mock(
        return_value=Response(
            200,
            json=_phones_payload(
                [
                    {
                        "id": "phone-1",
                        "phone_number": "+14155551234",
                        "persona_id_associated_to": None,
                    },
                ]
            ),
        )
    )
    respx.get(JOBS_URL).mock(return_value=Response(200, json={"data": []}))
    assoc_route = respx.post(PHONE_ASSOC_URL).mock(
        return_value=Response(200, json={"success": True})
    )
    respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))

    # select phone 1, no subagent prompt (empty list)
    result = runner.invoke(
        app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"], input="1\n"
    )

    assert result.exit_code == 0, result.output
    assert assoc_route.called
    sent = assoc_route.calls.last.request.read().decode()
    assert '"persona_id_associated_to":"agent-1"' in sent
    assert '"subagent_id_associated_to":null' in sent
    assert "Phone number associated" in result.output
    assert "Deployed version 'v1'" in result.output


@respx.mock
def test_deploy_attaches_phone_with_subagent() -> None:
    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(PHONES_URL).mock(
        return_value=Response(
            200,
            json=_phones_payload(
                [
                    {
                        "id": "phone-1",
                        "phone_number": "+14155551234",
                        "persona_id_associated_to": None,
                    },
                ]
            ),
        )
    )
    respx.get(JOBS_URL).mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "sub-1",
                        "name": "Sales Bot",
                        "id_shared_between_versions": "sub-shared-1",
                    },
                ]
            },
        )
    )
    assoc_route = respx.post(PHONE_ASSOC_URL).mock(
        return_value=Response(200, json={"success": True})
    )
    respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))

    # select phone 1, then subagent 1
    result = runner.invoke(
        app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"], input="1\n1\n"
    )

    assert result.exit_code == 0, result.output
    assert assoc_route.called
    sent = assoc_route.calls.last.request.read().decode()
    assert '"subagent_id_associated_to":"sub-shared-1"' in sent
    assert "Deployed version 'v1'" in result.output


@respx.mock
def test_deploy_requires_agent_id() -> None:
    result = runner.invoke(app, ["agents", "deploy"])
    assert result.exit_code != 0


@respx.mock
def test_deploy_uses_default_agent_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[xmagic]",
                'api_key = "test-key"',
                f'base_url = "{DEFAULT_BASE_URL}"',
                'default_agent_id = "agent-1"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XMAGIC_CONFIG_PATH", str(config_path))

    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(PHONES_URL).mock(return_value=Response(200, json=_phones_payload([])))
    respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))

    result = runner.invoke(app, ["agents", "deploy", "--version", "v1"])

    assert result.exit_code == 0, result.output
    assert "Deployed version 'v1' for agent agent-1" in result.output


@respx.mock
def test_deploy_voice_disabled_skips_phone_step() -> None:
    """If /phones returns 501 (voice not enabled), the deploy should still succeed."""
    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.get(PHONES_URL).mock(return_value=Response(501, json={"error": "NOT_CONFIGURED"}))
    respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))

    result = runner.invoke(app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"])

    assert result.exit_code == 0, result.output
    assert "Deployed version 'v1'" in result.output


@respx.mock
def test_deploy_rejects_agent_from_another_workspace() -> None:
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "current_workspace_id": "org-1",
                    "workspaces": [
                        {"id": "org-1", "name": "Current Org"},
                        {"id": "org-2", "name": "Agent Org"},
                    ],
                }
            },
        )
    )
    respx.get(AGENT_DETAIL_URL).mock(
        return_value=Response(200, json={"data": {"id": "agent-1", "organization_id": "org-2"}})
    )

    result = runner.invoke(app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"])

    assert result.exit_code == 1
    assert "current workspace" in result.output
    assert not respx.calls.call_count == 0
    assert not respx.calls.last.request.url.path.endswith("/switch")


@respx.mock
def test_deploy_rejects_when_current_workspace_is_unknown() -> None:
    respx.get(WORKSPACES_URL).mock(
        return_value=Response(
            200, json={"data": {"workspaces": [{"id": "org-1", "name": "Current Org"}]}}
        )
    )

    result = runner.invoke(app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1"])

    assert result.exit_code == 1
    assert "could not be determined" in result.output
    assert not respx.calls.last.request.url.path.endswith("/switch")


@respx.mock
def test_deploy_no_phone_is_non_interactive() -> None:
    respx.get(TEMP_URL).mock(
        return_value=Response(200, json={"data": {"id": "cfg-1", "organization_id": "org-1"}})
    )
    respx.post(SAVE_URL).mock(return_value=Response(200, json=_saved_config_payload()))
    respx.post(DEPLOY_URL).mock(return_value=Response(200, json={"success": True}))

    result = runner.invoke(
        app, ["agents", "deploy", "--agent", "agent-1", "--version", "v1", "--no-phone"]
    )

    assert result.exit_code == 0, result.output
