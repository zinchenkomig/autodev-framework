"""DB helpers shared by the worker loops: logging and status transitions."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.models import AgentLog, Task, TaskTransition

logger = logging.getLogger(__name__)


class Store:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get(self, task_id: uuid.UUID) -> Task | None:
        async with self.session_factory() as session:
            return await session.get(Task, task_id)

    async def log(
        self,
        task_id: uuid.UUID | None,
        message: str,
        *,
        level: str = "info",
        details: str | None = None,
        agent: str = "worker",
    ) -> None:
        async with self.session_factory() as session:
            session.add(AgentLog(agent_id=agent, task_id=task_id, level=level, message=message, details=details))
            await session.commit()

    async def update(self, task_id: uuid.UUID, **fields: Any) -> Task | None:
        async with self.session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return None
            for key, value in fields.items():
                setattr(task, key, value)
            await session.commit()
            return task

    async def transition(
        self,
        task_id: uuid.UUID,
        to: str,
        *,
        reason: str | None = None,
        by: str = "worker",
        only_from: set[str] | frozenset[str] | None = None,
        **fields: Any,
    ) -> Task | None:
        """Move a task to status *to* and record it.

        With *only_from*, the move happens only if the task is currently in one
        of those statuses (guards against racing with a cancel from the UI).
        Returns the updated task, or None if it wasn't moved.
        """
        async with self.session_factory() as session:
            task = await session.get(Task, task_id, with_for_update=True)
            if task is None or (only_from is not None and task.status not in only_from):
                return None
            old = task.status
            for key, value in fields.items():
                setattr(task, key, value)
            if old != to:
                task.status = to
                task.status_changed_at = datetime.now(UTC)
                session.add(
                    TaskTransition(task_id=task.id, from_status=old, to_status=to, reason=reason, triggered_by=by)
                )
                text = f"📌 {old} → {to}" + (f" ({reason})" if reason else "")
                session.add(AgentLog(agent_id=by, task_id=task.id, level="transition", message=text))
            await session.commit()
            logger.info("task #%s %s → %s %s", task.ticket_number, old, to, reason or "")
            return task
