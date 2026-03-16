"""Agent management REST endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Agent, Event

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentResponse(BaseModel):
    id: str
    role: str
    status: str
    current_task_id: str | None
    last_run_at: datetime | None
    total_runs: int
    total_failures: int

    model_config = {"from_attributes": True}


class TriggerResponse(BaseModel):
    event_id: str
    agent_id: str
    message: str


def _agent_to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        role=agent.role,
        status=agent.status,
        current_task_id=str(agent.current_task_id) if agent.current_task_id else None,
        last_run_at=agent.last_run_at,
        total_runs=agent.total_runs,
        total_failures=agent.total_failures,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List registered agents")
async def list_agents(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AgentResponse]:
    """Return all registered agents."""
    result = await session.execute(select(Agent))
    agents = result.scalars().all()
    return [_agent_to_response(a) for a in agents]


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
