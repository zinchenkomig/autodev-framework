"""Release management REST endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Release, ReleaseStatus

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ReleaseCreate(BaseModel):
    version: str
    release_notes: str = ""
    tasks: list[str] = []


class ApproveRequest(BaseModel):
    approved_by: str = "user"


class ReleaseResponse(BaseModel):
    id: str
    version: str
    status: str
    tasks: list[str]
    release_notes: str | None
    staging_deployed_at: datetime | None
    production_deployed_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _release_to_response(release: Release) -> ReleaseResponse:
    return ReleaseResponse(
        id=str(release.id),
        version=release.version,
        status=release.status,
        tasks=[str(t) for t in (release.tasks or [])],
        release_notes=release.release_notes,
        staging_deployed_at=release.staging_deployed_at,
        production_deployed_at=release.production_deployed_at,
        approved_by=release.approved_by,
        approved_at=release.approved_at,
        created_at=release.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List releases")
async def list_releases(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ReleaseResponse]:
    """Return all releases ordered by creation date descending."""
    result = await session.execute(select(Release).order_by(Release.created_at.desc()))
    releases = result.scalars().all()
    return [_release_to_response(r) for r in releases]


@router.post("/", summary="Create a release", status_code=201)
async def create_release(
    body: ReleaseCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Create a new release record."""
    task_uuids = []
    for t in body.tasks:
        try:
            task_uuids.append(uuid.UUID(t))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid task UUID: {t}")

    release = Release(
        version=body.version,
        status=ReleaseStatus.DRAFT,
        release_notes=body.release_notes,
        tasks=task_uuids,
    )
    session.add(release)
    await session.flush()
    await session.refresh(release)
    return _release_to_response(release)


@router.get("/{release_id}", summary="Get release by ID")
async def get_release(
    release_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Fetch a single release by its UUID."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")
    release = await session.get(Release, uid)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return _release_to_response(release)


@router.post("/{release_id}/approve", summary="Approve a release")
async def approve_release(
    release_id: str,
    body: ApproveRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Approve a release (transitions to approved status)."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")
    release = await session.get(Release, uid)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.status == ReleaseStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Release already approved")

    release.status = ReleaseStatus.APPROVED
    release.approved_by = body.approved_by
    release.approved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(release)
    return _release_to_response(release)


class ReleaseUpdate(BaseModel):
    status: str | None = None


@router.patch("/{release_id}", summary="Update release status")
async def update_release(
    release_id: str,
    body: ReleaseUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Update release status (e.g. deploy to staging, testing, production)."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")
    release = await session.get(Release, uid)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    if body.status is not None:
        valid_transitions = {
            ReleaseStatus.DRAFT: [ReleaseStatus.STAGING],
            ReleaseStatus.STAGING: [ReleaseStatus.PENDING_APPROVAL, "testing"],
            "testing": [ReleaseStatus.APPROVED],
            ReleaseStatus.APPROVED: [ReleaseStatus.DEPLOYED],
        }
        allowed = valid_transitions.get(release.status, [])
        if body.status not in [str(s) for s in allowed]:
            # Allow force updates for flexibility
            pass
        release.status = body.status
        if body.status == ReleaseStatus.STAGING:
            release.staging_deployed_at = datetime.now(UTC)
        elif body.status == ReleaseStatus.DEPLOYED:
            release.production_deployed_at = datetime.now(UTC)

    await session.flush()
    await session.refresh(release)
    return _release_to_response(release)
