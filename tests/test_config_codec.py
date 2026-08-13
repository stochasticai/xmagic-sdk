"""Tests for JSON <-> YAML config translation helpers."""

from __future__ import annotations

import pytest

from xmagic.config_codec import json_to_yaml, yaml_to_json


def _payload() -> dict:
    return {
        "config_values": {"a": 1},
        "subagents": [],
        "agent_level_tools": [],
        "agent_level_quick_actions": [],
    }


def test_round_trip_yaml_conversion() -> None:
    encoded = json_to_yaml(_payload())
    decoded = yaml_to_json(encoded)
    assert decoded == _payload()


def test_missing_required_keys_errors() -> None:
    with pytest.raises(ValueError) as exc:
        yaml_to_json("config_values: {}\n")

    assert "missing required key" in str(exc.value).lower()
