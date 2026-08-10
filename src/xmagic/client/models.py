"""Pydantic models for xMagic API entities and streaming events."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatType(StrEnum):
    """UI context a chat belongs to."""

    PLAYGROUND = "playground"
    CONFIGURATION = "configuration"
    INTERACT = "interact"
    STANDARD = "standard"


class Chat(BaseModel):
    """A conversation session with an agent."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str | None = None
    chat_type: ChatType | None = None
    agent_id: str | None = None


class QueryResponse(BaseModel):
    """Synchronous (non-streaming) query result."""

    model_config = ConfigDict(extra="allow")

    text: str
    message_id: str | None = None


class WorklistReviewAction(StrEnum):
    """Action taken when a worklist task is reviewed."""

    COMPLETED = "completed"
    FOLLOW_UP_SENT = "follow_up_sent"


class Message(BaseModel):
    """A stored query/response pair.

    ``output_assets`` maps an output id to its S3 path (confirmed live
    2026-07-31 via ``GET .../message/{message_id}``).
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    query: str | None = None
    response: str | None = None
    output_assets: dict[str, str] = Field(default_factory=dict)
    downloadable_output: dict[str, str] = Field(default_factory=dict)


class WorklistTaskStatus(StrEnum):
    """Lifecycle status of a background worklist task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduleStatus(StrEnum):
    """Lifecycle status of a recurring worklist schedule."""

    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"


class RecurrenceFrequency(StrEnum):
    """Supported recurrence frequencies for worklist schedules."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class RecurrenceConfig(BaseModel):
    """Recurrence configuration returned by the worklist API."""

    model_config = ConfigDict(extra="allow")

    frequency: RecurrenceFrequency
    interval: int = 1
    days_of_week: list[int] | None = None
    time_of_day: str | None = None
    timezone: str = "UTC"
    end_date: str | None = None
    max_occurrences: int | None = None


class WorklistTask(BaseModel):
    """A background task and its execution metadata."""

    model_config = ConfigDict(extra="allow")

    id: str
    agent_id: str | None = None
    persona_id: str | None = None
    name: str
    detailed_description: str
    input_s3_file_paths: list[str] = Field(default_factory=list)
    creation_chat_id: str | None = None
    created_by: str | None = None
    user_type: str | None = None
    created_by_name: str | None = None
    created_by_email: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    run_chat_id: str | None = None
    run_message_ids: list[str] = Field(default_factory=list)
    status: WorklistTaskStatus
    started_execution_at: str | None = None
    finished_execution_at: str | None = None
    error_if_any: str | None = None
    output_s3_file_paths: list[str] = Field(default_factory=list)
    is_scheduled: bool = False
    scheduled_at: str | None = None
    is_archived: bool = False
    recurrency_schedule_id: str | None = None
    recurrence: RecurrenceConfig | None = None
    schedule_status: ScheduleStatus | None = None
    schedule_total_runs: int | None = None
    schedule_last_run_at: str | None = None


class WorklistTaskPage(BaseModel):
    """One paginated page returned by the worklist list endpoint."""

    model_config = ConfigDict(extra="allow")

    tasks: list[WorklistTask] = Field(default_factory=list)
    total: int = 0
    skip: int = 0
    limit: int = 50


class WorklistReviewResult(BaseModel):
    """Result of reviewing a task that is waiting for user input."""

    task: WorklistTask
    action: WorklistReviewAction
    query: QueryResponse | None = None


class RecurrencySchedule(BaseModel):
    """A recurring worklist schedule."""

    model_config = ConfigDict(extra="allow")

    id: str
    agent_id: str | None = None
    persona_id: str | None = None
    name: str
    detailed_description: str
    input_s3_file_paths: list[str] = Field(default_factory=list)
    creation_chat_id: str | None = None
    created_by: str | None = None
    created_by_name: str | None = None
    created_by_email: str | None = None
    user_type: str | None = None
    recurrence: RecurrenceConfig
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    total_runs: int = 0
    last_run_at: str | None = None
    next_task_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UploadedFile(BaseModel):
    """Result of POST /uploaded-files."""

    model_config = ConfigDict(extra="allow")

    id: str
    filename: str | None = None


class StreamEvent(BaseModel):
    """A Server-Sent Event emitted during a streaming query.

    Confirmed against a live agent (2026-07-31): SSE frames carry no
    ``event:`` field (all arrive as the default ``message`` event), and each
    ``data:`` payload is a flat JSON object with the token type at
    ``payload["type"]`` and the text at ``payload["text"]``. The stream ends
    with the literal sentinel frame ``data: [DONE]``, surfaced here as a
    synthetic ``type="done"`` event.

    Observed live in a single streaming turn: ``metadata`` (carries
    ``message_id`` under ``raw["data"]``), ``response`` (incremental text),
    and ``end_response`` (terminal marker, empty text). The remaining
    literal members (``reasoning``, ``end_reasoning``,
    ``fast_response_simulation``, ``live_update``, ``ping``, ``error``,
    ``token_usage``) come from the backend's ``TokenType`` enum
    (xmagic_shared/src/shared/models/model_response_schema.py).
    """

    type: Literal[
        "reasoning",
        "end_reasoning",
        "fast_response_simulation",
        "response",
        "end_response",
        "live_update",
        "ping",
        "error",
        "token_usage",
        "metadata",
        "done",
    ]
    text: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class DriveFolder(BaseModel):
    """A knowledge-base folder in xMagic Drive."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None


class DriveFile(BaseModel):
    """A file within a Drive folder."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str | None = None
    knowledge_base_id: str | None = None
