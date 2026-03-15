"""Tests for the AgentStateManager implementation.

Uses an in-memory SQLite database (aiosqlite) — no external Postgres required.
Covers: registration, status transitions, task assignment, run lifecycle,
timeout detection, event emission, and error paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from autodev.core.events import EventBus
from autodev.core.models import Agent, AgentRun, AgentRunStatus, AgentStatus, Base, Task
from autodev.core.state import AgentStateManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_factory():
    """In-memory SQLite DB with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture()
async def manager(db_factory):
    """AgentStateManager without event bus."""
    return AgentStateManager(db_factory)


@pytest.fixture()
async def bus():
    """EventBus without DB persistence."""
    return EventBus()


@pytest.fixture()
async def manager_with_bus(db_factory, bus):
    """AgentStateManager with an in-memory EventBus."""
    return AgentStateManager(db_factory, event_bus=bus)


@pytest.fixture()
async def task(db_factory) -> Task:
    """Create and persist a dummy Task."""
    async with db_factory() as session:
        t = Task(title="Test task")
        session.add(t)
        await session.commit()
        await session.refresh(t)
    return t


# ---------------------------------------------------------------------------
# 1. register_agent
# ---------------------------------------------------------------------------


class TestRegisterAgent:
    async def test_register_creates_agent(self, manager: AgentStateManager):
        agent = await manager.register_agent("dev-1", "developer")
        assert isinstance(agent, Agent)
        assert agent.id == "dev-1"
        assert agent.role == "developer"

    async def test_register_defaults_to_idle(self, manager: AgentStateManager):
        agent = await manager.register_agent("dev-2", "tester")
        assert agent.status == AgentStatus.IDLE

    async def test_register_persists_to_db(self, manager: AgentStateManager):
        await manager.register_agent("dev-3", "ba")
        fetched = await manager.get_agent("dev-3")
        assert fetched is not None
        assert fetched.role == "ba"


# ---------------------------------------------------------------------------
# 2. get_agent / list_agents
# ---------------------------------------------------------------------------


class TestGetAndList:
    async def test_get_agent_returns_none_for_unknown(self, manager: AgentStateManager):
        result = await manager.get_agent("nonexistent")
        assert result is None

    async def test_get_agent_returns_registered_agent(self, manager: AgentStateManager):
        await manager.register_agent("ag-1", "pm")
        agent = await manager.get_agent("ag-1")
        assert agent is not None
        assert agent.id == "ag-1"

    async def test_list_agents_empty(self, manager: AgentStateManager):
        agents = await manager.list_agents()
        assert agents == []

    async def test_list_agents_returns_all(self, manager: AgentStateManager):
        await manager.register_agent("a1", "developer")
        await manager.register_agent("a2", "tester")
        agents = await manager.list_agents()
        assert len(agents) == 2
        ids = {a.id for a in agents}
        assert ids == {"a1", "a2"}


# ---------------------------------------------------------------------------
# 3. set_status — valid & invalid transitions
# ---------------------------------------------------------------------------


