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
    """A stored query/response pair."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    query: str | None = None
    response: str | None = None
    outputs: list[dict[str, Any]] = Field(default_factory=list)


class UploadedFile(BaseModel):
    """Result of POST /uploaded-files."""

    model_config = ConfigDict(extra="allow")

    id: str
    filename: str | None = None


class StreamEvent(BaseModel):
    """A Server-Sent Event emitted during a streaming query.

    Event types observed in the docs: ``reasoning``, ``response``,
    ``live_update``, and a ``[DONE]`` terminator (surfaced as type="done").
    """

    type: Literal["reasoning", "response", "live_update", "done"]
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
    name: str | None = None
    folder_id: str | None = None
