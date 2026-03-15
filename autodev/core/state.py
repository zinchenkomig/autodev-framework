"""State manager for tracking global framework and agent state.

Provides a centralised, thread-safe store for runtime state that needs to
be shared across agents and API handlers within a single process.

Includes:
- StateManager: legacy in-memory key-value store (kept for compatibility)
- AgentStateManager: DB-backed agent state machine with event bus support
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.events import EventBus
from autodev.core.models import Agent, AgentRun, AgentRunStatus, AgentStatus

logger = logging.getLogger(__name__)

# Sentinel used to detect missing keys without conflicting with None values.
_MISSING = object()

# Valid state transitions: current_status -> set of allowed next statuses
_VALID_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.IDLE: {AgentStatus.ASSIGNED},
    AgentStatus.ASSIGNED: {AgentStatus.WORKING, AgentStatus.IDLE},
    AgentStatus.WORKING: {AgentStatus.IDLE},
}

# Map agent status to event type
_STATUS_EVENT_MAP: dict[AgentStatus, str] = {
    AgentStatus.IDLE: "agent.idle",
    AgentStatus.ASSIGNED: "agent.assigned",
    AgentStatus.WORKING: "agent.working",
}


class StateManager:
    """Thread-safe async key-value state store.

    Keys are dot-separated namespaces, e.g. ``"agents.developer.status"``.

    Example::

        state = StateManager()
        await state.set("system.phase", "running")
        phase = await state.get("system.phase")
    """

    def __init__(self) -> None:
        """Initialise with an empty state dict and a reentrant lock."""
        self._store: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any) -> None:
        """Set a state value.

        Args:
            key: Dot-namespaced state key.
            value: Value to store (deep-copied for safety).
        """
        async with self._lock:
            self._store[key] = deepcopy(value)
            logger.debug("State set: %s = %r", key, value)

    async def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a state value.

        Args:
            key: Dot-namespaced state key.
            default: Returned when key is absent.

        Returns:
            Deep copy of stored value, or *default*.
        """
        async with self._lock:
            value = self._store.get(key, _MISSING)
            if value is _MISSING:
                return default
            return deepcopy(value)

    async def delete(self, key: str) -> bool:
        """Remove a key from the store.

        Args:
            key: Key to remove.

        Returns:
            True if the key existed and was removed.
        """
        async with self._lock:
            existed = key in self._store
            self._store.pop(key, None)
            return existed

    async def keys(self, prefix: str = "") -> list[str]:
        """Return all keys, optionally filtered by prefix.

        Args:
            prefix: Only return keys starting with this string.

        Returns:
            Sorted list of matching keys.
        """
        async with self._lock:
            return sorted(k for k in self._store if k.startswith(prefix))

    async def snapshot(self) -> dict[str, Any]:
        """Return a full deep copy of the current state.

        TODO: Serialise to JSON and persist for crash recovery.
        """
        async with self._lock:
            return deepcopy(self._store)


