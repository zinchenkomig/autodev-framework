"""DB helpers shared by the worker loops: logging and status transitions."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev import review
from autodev.core.models import AgentLog, Task, TaskArtifact, TaskTransition

logger = logging.getLogger(__name__)

#: Screenshots an agent may attach to one task, and the largest one kept.
MAX_SHOTS = 8
MAX_SHOT_BYTES = 5_000_000


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

    async def patch_metadata(self, task_id: uuid.UUID, change: Callable[[dict], None]) -> None:
        """Change a task's metadata in place under a row lock (other loops write other keys)."""
        async with self.session_factory() as session:
            task = await session.get(Task, task_id, with_for_update=True)
            if task is None:
                return
            metadata = dict(task.metadata_ or {})
            change(metadata)
            task.metadata_ = metadata
            await session.commit()

    async def attach_screenshots(self, task_id: uuid.UUID, files: Iterable[Path], label: str) -> bytes | None:
        """Keep an agent's PNG screenshots as the task's artifacts named «*label*: <file name>».

        Returns the first one kept, for the notification.
        """
        first = None
        async with self.session_factory() as session:
            for path in list(files)[:MAX_SHOTS]:
                content = path.read_bytes() if path.is_file() else b""
                if not content.startswith(b"\x89PNG") or len(content) > MAX_SHOT_BYTES:
                    continue
                first = first or content
                session.add(
                    TaskArtifact(
                        task_id=task_id,
                        kind="screenshot",
                        name=f"{label}: {path.stem}",
                        content=content,
                        content_type="image/png",
                    )
                )
            await session.commit()
        return first

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

    async def adopt_child_plan(self, child: Task) -> Task | None:
        """*child* is on stage: fold its change into its main task's check. Returns the main task."""
        if not child.parent_id:
            return None
        async with self.session_factory() as session:
            root = await session.get(Task, child.parent_id, with_for_update=True)
            if root is None:
                return None
            review.adopt_child_plan(root, child)
            await session.commit()
            return root
