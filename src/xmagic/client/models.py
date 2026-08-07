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


class Workspace(BaseModel):
    """A workspace (organization) accessible to the current user."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    role: str | None = None
    status: str | None = None
    plan: str | None = None


class WorkspaceState(BaseModel):
    """Workspace listing payload including current selection."""

    model_config = ConfigDict(extra="allow")

    current_workspace_id: str | None = None
    workspaces: list[Workspace] = Field(default_factory=list)


class AgentSummary(BaseModel):
    """Minimal agent shape for list operations."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    role: str | None = None


class SavedConfig(BaseModel):
    """Result of ``POST /agents/{agent_id}/configs`` — the saved non-temporary config."""

    model_config = ConfigDict(extra="allow")

    id: str


class PhoneSummary(BaseModel):
    """A phone number available in the current organisation."""

    model_config = ConfigDict(extra="allow")

    id: str
    phone_number: str
    persona_id_associated_to: str | None = None
    subagent_id_associated_to: str | None = None


class SubagentSummary(BaseModel):
    """Minimal subagent shape returned by ``GET /agents/{id}/configs/{cfg}/jobs``."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    id_shared_between_versions: str | None = None