class TestSetStatus:
    async def test_idle_to_assigned_valid(self, manager: AgentStateManager):
        await manager.register_agent("s1", "developer")
        agent = await manager.set_status("s1", AgentStatus.ASSIGNED)
        assert agent.status == AgentStatus.ASSIGNED

    async def test_assigned_to_working_valid(self, manager: AgentStateManager):
        await manager.register_agent("s2", "developer")
        await manager.set_status("s2", AgentStatus.ASSIGNED)
        agent = await manager.set_status("s2", AgentStatus.WORKING)
        assert agent.status == AgentStatus.WORKING

    async def test_assigned_to_idle_valid_cancel(self, manager: AgentStateManager):
        await manager.register_agent("s3", "developer")
        await manager.set_status("s3", AgentStatus.ASSIGNED)
        agent = await manager.set_status("s3", AgentStatus.IDLE)
        assert agent.status == AgentStatus.IDLE

    async def test_working_to_idle_valid(self, manager: AgentStateManager):
        await manager.register_agent("s4", "developer")
        await manager.set_status("s4", AgentStatus.ASSIGNED)
        await manager.set_status("s4", AgentStatus.WORKING)
        agent = await manager.set_status("s4", AgentStatus.IDLE)
        assert agent.status == AgentStatus.IDLE

    async def test_idle_to_working_invalid(self, manager: AgentStateManager):
        await manager.register_agent("s5", "developer")
        with pytest.raises(ValueError, match="Invalid status transition"):
            await manager.set_status("s5", AgentStatus.WORKING)

    async def test_working_to_assigned_invalid(self, manager: AgentStateManager):
        await manager.register_agent("s6", "developer")
        await manager.set_status("s6", AgentStatus.ASSIGNED)
        await manager.set_status("s6", AgentStatus.WORKING)
        with pytest.raises(ValueError, match="Invalid status transition"):
            await manager.set_status("s6", AgentStatus.ASSIGNED)

    async def test_set_status_unknown_agent_raises(self, manager: AgentStateManager):
        with pytest.raises(ValueError, match="not found"):
            await manager.set_status("ghost", AgentStatus.ASSIGNED)


# ---------------------------------------------------------------------------
# 4. assign_task
# ---------------------------------------------------------------------------


