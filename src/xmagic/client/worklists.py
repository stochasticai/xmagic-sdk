"""Worklist task and recurring schedule operations.

Endpoints (base: https://api.xmagic.ai/xmagic-backend/v1):

- GET    /agents/{agent_id}/worklist
- GET    /agents/{agent_id}/worklist/{task_id}
- POST   /agents/{agent_id}/worklist
- PATCH  /agents/{agent_id}/worklist/{task_id}
- DELETE /agents/{agent_id}/worklist/{task_id}
- POST   /agents/{agent_id}/worklist/{task_id}/trigger
- POST   /agents/{agent_id}/worklist/{task_id}/rerun
- POST   /agents/{agent_id}/worklist/{task_id}/stop
- GET    /agents/{agent_id}/worklist/schedules/{schedule_id}
- PATCH  /agents/{agent_id}/worklist/schedules/{schedule_id}
- DELETE /agents/{agent_id}/worklist/schedules/{schedule_id}
- POST   /agents/{agent_id}/worklist/schedules/{schedule_id}/pause
- POST   /agents/{agent_id}/worklist/schedules/{schedule_id}/resume

The API returns a single page for list operations. Callers can use ``skip`` and
``limit`` explicitly; this resource does not silently fetch additional pages.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import secrets
from typing import Any

from xmagic.client.chats import AsyncChatsAPI, ChatsAPI
from xmagic.client.http import AsyncHttpTransport, HttpTransport
from xmagic.client.models import (
    RecurrencySchedule,
    WorklistTask,
    WorklistReviewAction,
    WorklistReviewResult,
    WorklistTaskPage,
    WorklistTaskStatus,
)


def _unwrap_data(body: dict[str, Any]) -> Any:
    return body.get("data", body)


def _base_path(agent_id: str) -> str:
    return f"/agents/{agent_id}/worklist"


def _task_path(agent_id: str, task_id: str = "") -> str:
    suffix = f"/{task_id}" if task_id else ""
    return f"{_base_path(agent_id)}{suffix}"


def _schedule_path(agent_id: str, schedule_id: str, action: str = "") -> str:
    suffix = f"/{action}" if action else ""
    return f"{_base_path(agent_id)}/schedules/{schedule_id}{suffix}"


def _list_params(
    *,
    status: WorklistTaskStatus | str | None,
    is_archived: bool | None,
    is_recurring: bool | None,
    creation_chat_id: str | None,
    skip: int,
    limit: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {"skip": skip, "limit": limit}
    if status is not None:
        params["status"] = getattr(status, "value", status)
    if is_archived is not None:
        params["is_archived"] = is_archived
    if is_recurring is not None:
        params["is_recurring"] = is_recurring
    if creation_chat_id is not None:
        params["creation_chat_id"] = creation_chat_id
    return params


def _wire_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_wire_value(item) for item in value]
    return value


def _wire_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _wire_value(payload)


def _task(body: dict[str, Any]) -> WorklistTask:
    data = _unwrap_data(body)
    if not isinstance(data, dict):
        raise ValueError("Unexpected worklist task response shape")
    return WorklistTask.model_validate(data)


def _schedule(body: dict[str, Any]) -> RecurrencySchedule:
    data = _unwrap_data(body)
    if not isinstance(data, dict):
        raise ValueError("Unexpected worklist schedule response shape")
    return RecurrencySchedule.model_validate(data)


def _review_follow_up_instruction(task: WorklistTask) -> str:
    return (
        f'You have to follow up on the worklist task ID "{task.id}" '
        f'with name "{task.name}". Please modify the existing task instead '
        "of creating a new one."
    )


def _validate_review(task: WorklistTask, message: str | None) -> str | None:
    if task.status != WorklistTaskStatus.NEEDS_REVIEW:
        raise ValueError(
            f"Worklist task {task.id} has status '{task.status.value}', not 'needs_review'."
        )
    normalized = message.strip() if message is not None else None
    if normalized and not task.run_chat_id:
        raise ValueError(
            f"Worklist task {task.id} has no run chat, so a follow-up message cannot be sent."
        )
    return normalized or None


class WorklistsAPI:
    """Synchronous worklist task and recurrence operations."""

    def __init__(self, transport: HttpTransport, chats: ChatsAPI | None = None) -> None:
        self._t = transport
        self._chats = chats or ChatsAPI(transport)

    def list(
        self,
        agent_id: str,
        *,
        status: WorklistTaskStatus | str | None = None,
        is_archived: bool | None = None,
        is_recurring: bool | None = None,
        creation_chat_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> WorklistTaskPage:
        """List one page of tasks, newest first."""
        body = self._t.request(
            "GET",
            _task_path(agent_id),
            params=_list_params(
                status=status,
                is_archived=is_archived,
                is_recurring=is_recurring,
                creation_chat_id=creation_chat_id,
                skip=skip,
                limit=limit,
            ),
        )
        data = _unwrap_data(body)
        if not isinstance(data, dict):
            raise ValueError("Unexpected worklist list response shape")
        return WorklistTaskPage.model_validate(data)

    def get(self, agent_id: str, task_id: str) -> WorklistTask:
        """Get one task, including its execution metadata and output paths."""
        return _task(self._t.request("GET", _task_path(agent_id, task_id)))

    def create(self, agent_id: str, payload: dict[str, Any]) -> WorklistTask:
        """Create a task, optionally with a recurring schedule."""
        return _task(self._t.request("POST", _task_path(agent_id), json=_wire_payload(payload)))

    def update(self, agent_id: str, task_id: str, payload: dict[str, Any]) -> WorklistTask:
        """Patch a pending task or its archive/status fields."""
        return _task(
            self._t.request("PATCH", _task_path(agent_id, task_id), json=_wire_payload(payload))
        )

    def delete(self, agent_id: str, task_id: str) -> dict[str, Any]:
        """Delete a task and return the API's deletion marker."""
        return _unwrap_data(self._t.request("DELETE", _task_path(agent_id, task_id)))

    def trigger(self, agent_id: str, task_id: str) -> WorklistTask:
        """Enqueue a pending task for execution."""
        return _task(self._t.request("POST", _task_path(agent_id, f"{task_id}/trigger")))

    def review(
        self,
        agent_id: str,
        task_id: str,
        *,
        message: str | None = None,
        task: WorklistTask | None = None,
    ) -> WorklistReviewResult:
        """Review a ``needs_review`` task without interactive prompts.

        A blank message completes the task without another agent action. A
        non-empty message continues the task's existing run chat.
        """
        task = task or self.get(agent_id, task_id)
        if task.id != task_id:
            raise ValueError(f"Worklist task {task.id} does not match task id '{task_id}'.")
        message = _validate_review(task, message)
        if message:
            response = self._chats.query(
                agent_id,
                task.run_chat_id or "",
                message,
                message_id=secrets.token_hex(12),
                hidden_query=_review_follow_up_instruction(task),
                parse_response=True,
            )
            return WorklistReviewResult(
                task=task,
                action=WorklistReviewAction.FOLLOW_UP_SENT,
                query=response,
            )

        completed = self.update(agent_id, task_id, {"status": WorklistTaskStatus.COMPLETED})
        return WorklistReviewResult(
            task=completed,
            action=WorklistReviewAction.COMPLETED,
        )

    def rerun(self, agent_id: str, task_id: str) -> WorklistTask:
        """Clone and enqueue a completed, failed, or cancelled task."""
        return _task(self._t.request("POST", _task_path(agent_id, f"{task_id}/rerun")))

    def stop(self, agent_id: str, task_id: str) -> WorklistTask:
        """Cancel an in-progress task."""
        return _task(self._t.request("POST", _task_path(agent_id, f"{task_id}/stop")))

    def get_schedule(self, agent_id: str, schedule_id: str) -> RecurrencySchedule:
        """Get one recurring schedule."""
        return _schedule(self._t.request("GET", _schedule_path(agent_id, schedule_id)))

    def update_schedule(
        self, agent_id: str, schedule_id: str, payload: dict[str, Any]
    ) -> RecurrencySchedule:
        """Patch a recurring schedule."""
        return _schedule(
            self._t.request(
                "PATCH",
                _schedule_path(agent_id, schedule_id),
                json=_wire_payload(payload),
            )
        )

    def delete_schedule(self, agent_id: str, schedule_id: str) -> dict[str, Any]:
        """Deactivate a recurring schedule."""
        return _unwrap_data(self._t.request("DELETE", _schedule_path(agent_id, schedule_id)))

    def pause_schedule(self, agent_id: str, schedule_id: str) -> RecurrencySchedule:
        """Pause a recurring schedule."""
        return _schedule(self._t.request("POST", _schedule_path(agent_id, schedule_id, "pause")))

    def resume_schedule(self, agent_id: str, schedule_id: str) -> RecurrencySchedule:
        """Resume a paused recurring schedule."""
        return _schedule(self._t.request("POST", _schedule_path(agent_id, schedule_id, "resume")))


