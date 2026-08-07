"""YAML codec for agent configuration editing.

CLI/editor interactions use YAML only. Backend transport remains JSON.
"""

from __future__ import annotations

from typing import Any

import yaml

REQUIRED_TOP_LEVEL_KEYS = (
    "config_values",
    "subagents",
    "agent_level_tools",
    "agent_level_quick_actions",
)


def _normalize_config_top_level_keys(config_json: dict[str, Any]) -> dict[str, Any]:
    """Translate API-key transformed top-level keys back to SDK shape.

    The backend applies a response key transform for API-key requests that can
    rename ``subagents`` to ``jobs``. Keep accepting that wire shape, but
    normalize back to ``subagents`` internally.
    """
    normalized = dict(config_json)
    if "subagents" not in normalized and "jobs" in normalized:
        normalized["subagents"] = normalized.pop("jobs")
    return normalized


def json_to_yaml(config_json: dict[str, Any]) -> str:
    """Render backend JSON as human-editable YAML."""
    normalized = _normalize_config_top_level_keys(config_json)
    validate_config_json(normalized)
    return yaml.safe_dump(
        normalized,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def yaml_to_json(yaml_text: str) -> dict[str, Any]:
    """Parse YAML into backend-compatible JSON payload."""
    payload = yaml.safe_load(yaml_text)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Configuration YAML must decode to a top-level mapping/object")
    payload = _normalize_config_top_level_keys(payload)
    validate_config_json(payload)
    return payload


def validate_config_json(config_json: dict[str, Any]) -> None:
    """Ensure required top-level keys exist before backend PATCH."""
    config_json = _normalize_config_top_level_keys(config_json)
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in config_json]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Configuration is missing required key(s): {names}")
