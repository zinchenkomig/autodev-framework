"""Task queue for distributing work across agents.

Provides an async-first, database-backed interface for enqueuing, claiming,
and completing development tasks with priority ordering and dependency tracking.

Priority order (highest → lowest): critical > high > normal > low
Atomicity: uses SELECT ... FOR UPDATE SKIP LOCKED (PostgreSQL) or
           an equivalent optimistic-update approach (SQLite for tests).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.models import Priority, Task, TaskStatus

# Alias kept for backwards compatibility with agent subclasses.
QueuedTask = Task

logger = logging.getLogger(__name__)

# Priority ordering: lower number = higher priority
_PRIORITY_ORDER: dict[str, int] = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.NORMAL: 2,
    Priority.LOW: 3,
}

_PRIORITY_CASE = case(
    (Task.priority == Priority.CRITICAL, 0),
    (Task.priority == Priority.HIGH, 1),
    (Task.priority == Priority.NORMAL, 2),
    (Task.priority == Priority.LOW, 3),
    else_=99,
)


class TaskNotFoundError(Exception):
    """Raised when a task with the given ID does not exist."""


class TaskQueue:
    """Database-backed async task queue with priority ordering and dependency tracking.

    Supports multiple concurrent agents safely via SELECT … FOR UPDATE SKIP LOCKED
    (PostgreSQL dialect) or an atomic status-CAS update (SQLite / other dialects).

    Example::

        factory = async_sessionmaker(engine, expire_on_commit=False)
        q = TaskQueue(factory)

        task = await q.enqueue({"title": "Fix bug", "priority": "critical"})
        claimed = await q.dequeue(repo="backend")
        await q.complete(claimed.id)
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialise the queue with an async session factory.

        Args:
            session_factory: An ``async_sessionmaker`` bound to the target DB.
        """
        self._factory = session_factory

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def enqueue(self, task_data: dict[str, Any]) -> Task:
        """Create and persist a new task.

        Args:
            task_data: Mapping of Task field names → values.  ``id``,
                ``created_at``, and ``updated_at`` are filled automatically.

        Returns:
            The newly created :class:`~autodev.core.models.Task`.
        """
        async with self._factory() as session:
            task = Task(
                id=task_data.get("id", uuid.uuid4()),
                title=task_data["title"],
                description=task_data.get("description"),
                source=task_data.get("source", "manual"),
                priority=task_data.get("priority", Priority.NORMAL),
                status=task_data.get("status", TaskStatus.QUEUED),
                assigned_to=task_data.get("assigned_to"),
                repo=task_data.get("repo"),
                issue_number=task_data.get("issue_number"),
                pr_number=task_data.get("pr_number"),
                depends_on=task_data.get("depends_on") or [],
                metadata_=task_data.get("metadata") or {},
                created_by=task_data.get("created_by"),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            logger.debug("Enqueued task %s (%s)", task.id, task.title)
            return task

    async def dequeue(self, repo: str | None = None) -> Task | None:
        """Claim the highest-priority queued task whose dependencies are all done.

        Uses ``SELECT … FOR UPDATE SKIP LOCKED`` on PostgreSQL so that
        concurrent agents never claim the same task.  On SQLite (used in
        tests) falls back to an atomic ``UPDATE … WHERE status='queued'``
        approach.

        Args:
            repo: If provided, only consider tasks for this repository.

        Returns:
            The claimed :class:`~autodev.core.models.Task` (status →
            ``assigned``), or ``None`` if no eligible task exists.
        """
        async with self._factory() as session:
            async with session.begin():
                dialect = session.bind.dialect.name  # type: ignore[union-attr]
                use_skip_locked = dialect == "postgresql"

                # Base filter: queued status
                filters = [Task.status == TaskStatus.QUEUED]
                if repo is not None:
                    filters.append(Task.repo == repo)

                if use_skip_locked:
                    stmt = (
                        select(Task)
                        .where(and_(*filters))
                        .order_by(_PRIORITY_CASE, Task.created_at)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    result = await session.execute(stmt)
                    task = result.scalar_one_or_none()
                else:
                    # SQLite: fetch candidates and pick the first whose deps are done
                    stmt = (
                        select(Task)
                        .where(and_(*filters))
                        .order_by(_PRIORITY_CASE, Task.created_at)
                    )
                    result = await session.execute(stmt)
                    candidates = result.scalars().all()
                    task = None
                    for candidate in candidates:
                        if await self._deps_satisfied(session, candidate):
                            task = candidate
                            break

                if task is None:
                    return None

                # For PostgreSQL path, check deps after locking the row
                if use_skip_locked and not await self._deps_satisfied(session, task):
                    return None

                task.status = TaskStatus.ASSIGNED
                task.updated_at = datetime.now(UTC)
                await session.flush()
                await session.refresh(task)
                logger.debug("Dequeued task %s", task.id)
                return task

    async def assign(self, task_id: uuid.UUID, agent_id: str) -> Task:
        """Atomically assign a task to a specific agent.

        Args:
            task_id: UUID of the task to assign.
            agent_id: Identifier of the agent taking the task.

        Returns:
            Updated :class:`~autodev.core.models.Task`.

        Raises:
            TaskNotFoundError: If no task with *task_id* exists.
        """
        async with self._factory() as session:
            async with session.begin():
                task = await session.get(Task, task_id)
                if task is None:
                    raise TaskNotFoundError(task_id)
                task.assigned_to = agent_id
                task.status = TaskStatus.ASSIGNED
                task.updated_at = datetime.now(UTC)
                await session.flush()
                await session.refresh(task)
                return task

    async def complete(self, task_id: uuid.UUID, pr_number: int | None = None) -> Task:
        """Mark a task as done.

        Args:
            task_id: UUID of the task to complete.
            pr_number: Optional PR number to attach to the task record.

        Returns:
            Updated :class:`~autodev.core.models.Task`.

        Raises:
            TaskNotFoundError: If no task with *task_id* exists.
        """
        async with self._factory() as session:
            async with session.begin():
                task = await session.get(Task, task_id)
                if task is None:
                    raise TaskNotFoundError(task_id)
                task.status = TaskStatus.DONE
                task.updated_at = datetime.now(UTC)
                if pr_number is not None:
                    task.pr_number = pr_number
                await session.flush()
                await session.refresh(task)
                logger.debug("Completed task %s", task.id)
                return task

    async def fail(self, task_id: uuid.UUID, reason: str) -> Task:
        """Mark a task as failed.

        Args:
            task_id: UUID of the task that failed.
            reason: Human-readable failure reason stored in task metadata.

        Returns:
            Updated :class:`~autodev.core.models.Task`.

        Raises:
            TaskNotFoundError: If no task with *task_id* exists.
        """
        async with self._factory() as session:
            async with session.begin():
                task = await session.get(Task, task_id)
                if task is None:
                    raise TaskNotFoundError(task_id)
                task.status = TaskStatus.FAILED
                task.updated_at = datetime.now(UTC)
                if task.metadata_ is None:
                    task.metadata_ = {}
                task.metadata_ = {**task.metadata_, "failure_reason": reason}
                await session.flush()
                await session.refresh(task)
                logger.debug("Failed task %s: %s", task.id, reason)
                return task

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(self, task_id: uuid.UUID) -> Task | None:
        """Fetch a single task by its UUID.

        Args:
            task_id: UUID of the task to retrieve.

        Returns:
            The :class:`~autodev.core.models.Task`, or ``None`` if not found.
        """
        async with self._factory() as session:
            return await session.get(Task, task_id)

    async def list_tasks(
        self,
        status: str | None = None,
        repo: str | None = None,
        priority: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        """Return a filtered, paginated list of tasks.

        Args:
            status: Filter by :class:`~autodev.core.models.TaskStatus` value.
            repo: Filter by repository name.
            priority: Filter by :class:`~autodev.core.models.Priority` value.
            limit: Maximum number of results (default 50).
            offset: Number of results to skip (default 0).

        Returns:
            List of matching :class:`~autodev.core.models.Task` objects.
        """
        async with self._factory() as session:
            filters = []
            if status is not None:
                filters.append(Task.status == status)
            if repo is not None:
                filters.append(Task.repo == repo)
            if priority is not None:
                filters.append(Task.priority == priority)

            stmt = (
                select(Task)
                .where(and_(*filters) if filters else text("1=1"))
                .order_by(_PRIORITY_CASE, Task.created_at)
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count(self, status: str | None = None, repo: str | None = None) -> int:
        """Count tasks matching the given filters.

        Args:
            status: Filter by task status.
            repo: Filter by repository name.

        Returns:
            Integer count of matching tasks.
        """
        async with self._factory() as session:
            filters = []
            if status is not None:
                filters.append(Task.status == status)
            if repo is not None:
                filters.append(Task.repo == repo)

            stmt = select(func.count()).select_from(Task)
            if filters:
                stmt = stmt.where(and_(*filters))
            result = await session.execute(stmt)
            return result.scalar_one()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _deps_satisfied(self, session: AsyncSession, task: Task) -> bool:
        """Return True if all dependency tasks for *task* have status ``done``.

        Args:
            session: Active DB session (must not be closed).
            task: Task whose ``depends_on`` list to check.

        Returns:
            ``True`` when all dependencies are done (or there are none).
        """
        dep_ids = task.depends_on or []
        if not dep_ids:
            return True

        stmt = select(func.count()).select_from(Task).where(
            and_(
                Task.id.in_(dep_ids),
                Task.status != TaskStatus.DONE,
            )
        )
        result = await session.execute(stmt)
        not_done = result.scalar_one()
        return not_done == 0