class AsyncWorklistsAPI:
    """Async mirror of :class:`WorklistsAPI`."""

    def __init__(self, transport: AsyncHttpTransport, chats: AsyncChatsAPI | None = None) -> None:
        self._t = transport
        self._chats = chats or AsyncChatsAPI(transport)

    async def list(
        self,
        agent_id: str,
        *,
        status: WorklistTaskStatus | str | None = None,
        is_archived: bool | None = None,
        is_recurring: bool | None = None,
        creation_chat_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> WorklistTaskPage:
        """List one page of tasks, newest first."""
        body = await self._t.request(
            "GET",
            _task_path(agent_id),
            params=_list_params(
                status=status,
                is_archived=is_archived,
                is_recurring=is_recurring,
                creation_chat_id=creation_chat_id,
                skip=skip,
                limit=limit,
            ),
        )
        data = _unwrap_data(body)
        if not isinstance(data, dict):
            raise ValueError("Unexpected worklist list response shape")
        return WorklistTaskPage.model_validate(data)

    async def get(self, agent_id: str, task_id: str) -> WorklistTask:
        """Get one task, including its execution metadata and output paths."""
        return _task(await self._t.request("GET", _task_path(agent_id, task_id)))

    async def create(self, agent_id: str, payload: dict[str, Any]) -> WorklistTask:
        """Create a task, optionally with a recurring schedule."""
        return _task(
            await self._t.request("POST", _task_path(agent_id), json=_wire_payload(payload))
        )

    async def update(self, agent_id: str, task_id: str, payload: dict[str, Any]) -> WorklistTask:
        """Patch a pending task or its archive/status fields."""
        return _task(
            await self._t.request(
                "PATCH", _task_path(agent_id, task_id), json=_wire_payload(payload)
            )
        )

    async def delete(self, agent_id: str, task_id: str) -> dict[str, Any]:
        """Delete a task and return the API's deletion marker."""
        return _unwrap_data(await self._t.request("DELETE", _task_path(agent_id, task_id)))

    async def trigger(self, agent_id: str, task_id: str) -> WorklistTask:
        """Enqueue a pending task for execution."""
        return _task(await self._t.request("POST", _task_path(agent_id, f"{task_id}/trigger")))

    async def review(
        self,
        agent_id: str,
        task_id: str,
        *,
        message: str | None = None,
        task: WorklistTask | None = None,
    ) -> WorklistReviewResult:
        """Async mirror of :meth:`WorklistsAPI.review`."""
        task = task or await self.get(agent_id, task_id)
        if task.id != task_id:
            raise ValueError(f"Worklist task {task.id} does not match task id '{task_id}'.")
        message = _validate_review(task, message)
        if message:
            response = await self._chats.query(
                agent_id,
                task.run_chat_id or "",
                message,
                message_id=secrets.token_hex(12),
                hidden_query=_review_follow_up_instruction(task),
                parse_response=True,
            )
            return WorklistReviewResult(
                task=task,
                action=WorklistReviewAction.FOLLOW_UP_SENT,
                query=response,
            )

        completed = await self.update(agent_id, task_id, {"status": WorklistTaskStatus.COMPLETED})
        return WorklistReviewResult(
            task=completed,
            action=WorklistReviewAction.COMPLETED,
        )

    async def rerun(self, agent_id: str, task_id: str) -> WorklistTask:
        """Clone and enqueue a completed, failed, or cancelled task."""
        return _task(await self._t.request("POST", _task_path(agent_id, f"{task_id}/rerun")))

    async def stop(self, agent_id: str, task_id: str) -> WorklistTask:
        """Cancel an in-progress task."""
        return _task(await self._t.request("POST", _task_path(agent_id, f"{task_id}/stop")))

    async def get_schedule(self, agent_id: str, schedule_id: str) -> RecurrencySchedule:
        """Get one recurring schedule."""
        return _schedule(await self._t.request("GET", _schedule_path(agent_id, schedule_id)))

    async def update_schedule(
        self, agent_id: str, schedule_id: str, payload: dict[str, Any]
    ) -> RecurrencySchedule:
        """Patch a recurring schedule."""
        return _schedule(
            await self._t.request(
                "PATCH",
                _schedule_path(agent_id, schedule_id),
                json=_wire_payload(payload),
            )
        )

    async def delete_schedule(self, agent_id: str, schedule_id: str) -> dict[str, Any]:
        """Deactivate a recurring schedule."""
        return _unwrap_data(await self._t.request("DELETE", _schedule_path(agent_id, schedule_id)))

    async def pause_schedule(self, agent_id: str, schedule_id: str) -> RecurrencySchedule:
        """Pause a recurring schedule."""
        return _schedule(
            await self._t.request("POST", _schedule_path(agent_id, schedule_id, "pause"))
        )

    async def resume_schedule(self, agent_id: str, schedule_id: str) -> RecurrencySchedule:
        """Resume a paused recurring schedule."""
        return _schedule(
            await self._t.request("POST", _schedule_path(agent_id, schedule_id, "resume"))
        )
