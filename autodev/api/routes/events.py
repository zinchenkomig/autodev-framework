"""Domain events REST endpoints.

Read-only access to the event log for audit and debugging.

TODO: Add filtering by event_type and date range.
TODO: Add streaming endpoint (SSE) for real-time event feed.
TODO: Add event replay endpoint for debugging.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class EventResponse(BaseModel):
    """Event log entry returned by the API.

    TODO: Add payload field.
    """

    id: int
    event_type: str
    source: str
    occurred_at: datetime


@router.get("/", summary="List domain events")
async def list_events() -> list[EventResponse]:
    """Return recent domain events.

    TODO: Query from database with pagination.
    TODO: Add cursor-based pagination for large volumes.
    """
    # TODO: Implement database query
    return []