class AgentStateManager:
    """DB-backed state machine for agent lifecycle management.

    Handles agent registration, status transitions with validation,
    task assignment, run tracking, and timeout detection.

    Args:
        session_factory: Async SQLAlchemy session factory (``async_sessionmaker``).
        event_bus: Optional :class:`EventBus` for emitting state change events.

    Example::

        manager = AgentStateManager(session_factory, event_bus=bus)
        agent = await manager.register_agent("dev-1", "developer")
        agent = await manager.assign_task("dev-1", task_id)
        run = await manager.start_work("dev-1")
        run = await manager.complete_work("dev-1", result={"pr": 42}, tokens=1000)
    """

    def __init__(
        self,
        session_factory: Any,
        event_bus: EventBus | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session(self) -> AsyncSession:
        """Open a new async DB session."""
        return self._session_factory()

    def _validate_transition(
        self, agent_id: str, current: AgentStatus, target: AgentStatus
    ) -> None:
        """Raise ValueError if *current* → *target* is not a valid transition."""
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid status transition for agent {agent_id!r}: "
                f"{current!r} → {target!r}. Allowed: {sorted(s.value for s in allowed)}"
            )

    async def _emit_status_event(self, agent: Agent) -> None:
        """Emit an event for the agent's current status, if event_bus is set."""
        if self._event_bus is None:
            return
        status = AgentStatus(agent.status)
        event_type: str
        if status == AgentStatus.IDLE:
            event_type = "agent.idle"
        elif status == AgentStatus.ASSIGNED:
            event_type = "agent.assigned"
        elif status == AgentStatus.WORKING:
            event_type = "agent.working"
        else:
            # For other statuses emit agent.failed or skip
            if status == AgentStatus.ERROR:
                event_type = "agent.failed"
            else:
                return
        await self._event_bus.emit(
            event_type,
            payload={"agent_id": agent.id, "role": agent.role, "status": agent.status},
            source="state_manager",
        )

    async def _get_agent_or_raise(
        self, session: AsyncSession, agent_id: str
    ) -> Agent:
        """Fetch an agent by id, raising ValueError if not found."""
        result = await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise ValueError(f"Agent {agent_id!r} not found")
        return agent

    async def _get_active_run(
        self, session: AsyncSession, agent_id: str
    ) -> AgentRun | None:
        """Return the most recent RUNNING AgentRun for the given agent."""
        result = await session.execute(
            select(AgentRun)
            .where(AgentRun.agent_id == agent_id)
            .where(AgentRun.status == AgentRunStatus.RUNNING)
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_agent(self, agent_id: str, role: str) -> Agent:
        """Create a new agent record in the database.

        Args:
            agent_id: Unique identifier for the agent.
            role: Agent role string (e.g. ``"developer"``).

        Returns:
            The newly created :class:`Agent` ORM object.
        """
        async with self._session() as session:
            agent = Agent(
                id=agent_id,
                role=role,
                status=AgentStatus.IDLE,
            )
            session.add(agent)
            await session.commit()
            await session.refresh(agent)
            logger.info("Registered agent %r with role %r", agent_id, role)
        return agent

    async def get_agent(self, agent_id: str) -> Agent | None:
        """Retrieve an agent by id.

        Args:
            agent_id: Agent identifier.

        Returns:
            The :class:`Agent` ORM object or ``None`` if not found.
        """
        async with self._session() as session:
            result = await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            return result.scalar_one_or_none()

    async def list_agents(self) -> list[Agent]:
        """Return all registered agents.

        Returns:
            List of :class:`Agent` ORM objects.
        """
        async with self._session() as session:
            result = await session.execute(select(Agent))
            return list(result.scalars().all())

    async def set_status(self, agent_id: str, status: AgentStatus) -> Agent:
        """Update an agent's status with transition validation.

        Args:
            agent_id: Target agent identifier.
            status: Desired new status.

        Returns:
            Updated :class:`Agent` ORM object.

        Raises:
            ValueError: If the agent does not exist or the transition is invalid.
        """
        async with self._session() as session:
            agent = await self._get_agent_or_raise(session, agent_id)
            current = AgentStatus(agent.status)
            self._validate_transition(agent_id, current, status)
            agent.status = status
            await session.commit()
            await session.refresh(agent)
            logger.info("Agent %r status: %r → %r", agent_id, current.value, status.value)
        await self._emit_status_event(agent)
        return agent

    async def assign_task(self, agent_id: str, task_id: uuid.UUID) -> Agent:
        """Assign a task to an agent, transitioning idle → assigned.

        Args:
            agent_id: Target agent identifier.
            task_id: UUID of the task to assign.

        Returns:
            Updated :class:`Agent` ORM object.

        Raises:
            ValueError: If the agent is not in idle status.
        """
        async with self._session() as session:
            agent = await self._get_agent_or_raise(session, agent_id)
            current = AgentStatus(agent.status)
            self._validate_transition(agent_id, current, AgentStatus.ASSIGNED)
            agent.status = AgentStatus.ASSIGNED
            agent.current_task_id = task_id
            await session.commit()
            await session.refresh(agent)
            logger.info("Agent %r assigned task %s", agent_id, task_id)
        await self._emit_status_event(agent)
        return agent

    async def start_work(self, agent_id: str) -> AgentRun:
        """Transition an assigned agent to working and create an AgentRun record.

        Args:
            agent_id: Target agent identifier.

        Returns:
            The new :class:`AgentRun` ORM object with RUNNING status.

        Raises:
            ValueError: If the agent is not in assigned status.
        """
        async with self._session() as session:
            agent = await self._get_agent_or_raise(session, agent_id)
            current = AgentStatus(agent.status)
            self._validate_transition(agent_id, current, AgentStatus.WORKING)
            agent.status = AgentStatus.WORKING
            agent.total_runs += 1
            agent.last_run_at = datetime.now(UTC)
            run = AgentRun(
                agent_id=agent_id,
                task_id=agent.current_task_id,
                status=AgentRunStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
            await session.refresh(agent)
            await session.refresh(run)
            logger.info("Agent %r started work, run id=%s", agent_id, run.id)
        await self._emit_status_event(agent)
        return run

    async def complete_work(
        self,
        agent_id: str,
        result: dict,
        tokens: int = 0,
        cost: float = 0,
    ) -> AgentRun:
        """Mark current work as completed, transitioning working → idle.

        Args:
            agent_id: Target agent identifier.
            result: Result payload to store on the run.
            tokens: Number of tokens consumed.
            cost: Cost in USD.

        Returns:
            The completed :class:`AgentRun` ORM object.

        Raises:
            ValueError: If the agent is not in working status, or no active run.
        """
        async with self._session() as session:
            agent = await self._get_agent_or_raise(session, agent_id)
            current = AgentStatus(agent.status)
            self._validate_transition(agent_id, current, AgentStatus.IDLE)
            run = await self._get_active_run(session, agent_id)
            if run is None:
                raise ValueError(f"No active run found for agent {agent_id!r}")
            run.status = AgentRunStatus.SUCCESS
            run.finished_at = datetime.now(UTC)
            run.result = result
            run.tokens_used = tokens
            run.cost_usd = cost
            agent.status = AgentStatus.IDLE
            agent.current_task_id = None
            await session.commit()
            await session.refresh(agent)
            await session.refresh(run)
            logger.info("Agent %r completed work, run id=%s", agent_id, run.id)
        await self._emit_status_event(agent)
        return run

    async def fail_work(self, agent_id: str, error: str) -> AgentRun:
        """Mark current work as failed, transitioning working → idle.

        Increments the agent's ``total_failures`` counter.

        Args:
            agent_id: Target agent identifier.
            error: Error message to record on the run.

        Returns:
            The failed :class:`AgentRun` ORM object.

        Raises:
            ValueError: If the agent is not in working status, or no active run.
        """
        async with self._session() as session:
            agent = await self._get_agent_or_raise(session, agent_id)
            current = AgentStatus(agent.status)
            self._validate_transition(agent_id, current, AgentStatus.IDLE)
            run = await self._get_active_run(session, agent_id)
            if run is None:
                raise ValueError(f"No active run found for agent {agent_id!r}")
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.result = {"error": error}
            agent.status = AgentStatus.IDLE
            agent.current_task_id = None
            agent.total_failures += 1
            await session.commit()
            await session.refresh(agent)
            await session.refresh(run)
            logger.info("Agent %r failed work with error: %s", agent_id, error)
        # Emit agent.failed event for failed work
        if self._event_bus is not None:
            await self._event_bus.emit(
                "agent.failed",
                payload={"agent_id": agent_id, "error": error},
                source="state_manager",
            )
        # Also emit idle event since agent is now idle
        await self._emit_status_event(agent)
        return run

    async def check_timeouts(self, timeout_minutes: int = 30) -> list[Agent]:
        """Find agents stuck in working state beyond *timeout_minutes* and reset them.

        Args:
            timeout_minutes: Maximum allowed working duration in minutes.

        Returns:
            List of agents that were timed out and reset to idle.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=timeout_minutes)
        timed_out: list[Agent] = []

        async with self._session() as session:
            # Find all WORKING agents
            result = await session.execute(
                select(Agent).where(Agent.status == AgentStatus.WORKING)
            )
            working_agents = list(result.scalars().all())

            for agent in working_agents:
                # Check if the agent's active run started before the cutoff
                run_result = await session.execute(
                    select(AgentRun)
                    .where(AgentRun.agent_id == agent.id)
                    .where(AgentRun.status == AgentRunStatus.RUNNING)
                    .order_by(AgentRun.started_at.desc())
                    .limit(1)
                )
                run = run_result.scalar_one_or_none()
                if run is None or run.started_at is None:
                    continue
                # Make sure started_at is timezone-aware for comparison
                started = run.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                if started <= cutoff:
                    # Timeout this run
                    run.status = AgentRunStatus.TIMEOUT
                    run.finished_at = datetime.now(UTC)
                    run.result = {"error": f"Timed out after {timeout_minutes} minutes"}
                    agent.status = AgentStatus.IDLE
                    agent.current_task_id = None
                    agent.total_failures += 1
                    timed_out.append(agent)

            if timed_out:
                await session.commit()
                for agent in timed_out:
                    await session.refresh(agent)
                logger.warning(
                    "Timed out %d agent(s): %s",
                    len(timed_out),
                    [a.id for a in timed_out],
                )

        for agent in timed_out:
            if self._event_bus is not None:
                await self._event_bus.emit(
                    "agent.failed",
                    payload={
                        "agent_id": agent.id,
                        "error": f"timeout after {timeout_minutes}m",
                    },
                    source="state_manager",
                )
        return timed_out
