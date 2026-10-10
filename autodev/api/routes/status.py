"""System status for the dashboard header: is the worker alive, paused, busy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Agent, Setting, Task

router = APIRouter()

PAUSED_UNTIL_KEY = "worker_paused_until"
HEARTBEAT_AGENT = "delivery"
#: The delivery loop ticks every ~20 s; allow a few missed ticks.
ONLINE_WINDOW_SECONDS = 120


class Slot(BaseModel):
    id: str
    status: str
    task_id: str | None
    task_ticket: int | None
    task_title: str | None


class StatusResponse(BaseModel):
    worker_online: bool
    worker_last_seen: datetime | None
    developers_enabled: bool
    paused_until: datetime | None  # Claude subscription limit
    slots: list[Slot]


@router.get("/", summary="Worker status")
async def get_status(session: Annotated[AsyncSession, Depends(get_session)]) -> StatusResponse:
    agents = {a.id: a for a in (await session.execute(select(Agent))).scalars()}
    heartbeat = agents.get(HEARTBEAT_AGENT)
    last_seen = heartbeat.last_run_at if heartbeat else None
    online = last_seen is not None and (datetime.now(UTC) - last_seen).total_seconds() < ONLINE_WINDOW_SECONDS

    paused_until = None
    setting = await session.get(Setting, PAUSED_UNTIL_KEY)
    if setting and setting.value:
        moment = datetime.fromisoformat(setting.value)
        paused_until = moment if moment > datetime.now(UTC) else None

    slots = []
    for agent in sorted(agents.values(), key=lambda a: a.id):
        if not agent.id.startswith("developer-"):
            continue
        task = await session.get(Task, agent.current_task_id) if agent.current_task_id else None
        slots.append(
            Slot(
                id=agent.id,
                status=agent.status,
                task_id=str(task.id) if task else None,
                task_ticket=task.ticket_number if task else None,
                task_title=task.title if task else None,
            )
        )

    switch = agents.get("developer")
    return StatusResponse(
        worker_online=online,
        worker_last_seen=last_seen,
        developers_enabled=switch is None or switch.enabled,
        paused_until=paused_until,
        slots=slots,
    )
