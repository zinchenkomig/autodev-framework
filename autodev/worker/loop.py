"""Worker process: developer slots + delivery loop."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, select

from autodev.core.models import (
    MERGED_STATUSES,
    Agent,
    AgentStatus,
    Project,
    Task,
    TaskStatus,
    TaskTransition,
)
from autodev.worker.context import WorkerContext
from autodev.worker.delivery import Delivery
from autodev.worker.developer import develop

logger = logging.getLogger(__name__)

PRIORITY_RANK = case(
    (Task.priority == "critical", 0),
    (Task.priority == "high", 1),
    (Task.priority == "normal", 2),
    else_=3,
)

#: Agent row whose ``enabled`` flag pauses all developer slots.
DEVELOPER_SWITCH = "developer"


def resolve_project(task: Task, projects: list[Project]) -> Project | None:
    """Project for a task that only knows its repo (e.g. created by the PM chat)."""
    if task.project_id:
        return next((p for p in projects if p.id == task.project_id), None)
    if task.repo:
        matches = [p for p in projects if p.repo(task.repo) is not None]
        return matches[0] if len(matches) == 1 else None
    return projects[0] if len(projects) == 1 else None


class Worker:
    def __init__(self, ctx: WorkerContext) -> None:
        self.ctx = ctx
        self._claim_lock = asyncio.Lock()

    async def run(self) -> None:
        slots = [f"developer-{i + 1}" for i in range(max(1, self.ctx.settings.worker_slots))]
        await self.register_agents(slots)
        await self.recover()
        logger.info("worker started: %d developer slot(s)", len(slots))
        await asyncio.gather(*(self.slot_loop(name) for name in slots), self.delivery_loop())

    async def register_agents(self, slots: list[str]) -> None:
        async with self.ctx.session_factory() as session:
            for agent_id, role in [
                (DEVELOPER_SWITCH, "developer"),
                *((s, "developer") for s in slots),
                ("delivery", "delivery"),
            ]:
                agent = await session.get(Agent, agent_id)
                if agent is None:
                    session.add(Agent(id=agent_id, role=role, status=AgentStatus.IDLE))
                else:
                    agent.status = AgentStatus.IDLE
                    agent.current_task_id = None
            await session.commit()

    async def recover(self) -> None:
        """Tasks left in_progress by a previous process go back to the queue."""
        async with self.ctx.session_factory() as session:
            rows = await session.execute(select(Task).where(Task.status == TaskStatus.IN_PROGRESS))
            for task in rows.scalars():
                task.status = TaskStatus.QUEUED
                task.assigned_to = None
                task.status_changed_at = datetime.now(UTC)
                session.add(
                    TaskTransition(
                        task_id=task.id,
                        from_status=TaskStatus.IN_PROGRESS,
                        to_status=TaskStatus.QUEUED,
                        reason="worker restarted",
                        triggered_by="worker",
                    )
                )
            await session.commit()

    async def slot_loop(self, name: str) -> None:
        while True:
            try:
                if self.ctx.paused():
                    remaining = (self.ctx.paused_until - datetime.now(UTC)).total_seconds()
                    await asyncio.sleep(min(max(remaining, 1), 60))
                    continue
                task_id = await self.claim(name) if await self.developers_enabled() else None
                if task_id is None:
                    await asyncio.sleep(self.ctx.settings.poll_interval)
                    continue
                await self._agent_status(name, AgentStatus.WORKING, task_id)
                try:
                    await develop(self.ctx, task_id, name)
                finally:
                    await self._agent_status(name, AgentStatus.IDLE, None)
            except Exception:
                logger.exception("slot %s crashed — continuing", name)
                await asyncio.sleep(5)

    async def delivery_loop(self) -> None:
        delivery = Delivery(self.ctx)
        while True:
            try:
                await delivery.tick()
            except Exception:
                logger.exception("delivery tick failed")
            await asyncio.sleep(self.ctx.settings.poll_interval * 2)

    async def developers_enabled(self) -> bool:
        async with self.ctx.session_factory() as session:
            switch = await session.get(Agent, DEVELOPER_SWITCH)
            return switch is None or switch.enabled

    async def claim(self, slot: str) -> uuid.UUID | None:
        """Atomically pick the next runnable queued task and mark it in_progress."""
        async with self._claim_lock, self.ctx.session_factory() as session:
            projects = list((await session.execute(select(Project))).scalars())
            running = dict(
                (
                    await session.execute(
                        select(Task.project_id, func.count())
                        .where(Task.status == TaskStatus.IN_PROGRESS)
                        .group_by(Task.project_id)
                    )
                ).all()
            )
            candidates = (
                await session.execute(
                    select(Task)
                    .where(Task.status == TaskStatus.QUEUED)
                    .order_by(PRIORITY_RANK, Task.created_at)
                    .limit(50)
                    .with_for_update(skip_locked=True, of=Task)
                )
            ).scalars()

            for task in candidates:
                project = resolve_project(task, projects)
                if project is None:
                    task.status = TaskStatus.FAILED
                    task.error = "Can't tell which project this task belongs to — set the project and retry."
                    task.status_changed_at = datetime.now(UTC)
                    session.add(
                        TaskTransition(
                            task_id=task.id,
                            from_status=TaskStatus.QUEUED,
                            to_status=TaskStatus.FAILED,
                            reason="no project",
                            triggered_by=slot,
                        )
                    )
                    continue
                if not project.enabled or running.get(project.id, 0) >= project.max_parallel:
                    continue
                if not await self._deps_merged(session, task):
                    continue

                task.project_id = project.id
                task.status = TaskStatus.IN_PROGRESS
                task.assigned_to = slot
                task.status_changed_at = datetime.now(UTC)
                fix = (task.metadata_ or {}).get("fix")
                session.add(
                    TaskTransition(
                        task_id=task.id,
                        from_status=TaskStatus.QUEUED,
                        to_status=TaskStatus.IN_PROGRESS,
                        reason=f"{fix['kind']} fix" if fix else None,
                        triggered_by=slot,
                    )
                )
                await session.commit()
                return task.id

            await session.commit()  # persist "no project" failures, release locks
            return None

    @staticmethod
    async def _deps_merged(session, task: Task) -> bool:
        if not task.depends_on:
            return True
        statuses = (await session.execute(select(Task.status).where(Task.id.in_(task.depends_on)))).scalars().all()
        return all(s in MERGED_STATUSES for s in statuses)

    async def _agent_status(self, agent_id: str, status: AgentStatus, task_id: uuid.UUID | None) -> None:
        async with self.ctx.session_factory() as session:
            agent = await session.get(Agent, agent_id)
            if agent is not None:
                agent.status = status
                agent.current_task_id = task_id
                if status == AgentStatus.WORKING:
                    agent.last_run_at = datetime.now(UTC)
                    agent.total_runs += 1
                await session.commit()
