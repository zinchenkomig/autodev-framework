"""Domain events REST endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Event

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class EventResponse(BaseModel):
    id: str
    type: str
    payload: dict
    source: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _event_to_response(event: Event) -> EventResponse:
    return EventResponse(
        id=str(event.id),
        type=event.type,
        payload=event.payload or {},
        source=event.source,
        created_at=event.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List domain events")
async def list_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    type: str | None = Query(default=None, description="Filter by event type"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[EventResponse]:
    """Return recent domain events with optional filtering."""
    stmt = select(Event)
    if type:
        stmt = stmt.where(Event.type == type)
    stmt = stmt.order_by(Event.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    events = result.scalars().all()
    return [_event_to_response(e) for e in events]