class TestAssignTask:
    async def test_assign_task_transitions_to_assigned(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("at-1", "developer")
        agent = await manager.assign_task("at-1", task.id)
        assert agent.status == AgentStatus.ASSIGNED

    async def test_assign_task_sets_current_task_id(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("at-2", "developer")
        agent = await manager.assign_task("at-2", task.id)
        assert agent.current_task_id == task.id

    async def test_assign_task_from_non_idle_raises(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("at-3", "developer")
        await manager.assign_task("at-3", task.id)  # now assigned
        with pytest.raises(ValueError, match="Invalid status transition"):
            await manager.assign_task("at-3", task.id)  # can't re-assign without going idle first


# ---------------------------------------------------------------------------
# 5. start_work
# ---------------------------------------------------------------------------


class TestStartWork:
    async def test_start_work_creates_run(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("sw-1", "developer")
        await manager.assign_task("sw-1", task.id)
        run = await manager.start_work("sw-1")
        assert isinstance(run, AgentRun)
        assert run.status == AgentRunStatus.RUNNING

    async def test_start_work_transitions_to_working(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("sw-2", "developer")
        await manager.assign_task("sw-2", task.id)
        await manager.start_work("sw-2")
        agent = await manager.get_agent("sw-2")
        assert agent.status == AgentStatus.WORKING

    async def test_start_work_increments_total_runs(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("sw-3", "developer")
        await manager.assign_task("sw-3", task.id)
        await manager.start_work("sw-3")
        agent = await manager.get_agent("sw-3")
        assert agent.total_runs == 1

    async def test_start_work_from_idle_raises(self, manager: AgentStateManager):
        await manager.register_agent("sw-4", "developer")
        with pytest.raises(ValueError, match="Invalid status transition"):
            await manager.start_work("sw-4")


# ---------------------------------------------------------------------------
# 6. complete_work
# ---------------------------------------------------------------------------


class TestCompleteWork:
    async def test_complete_work_marks_run_success(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("cw-1", "developer")
        await manager.assign_task("cw-1", task.id)
        await manager.start_work("cw-1")
        run = await manager.complete_work("cw-1", result={"pr": 5}, tokens=100, cost=0.01)
        assert run.status == AgentRunStatus.SUCCESS

    async def test_complete_work_stores_result(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("cw-2", "developer")
        await manager.assign_task("cw-2", task.id)
        await manager.start_work("cw-2")
        run = await manager.complete_work("cw-2", result={"key": "val"})
        assert run.result == {"key": "val"}

    async def test_complete_work_transitions_to_idle(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("cw-3", "developer")
        await manager.assign_task("cw-3", task.id)
        await manager.start_work("cw-3")
        await manager.complete_work("cw-3", result={})
        agent = await manager.get_agent("cw-3")
        assert agent.status == AgentStatus.IDLE

    async def test_complete_work_clears_current_task(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("cw-4", "developer")
        await manager.assign_task("cw-4", task.id)
        await manager.start_work("cw-4")
        await manager.complete_work("cw-4", result={})
        agent = await manager.get_agent("cw-4")
        assert agent.current_task_id is None

    async def test_complete_work_from_idle_raises(self, manager: AgentStateManager):
        await manager.register_agent("cw-5", "developer")
        with pytest.raises(ValueError, match="Invalid status transition"):
            await manager.complete_work("cw-5", result={})


# ---------------------------------------------------------------------------
# 7. fail_work
# ---------------------------------------------------------------------------


class TestFailWork:
    async def test_fail_work_marks_run_failed(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("fw-1", "developer")
        await manager.assign_task("fw-1", task.id)
        await manager.start_work("fw-1")
        run = await manager.fail_work("fw-1", error="timeout")
        assert run.status == AgentRunStatus.FAILED

    async def test_fail_work_increments_failures(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("fw-2", "developer")
        await manager.assign_task("fw-2", task.id)
        await manager.start_work("fw-2")
        await manager.fail_work("fw-2", error="oops")
        agent = await manager.get_agent("fw-2")
        assert agent.total_failures == 1

    async def test_fail_work_transitions_to_idle(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("fw-3", "developer")
        await manager.assign_task("fw-3", task.id)
        await manager.start_work("fw-3")
        await manager.fail_work("fw-3", error="broken")
        agent = await manager.get_agent("fw-3")
        assert agent.status == AgentStatus.IDLE

    async def test_fail_work_stores_error_in_result(
        self, manager: AgentStateManager, task: Task
    ):
        await manager.register_agent("fw-4", "developer")
        await manager.assign_task("fw-4", task.id)
        await manager.start_work("fw-4")
        run = await manager.fail_work("fw-4", error="network error")
        assert run.result == {"error": "network error"}


# ---------------------------------------------------------------------------
# 8. check_timeouts
# ---------------------------------------------------------------------------


class TestCheckTimeouts:
    async def test_check_timeouts_returns_empty_when_no_working(
        self, manager: AgentStateManager
    ):
        await manager.register_agent("ct-1", "developer")
        timed_out = await manager.check_timeouts(timeout_minutes=1)
        assert timed_out == []

    async def test_check_timeouts_detects_overdue_agent(
        self, db_factory, task: Task
    ):
        """Manually create an old run and verify it gets timed out."""
        manager = AgentStateManager(db_factory)
        await manager.register_agent("ct-2", "developer")
        await manager.assign_task("ct-2", task.id)
        run = await manager.start_work("ct-2")

        # Backdate the run's started_at to simulate a timeout
        async with db_factory() as session:
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(AgentRun).where(AgentRun.id == run.id)
            )
            stale_run = result.scalar_one()
            stale_run.started_at = datetime.now(UTC) - timedelta(minutes=60)
            await session.commit()

        timed_out = await manager.check_timeouts(timeout_minutes=30)
        assert len(timed_out) == 1
        assert timed_out[0].id == "ct-2"
        assert timed_out[0].status == AgentStatus.IDLE

    async def test_check_timeouts_increments_failures(
        self, db_factory, task: Task
    ):
        manager = AgentStateManager(db_factory)
        await manager.register_agent("ct-3", "developer")
        await manager.assign_task("ct-3", task.id)
        run = await manager.start_work("ct-3")

        async with db_factory() as session:
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(AgentRun).where(AgentRun.id == run.id)
            )
            stale_run = result.scalar_one()
            stale_run.started_at = datetime.now(UTC) - timedelta(minutes=60)
            await session.commit()

        await manager.check_timeouts(timeout_minutes=30)
        agent = await manager.get_agent("ct-3")
        assert agent.total_failures == 1

    async def test_check_timeouts_marks_run_timeout(
        self, db_factory, task: Task
    ):
        manager = AgentStateManager(db_factory)
        await manager.register_agent("ct-4", "developer")
        await manager.assign_task("ct-4", task.id)
        run = await manager.start_work("ct-4")

        async with db_factory() as session:
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(AgentRun).where(AgentRun.id == run.id)
            )
            stale_run = result.scalar_one()
            stale_run.started_at = datetime.now(UTC) - timedelta(minutes=60)
            await session.commit()

        await manager.check_timeouts(timeout_minutes=30)

        async with db_factory() as session:
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(AgentRun).where(AgentRun.id == run.id)
            )
            updated_run = result.scalar_one()
            assert updated_run.status == AgentRunStatus.TIMEOUT

    async def test_check_timeouts_does_not_affect_recent_agent(
        self, db_factory, task: Task
    ):
        """An agent that just started should not be timed out."""
        manager = AgentStateManager(db_factory)
        await manager.register_agent("ct-5", "developer")
        await manager.assign_task("ct-5", task.id)
        await manager.start_work("ct-5")
        # do NOT backdate; the run is fresh
        timed_out = await manager.check_timeouts(timeout_minutes=30)
        assert len(timed_out) == 0
        agent = await manager.get_agent("ct-5")
        assert agent.status == AgentStatus.WORKING


# ---------------------------------------------------------------------------
# 9. Event emission
# ---------------------------------------------------------------------------


class TestEventEmission:
    async def test_register_does_not_emit_event(
        self, manager_with_bus: AgentStateManager, bus: EventBus
    ):
        calls: list = []

        async def handler(event):
            calls.append(event)

        bus.subscribe("*", handler)
        await manager_with_bus.register_agent("ev-1", "developer")
        assert len(calls) == 0

    async def test_set_status_emits_assigned_event(
        self, manager_with_bus: AgentStateManager, bus: EventBus
    ):
        calls: list = []

        async def handler(event):
            calls.append(event)

        bus.subscribe("agent.assigned", handler)
        await manager_with_bus.register_agent("ev-2", "developer")
        await manager_with_bus.set_status("ev-2", AgentStatus.ASSIGNED)
        assert any(c.type == "agent.assigned" for c in calls)

    async def test_set_status_emits_idle_event(
        self, manager_with_bus: AgentStateManager, bus: EventBus
    ):
        calls: list = []

        async def handler(event):
            calls.append(event)

        bus.subscribe("agent.idle", handler)
        await manager_with_bus.register_agent("ev-3", "developer")
        await manager_with_bus.set_status("ev-3", AgentStatus.ASSIGNED)
        await manager_with_bus.set_status("ev-3", AgentStatus.IDLE)
        idle_events = [c for c in calls if c.type == "agent.idle"]
        assert len(idle_events) >= 1

    async def test_fail_work_emits_agent_failed_event(
        self, manager_with_bus: AgentStateManager, bus: EventBus, task: Task
    ):
        calls: list = []

        async def handler(event):
            calls.append(event)

        bus.subscribe("agent.failed", handler)
        await manager_with_bus.register_agent("ev-4", "developer")
        await manager_with_bus.assign_task("ev-4", task.id)
        await manager_with_bus.start_work("ev-4")
        await manager_with_bus.fail_work("ev-4", error="boom")
        failed_events = [c for c in calls if c.type == "agent.failed"]
        assert len(failed_events) >= 1

    async def test_no_event_bus_no_error(
        self, manager: AgentStateManager, task: Task
    ):
        """All operations should work normally without an event bus."""
        await manager.register_agent("ev-5", "developer")
        await manager.assign_task("ev-5", task.id)
        await manager.start_work("ev-5")
        run = await manager.complete_work("ev-5", result={"ok": True})
        assert run.status == AgentRunStatus.SUCCESS
