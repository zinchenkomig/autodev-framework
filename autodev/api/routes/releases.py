"""Release history. Releases are started per project: POST /api/projects/{id}/release."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Release

router = APIRouter()


class ReleasePR(BaseModel):
    repo: str
    pr_number: int
    pr_url: str
    merged: bool = False


class ReleaseResponse(BaseModel):
    id: str
    project_id: str | None
    version: str
    status: str
    tasks: list[str]
    release_notes: str | None
    release_prs: list[ReleasePR]
    error: str | None
    created_by: str | None
    production_deployed_at: datetime | None
    created_at: datetime


def release_to_response(release: Release) -> ReleaseResponse:
    return ReleaseResponse(
        id=str(release.id),
        project_id=release.project_id,
        version=release.version,
        status=release.status,
        tasks=[str(t) for t in release.tasks or []],
        release_notes=release.release_notes,
        release_prs=[ReleasePR(**p) for p in release.release_prs or []],
        error=release.error,
        created_by=release.created_by,
        production_deployed_at=release.production_deployed_at,
        created_at=release.created_at,
    )


@router.get("/", summary="List releases")
async def list_releases(
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ReleaseResponse]:
    stmt = select(Release).order_by(Release.created_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(Release.project_id == project_id)
    return [release_to_response(r) for r in (await session.execute(stmt)).scalars()]


@router.get("/{release_id}", summary="Get a release")
async def get_release(release_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> ReleaseResponse:
    try:
        release = await session.get(Release, uuid.UUID(release_id))
    except ValueError:
        release = None
    if release is None:
        raise HTTPException(404, "Release not found")
    return release_to_response(release)
