"""YAML codec for worklist task and recurring schedule editing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import yaml

_CREATE_KEYS = {
    "name",
    "detailed_description",
    "input_s3_file_paths",
    "is_scheduled",
    "scheduled_at",
    "status",
    "recurrence",
}
_UPDATE_KEYS = {
    "name",
    "detailed_description",
    "input_s3_file_paths",
    "status",
    "is_scheduled",
    "scheduled_at",
    "is_archived",
}
_SCHEDULE_UPDATE_KEYS = {
    "name",
    "detailed_description",
    "input_s3_file_paths",
    "recurrence",
}
_RECURRENCE_KEYS = {
    "frequency",
    "interval",
    "days_of_week",
    "time_of_day",
    "timezone",
    "end_date",
    "max_occurrences",
}
_ALLOWED_STATUSES = {"pending", "needs_review"}
_ALLOWED_FREQUENCIES = {"hourly", "daily", "weekly"}

CREATE_TEMPLATE = """# Worklist task to create.
# Non-scheduled tasks start immediately after saving.
# Set status to needs_review to create the task without starting it.
name: ""
detailed_description: ""
input_s3_file_paths: []
is_scheduled: false
scheduled_at: null
status: pending
# Optional recurring schedule. Set to null for a one-off task.
recurrence: null
"""

_EDIT_HEADER = """# Edit the fields below and save the file.
# Read-only fields such as id, status timestamps, run ids, and results are not shown.
# Set is_archived only after the task reaches completed, failed, or cancelled.
"""
_SCHEDULE_EDIT_HEADER = """# Edit the fields below and save the file.
# Read-only fields such as id, status, timestamps, and run counts are not shown.
"""


def _load_mapping(yaml_text: str, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(yaml_text)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"{label} YAML must decode to a top-level mapping/object")
    return payload


def _reject_unknown(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ValueError(f"{label} contains unsupported key(s): {names}")


def _iso_datetime(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value
    raise ValueError(f"{field_name} must be an ISO-8601 datetime or null")


def _validate_recurrence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("recurrence must be a mapping/object or null")
    _reject_unknown(value, _RECURRENCE_KEYS, "recurrence")
    frequency = value.get("frequency")
    if frequency not in _ALLOWED_FREQUENCIES:
        raise ValueError("recurrence.frequency must be one of: hourly, daily, weekly")

    interval = value.get("interval", 1)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise ValueError("recurrence.interval must be at least 1")

    days = value.get("days_of_week")
    if days is not None:
        if frequency != "weekly":
            raise ValueError("recurrence.days_of_week is only allowed for weekly recurrence")
        if not isinstance(days, list) or any(
            not isinstance(day, int) or isinstance(day, bool) or not 0 <= day <= 6 for day in days
        ):
            raise ValueError(
                "recurrence.days_of_week values must be integers from 0 (Mon) to 6 (Sun)"
            )

    time_of_day = value.get("time_of_day")
    if frequency in {"daily", "weekly"} and not time_of_day:
        raise ValueError(f"recurrence.time_of_day is required for {frequency} recurrence")
    if time_of_day is not None:
        if not isinstance(time_of_day, str):
            raise ValueError("recurrence.time_of_day must use HH:MM format")
        parts = time_of_day.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("recurrence.time_of_day must use HH:MM format")
        hour, minute = (int(part) for part in parts)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("recurrence.time_of_day must be between 00:00 and 23:59")

    end_date = _iso_datetime(value.get("end_date"), "recurrence.end_date")
    max_occurrences = value.get("max_occurrences")
    if end_date is not None and max_occurrences is not None:
        raise ValueError(
            "recurrence.end_date and recurrence.max_occurrences are mutually exclusive"
        )
    if max_occurrences is not None and (
        not isinstance(max_occurrences, int)
        or isinstance(max_occurrences, bool)
        or max_occurrences < 1
    ):
        raise ValueError("recurrence.max_occurrences must be at least 1")

    normalized = dict(value)
    normalized.setdefault("interval", 1)
    normalized.setdefault("timezone", "UTC")
    if "end_date" in normalized:
        normalized["end_date"] = end_date
    return normalized


def yaml_to_create_payload(yaml_text: str) -> dict[str, Any]:
    """Parse and validate the YAML scaffold used by ``worklists create``."""
    payload = _load_mapping(yaml_text, "Worklist create")
    _reject_unknown(payload, _CREATE_KEYS, "Worklist create")
    name = payload.get("name")
    description = payload.get("detailed_description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required and must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("detailed_description is required and must be a non-empty string")

    status = payload.get("status", "pending")
    if status not in _ALLOWED_STATUSES:
        raise ValueError("status must be pending or needs_review when creating a task")
    paths = payload.get("input_s3_file_paths", [])
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise ValueError("input_s3_file_paths must be a list of strings")
    is_scheduled = payload.get("is_scheduled", False)
    if not isinstance(is_scheduled, bool):
        raise ValueError("is_scheduled must be true or false")

    normalized = dict(payload)
    normalized["name"] = name
    normalized["detailed_description"] = description
    normalized["input_s3_file_paths"] = paths
    normalized["is_scheduled"] = is_scheduled
    normalized["scheduled_at"] = _iso_datetime(payload.get("scheduled_at"), "scheduled_at")
    normalized["status"] = status
    normalized["recurrence"] = _validate_recurrence(payload.get("recurrence"))
    return normalized


def task_to_edit_yaml(task: dict[str, Any]) -> str:
    """Render editable task fields as YAML while omitting read-only fields."""
    editable = {key: task.get(key) for key in _UPDATE_KEYS}
    return _EDIT_HEADER + yaml.safe_dump(
        editable,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def yaml_to_update_payload(yaml_text: str, original: dict[str, Any]) -> dict[str, Any]:
    """Parse an edited task YAML file and return only changed PATCH fields."""
    edited = _load_mapping(yaml_text, "Worklist edit")
    _reject_unknown(edited, _UPDATE_KEYS, "Worklist edit")
    if not edited:
        raise ValueError("Worklist edit must contain at least one editable field")

    normalized = dict(edited)
    if "input_s3_file_paths" in normalized:
        paths = normalized["input_s3_file_paths"]
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ValueError("input_s3_file_paths must be a list of strings")
    if "is_scheduled" in normalized and not isinstance(normalized["is_scheduled"], bool):
        raise ValueError("is_scheduled must be true or false")
    if "status" in normalized and normalized["status"] not in {
        "pending",
        "in_progress",
        "needs_review",
        "completed",
        "failed",
        "cancelled",
    }:
        raise ValueError("status is not a valid worklist task status")
    if "scheduled_at" in normalized:
        normalized["scheduled_at"] = _iso_datetime(normalized["scheduled_at"], "scheduled_at")

    changed: dict[str, Any] = {}
    for key, value in normalized.items():
        old_value = original.get(key)
        if key == "scheduled_at":
            old_value = _iso_datetime(old_value, "scheduled_at")
        if value != old_value:
            changed[key] = value
    if not changed:
        return {}
    return changed


def schedule_to_edit_yaml(schedule: dict[str, Any]) -> str:
    """Render editable recurring schedule fields as YAML."""
    editable = {key: schedule.get(key) for key in _SCHEDULE_UPDATE_KEYS}
    return _SCHEDULE_EDIT_HEADER + yaml.safe_dump(
        editable,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def yaml_to_schedule_update_payload(yaml_text: str, original: dict[str, Any]) -> dict[str, Any]:
    """Parse an edited schedule YAML file and return only changed PATCH fields."""
    edited = _load_mapping(yaml_text, "Worklist schedule edit")
    _reject_unknown(edited, _SCHEDULE_UPDATE_KEYS, "Worklist schedule edit")
    if not edited:
        raise ValueError("Worklist schedule edit must contain at least one editable field")

    normalized = dict(edited)
    if "name" in normalized and (
        not isinstance(normalized["name"], str) or not normalized["name"].strip()
    ):
        raise ValueError("name must be a non-empty string")
    if "detailed_description" in normalized and (
        not isinstance(normalized["detailed_description"], str)
        or not normalized["detailed_description"].strip()
    ):
        raise ValueError("detailed_description must be a non-empty string")
    if "input_s3_file_paths" in normalized:
        paths = normalized["input_s3_file_paths"]
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ValueError("input_s3_file_paths must be a list of strings")
    if "recurrence" in normalized:
        normalized["recurrence"] = _validate_recurrence(normalized["recurrence"])
        if normalized["recurrence"] is None:
            raise ValueError("recurrence is required for a schedule")

    changed: dict[str, Any] = {}
    for key, value in normalized.items():
        if value != original.get(key):
            changed[key] = value
    return changed
