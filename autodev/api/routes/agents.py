"""Agent management REST endpoints.

Register, query, and control agent instances.

TODO: Add agent start/stop endpoints.
TODO: Add agent health/status endpoint.
TODO: Add task assignment override endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AgentResponse(BaseModel):
    """Agent representation returned by the API.

    TODO: Add last_heartbeat and current_task fields.
    """

    id: int
    role: str
    name: str


@router.get("/", summary="List registered agents")
async def list_agents() -> list[AgentResponse]:
    """Return all registered agents.

    TODO: Query from database.
    """
    # TODO: Implement database query
    return []


@router.get("/{agent_id}", summary="Get agent by ID")
async def get_agent(agent_id: int) -> AgentResponse:
    """Fetch a single agent by its ID.

    TODO: Query from database.
    """
    # TODO: Implement lookup
    raise HTTPException(status_code=404, detail="Agent not found")
