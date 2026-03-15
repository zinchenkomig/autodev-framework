"""Release management REST endpoints.

Manage software releases: list, create, and trigger deployments.

TODO: Add deployment trigger endpoint.
TODO: Add release notes generation endpoint.
TODO: Add rollback endpoint.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ReleaseCreate(BaseModel):
    """Request body for creating a release.

    TODO: Add target_env field (staging, production).
    """

    version: str
    notes: str = ""


class ReleaseResponse(BaseModel):
    """Release representation returned by the API."""

    id: int
    version: str
    notes: str
    created_at: datetime


@router.get("/", summary="List releases")
async def list_releases() -> list[ReleaseResponse]:
    """Return all releases.

    TODO: Query from database.
    """
    # TODO: Implement database query
    return []


@router.post("/", summary="Create a release", status_code=201)
async def create_release(body: ReleaseCreate) -> ReleaseResponse:
    """Create a new release record and trigger release workflow.

    TODO: Persist to database.
    TODO: Publish release.created domain event.
    TODO: Trigger Release Manager agent task.
    """
    # TODO: Implement release creation
    raise HTTPException(status_code=501, detail="Not implemented")
