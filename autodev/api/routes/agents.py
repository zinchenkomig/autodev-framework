"""Agent management REST endpoints."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from autodev.api.database import get_session
from autodev.core.models import Agent, AgentLog, Event

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentResponse(BaseModel):
    id: str
    role: str
    status: str
    current_task_id: str | None
    current_task_title: str | None
    last_run_at: datetime | None
    total_runs: int
    total_failures: int
    enabled: bool

    model_config = {"from_attributes": True}


class TriggerResponse(BaseModel):
    event_id: str
    agent_id: str
    message: str


class AgentLogResponse(BaseModel):
    id: str
    agent_id: str
    task_id: str | None
    level: str
    message: str
    details: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _agent_to_response(agent: Agent) -> AgentResponse:
    task_title: str | None = None
    if agent.current_task is not None:
        task_title = agent.current_task.title
    return AgentResponse(
        id=agent.id,
        role=agent.role,
        status=agent.status,
        current_task_id=str(agent.current_task_id) if agent.current_task_id else None,
        current_task_title=task_title,
        last_run_at=agent.last_run_at,
        total_runs=agent.total_runs,
        total_failures=agent.total_failures,
        enabled=agent.enabled,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List registered agents")
async def list_agents(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AgentResponse]:
    """Return all registered agents, including current task title."""
    result = await session.execute(
        select(Agent).options(selectinload(Agent.current_task))
    )
    agents = result.scalars().all()
    return [_agent_to_response(a) for a in agents]


@router.get("/{agent_id}/logs", summary="Get agent logs")
async def get_agent_logs(
    agent_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=500),
    task_id: str | None = Query(default=None),
) -> list[AgentLogResponse]:
    """Return logs for the given agent, ordered by created_at desc."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    stmt = (
        select(AgentLog)
        .where(AgentLog.agent_id == agent_id)
        .order_by(AgentLog.created_at.desc())
        .limit(limit)
    )
    if task_id is not None:
        try:
            tid = _uuid.UUID(task_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid task_id")
        stmt = stmt.where(AgentLog.task_id == tid)

    result = await session.execute(stmt)
    logs = result.scalars().all()
    return [
        AgentLogResponse(
            id=str(log.id),
            agent_id=log.agent_id,
            task_id=str(log.task_id) if log.task_id else None,
            level=log.level,
            message=log.message,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.post("/{agent_id}/trigger", summary="Trigger an agent")
async def trigger_agent(
    agent_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TriggerResponse:
    """Trigger an agent by creating an agent.triggered event."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    event = Event(
        type="agent.triggered",
        payload={"agent_id": agent_id},
        source="api",
        created_at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()
    await session.refresh(event)

    return TriggerResponse(
        event_id=str(event.id),
        agent_id=agent_id,
        message=f"Agent {agent_id} triggered",
    )


@router.post("/{agent_id}/toggle", summary="Toggle agent enabled/disabled")
async def toggle_agent(
    agent_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentResponse:
    """Toggle an agent's enabled state."""
    # Use eager loading for current_task to avoid lazy loading issues
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.current_task))
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.enabled = not agent.enabled
    await session.flush()

    return AgentResponse(
        id=agent.id,
        role=agent.role,
        status=agent.status,
        current_task_id=str(agent.current_task_id) if agent.current_task_id else None,
        current_task_title=agent.current_task.title if agent.current_task else None,
        last_run_at=agent.last_run_at,
        total_runs=agent.total_runs,
        total_failures=agent.total_failures,
        enabled=agent.enabled,
    )


@router.post("/developer/cancel", summary="Cancel current developer task")
async def cancel_developer_task(request: Request) -> dict:
    """Cancel the currently running developer task."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        # Fallback to global
        from autodev.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
    
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not running")
    
    cancelled = orchestrator.cancel_current_task()
    if cancelled:
        return {"status": "cancelled", "message": "Task cancellation requested"}
    else:
        return {"status": "idle", "message": "No task running"}
