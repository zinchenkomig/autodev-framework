"""Worker process: developer slots + delivery loop."""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import UTC, datetime
from pathlib import Path

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
from autodev.worker import acceptor, chat, combined, planner
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

#: How often an idle chat slot looks for a new message: the owner is waiting.
CHAT_POLL_SECONDS = 2

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
        self.stopping = asyncio.Event()
        self._drain_logged = False

    async def run(self) -> None:
        slots = [f"developer-{i + 1}" for i in range(max(1, self.ctx.settings.worker_slots))]
        await self.register_agents(slots)
        await self.recover()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop)
        logger.info("worker started: %d developer slot(s)", len(slots))
        await asyncio.gather(
            *(self.slot_loop(name) for name in slots),
            *(self.chat_loop() for _ in range(max(1, self.ctx.settings.chat_slots))),
            self.delivery_loop(),
            self.planner_loop(),
            self.acceptance_loop(),
            self.combined_loop(),
        )
        logger.info("worker stopped")

    def stop(self) -> None:
        """Graceful stop: take no new tasks, let running Claude sessions finish, then return from run()."""
        if not self.stopping.is_set():
            logger.info("stop requested — finishing running tasks, taking no new ones")
            self.stopping.set()

    def draining(self) -> bool:
        """An update is waiting: don't start new tasks (running ones continue)."""
        drain = Path(self.ctx.settings.drain_file).exists()
        if drain != self._drain_logged:
            logger.info("update pending — not taking new tasks" if drain else "update done — taking tasks again")
            self._drain_logged = drain
        return drain

    async def _sleep(self, seconds: float) -> None:
        """Sleep that ends early on stop()."""
        try:
            await asyncio.wait_for(self.stopping.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def register_agents(self, slots: list[str]) -> None:
        async with self.ctx.session_factory() as session:
            for agent_id, role in [
                (DEVELOPER_SWITCH, "developer"),
                *((s, "developer") for s in slots),
                ("delivery", "delivery"),
                (planner.AGENT, "planner"),
                (acceptor.AGENT, "pm"),
            ]:
                agent = await session.get(Agent, agent_id)
                if agent is None:
                    session.add(Agent(id=agent_id, role=role, status=AgentStatus.IDLE))
                else:
                    agent.status = AgentStatus.IDLE
                    agent.current_task_id = None
            await session.commit()

    async def recover(self) -> None:
        """Tasks (and chats) left in progress by a previous process go back to the queue."""
        await chat.recover(self.ctx)
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
        while not self.stopping.is_set():
            try:
                if self.ctx.paused():
                    remaining = (self.ctx.paused_until - datetime.now(UTC)).total_seconds()
                    await self._sleep(min(max(remaining, 1), 60))
                    continue
                runnable = not self.draining() and await self.developers_enabled()
                task_id = await self.claim(name) if runnable else None
                if task_id is None:
                    await self._sleep(self.ctx.settings.poll_interval)
                    continue
                await self._agent_status(name, AgentStatus.WORKING, task_id)
                try:
                    await develop(self.ctx, task_id, name)
                finally:
                    await self._agent_status(name, AgentStatus.IDLE, None)
            except Exception:
                logger.exception("slot %s crashed — continuing", name)
                await self._sleep(5)

    async def combined_loop(self) -> None:
        """Rebuild the one-diff view of a task and its follow-ups after their merges."""
        try:
            await combined.backfill(self.ctx)
        except Exception:
            logger.exception("full diff backfill failed")
        while not self.stopping.is_set():
            try:
                for root_id in await combined.pending(self.ctx):
                    await combined.rebuild(self.ctx, root_id)
                await self._sleep(self.ctx.settings.poll_interval)
            except Exception:
                logger.exception("full diff rebuild failed — retrying later")
                await self._sleep(300)

    async def planner_loop(self) -> None:
        """Test-plan refreshes the owner asked for, one at a time, beside the developer slots."""
        while not self.stopping.is_set():
            try:
                runnable = not self.ctx.paused() and not self.draining() and await self.developers_enabled()
                task_id = await planner.next_request(self.ctx) if runnable else None
                if task_id is None:
                    await self._sleep(self.ctx.settings.poll_interval)
                    continue
                await self._agent_status(planner.AGENT, AgentStatus.WORKING, task_id)
                try:
                    await planner.refresh_plan(self.ctx, task_id)
                finally:
                    await self._agent_status(planner.AGENT, AgentStatus.IDLE, None)
            except Exception:
                logger.exception("planner crashed — continuing")
                await self._sleep(5)

    async def acceptance_loop(self) -> None:
        """The PM accepts main tasks on stage before the owner is called, one at a time."""
        while not self.stopping.is_set():
            try:
                runnable = not self.ctx.paused() and not self.draining() and await self.developers_enabled()
                task_id = await acceptor.next_request(self.ctx) if runnable else None
                if task_id is None:
                    await self._sleep(self.ctx.settings.poll_interval)
                    continue
                await self._agent_status(acceptor.AGENT, AgentStatus.WORKING, task_id)
                try:
                    await acceptor.accept(self.ctx, task_id)
                finally:
                    await self._agent_status(acceptor.AGENT, AgentStatus.IDLE, None)
            except Exception:
                logger.exception("acceptance crashed — continuing")
                await self._sleep(5)

    async def chat_loop(self) -> None:
        """Answer the owner in chats. Not paused with the developers: a question needs no code changes."""
        while not self.stopping.is_set():
            try:
                runnable = not self.ctx.paused() and not self.draining()
                chat_id = await chat.claim(self.ctx) if runnable else None
                if chat_id is None:
                    await self._sleep(CHAT_POLL_SECONDS)
                    continue
                await chat.answer(self.ctx, chat_id)
            except Exception:
                logger.exception("chat slot crashed — continuing")
                await self._sleep(5)

    async def delivery_loop(self) -> None:
        delivery = Delivery(self.ctx)
        while not self.stopping.is_set():
            try:
                await delivery.tick()
            except Exception:
                logger.exception("delivery tick failed")
            try:
                chat.sweep(self.ctx.settings.workdir)
            except Exception:
                logger.exception("sweeping chat checkouts failed")
            try:
                await self._heartbeat()
            except Exception:
                logger.exception("heartbeat failed")
            await self._sleep(self.ctx.settings.poll_interval * 2)

    async def _heartbeat(self) -> None:
        """Lets the dashboard tell a live worker from a dead one."""
        async with self.ctx.session_factory() as session:
            agent = await session.get(Agent, "delivery")
            if agent is not None:
                agent.last_run_at = datetime.now(UTC)
                await session.commit()

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
