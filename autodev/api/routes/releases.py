"""Release management REST endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.github_ops import extract_pr_info, merge_develop_to_main, merge_pr
from autodev.core.models import Release, ReleaseStatus, Task

logger = logging.getLogger(__name__)

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
    reverted_at: datetime | None = None
    reverted_by: str | None = None
    previous_status: str | None = None
    created_at: datetime
    merge_results: list[dict] = []

    model_config = {"from_attributes": True}


def _release_to_response(
    release: Release, merge_results: list[dict] | None = None
) -> ReleaseResponse:
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
        reverted_at=release.reverted_at,
        reverted_by=release.reverted_by,
        previous_status=release.previous_status,
        created_at=release.created_at,
        merge_results=merge_results or [],
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

    merge_results: list[dict] = []

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
            # Merge PRs for all tasks in this release
            merge_results = await _merge_release_prs(release, session)

        elif body.status == ReleaseStatus.DEPLOYED:
            release.production_deployed_at = datetime.now(UTC)
            # Merge develop to main for all repos
            merge_results = await _merge_develop_to_main_for_release(release, session)

    await session.flush()
    await session.refresh(release)
    return _release_to_response(release, merge_results)


async def _merge_release_prs(
    release: Release, session: AsyncSession
) -> list[dict]:
    """Merge all PRs associated with release tasks. Returns list of results."""
    results: list[dict] = []
    task_uuids = release.tasks or []
    if not task_uuids:
        return results

    for task_uuid in task_uuids:
        task = await session.get(Task, task_uuid)
        if task is None:
            continue
        if not task.pr_url:
            logger.info("Task %s has no pr_url, skipping merge", task.id)
            continue

        info = extract_pr_info(task.pr_url)
        if info is None:
            logger.warning("Could not parse pr_url for task %s: %s", task.id, task.pr_url)
            results.append(
                {
                    "task_id": str(task.id),
                    "pr_url": task.pr_url,
                    "success": False,
                    "error": "Could not parse PR URL",
                }
            )
            continue

        repo, pr_number = info
        logger.info("Merging PR #%d in %s for task %s", pr_number, repo, task.id)
        try:
            success = await merge_pr(repo, pr_number)
        except Exception as exc:
            logger.error("Error merging PR #%d in %s: %s", pr_number, repo, exc)
            success = False
            results.append(
                {
                    "task_id": str(task.id),
                    "pr_url": task.pr_url,
                    "repo": repo,
                    "pr_number": pr_number,
                    "success": False,
                    "error": str(exc),
                }
            )
            continue

        logger.info(
            "PR #%d in %s merge result: %s", pr_number, repo, "success" if success else "failed"
        )
        results.append(
            {
                "task_id": str(task.id),
                "pr_url": task.pr_url,
                "repo": repo,
                "pr_number": pr_number,
                "success": success,
            }
        )

    return results


async def _merge_develop_to_main_for_release(
    release: Release, session: AsyncSession
) -> list[dict]:
    """Merge develop into main for each unique repo in the release tasks."""
    results: list[dict] = []
    task_uuids = release.tasks or []
    if not task_uuids:
        return results

    repos: set[str] = set()
    for task_uuid in task_uuids:
        task = await session.get(Task, task_uuid)
        if task and task.repo:
            repos.add(task.repo)

    for repo in repos:
        logger.info("Merging develop→main for repo %s", repo)
        try:
            success = await merge_develop_to_main(repo)
        except Exception as exc:
            logger.error("Error merging develop→main for %s: %s", repo, exc)
            success = False
            results.append({"repo": repo, "success": False, "error": str(exc)})
            continue

        logger.info(
            "develop→main merge for %s: %s", repo, "success" if success else "failed"
        )
        results.append({"repo": repo, "success": success})

    return results


# Rollback status mapping: current → previous
_ROLLBACK_MAP: dict[str, str] = {
    ReleaseStatus.DEPLOYED: ReleaseStatus.APPROVED,
    ReleaseStatus.APPROVED: ReleaseStatus.STAGING,
    ReleaseStatus.STAGING: ReleaseStatus.DRAFT,
    "testing": ReleaseStatus.STAGING,
    ReleaseStatus.PENDING_APPROVAL: ReleaseStatus.STAGING,
}


@router.post("/{release_id}/rollback", summary="Roll back release one step")
async def rollback_release(
    release_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Roll back a release to the previous lifecycle step."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")
    release = await session.get(Release, uid)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    previous = _ROLLBACK_MAP.get(release.status)
    if previous is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot roll back release in '{release.status}' status",
        )

    release.previous_status = release.status
    release.status = previous
    await session.flush()
    await session.refresh(release)
    return _release_to_response(release)


@router.post("/{release_id}/cancel", summary="Cancel a release")
async def cancel_release(
    release_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Cancel a release (cannot cancel an already-deployed release)."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")
    release = await session.get(Release, uid)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    if release.status == ReleaseStatus.DEPLOYED:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a deployed release. Use /revert to roll back production.",
        )
    if release.status == ReleaseStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="Release is already cancelled")

    release.previous_status = release.status
    release.status = ReleaseStatus.CANCELLED
    await session.flush()
    await session.refresh(release)
    return _release_to_response(release)


@router.post("/{release_id}/revert", summary="Revert a deployed release in production")
async def revert_release(
    release_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Revert a deployed release: marks it as reverted and records the timestamp."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")
    release = await session.get(Release, uid)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    if release.status != ReleaseStatus.DEPLOYED:
        raise HTTPException(
            status_code=400,
            detail=f"Only deployed releases can be reverted (current status: {release.status})",
        )

    # Find previous deployed release for context
    result = await session.execute(
        select(Release)
        .where(
            Release.status == ReleaseStatus.DEPLOYED,
            Release.id != release.id,
        )
        .order_by(Release.production_deployed_at.desc())
        .limit(1)
    )
    previous_release = result.scalar_one_or_none()

    release.previous_status = release.status
    release.status = ReleaseStatus.REVERTED
    release.reverted_at = datetime.now(UTC)
    release.reverted_by = "user"

    revert_info: dict = {
        "reverted_release": str(release.id),
        "reverted_version": release.version,
    }
    if previous_release is not None:
        revert_info["previous_release_id"] = str(previous_release.id)
        revert_info["previous_version"] = previous_release.version
        logger.info(
            "Reverting release %s (%s) — previous deployed release was %s (%s)",
            release.id,
            release.version,
            previous_release.id,
            previous_release.version,
        )
    else:
        logger.warning(
            "Reverting release %s (%s) — no previous deployed release found",
            release.id,
            release.version,
        )

    await session.flush()
    await session.refresh(release)
    return _release_to_response(release, [revert_info])


@router.post("/{release_id}/unapprove", summary="Remove approval from a release")
async def unapprove_release(
    release_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResponse:
    """Remove approval from a release (transitions back to staging status)."""
    try:
        release_uuid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID format")

    release = await session.get(Release, release_uuid)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    if release.status not in (
        ReleaseStatus.APPROVED,
        ReleaseStatus.STAGING,
        "testing",
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot unapprove release in {release.status} status",
        )

    release.status = ReleaseStatus.STAGING
    release.approved_by = None
    release.approved_at = None
    await session.flush()
    await session.refresh(release)
    return _release_to_response(release)
