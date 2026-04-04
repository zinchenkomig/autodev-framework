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
from autodev.core.github_ops import extract_pr_info, merge_pr, merge_release_pr
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
    release_prs: list[dict] = []
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


def _release_to_response(release: Release, merge_results: list[dict] | None = None) -> ReleaseResponse:
    return ReleaseResponse(
        id=str(release.id),
        version=release.version,
        status=release.status,
        tasks=[str(t) for t in (release.tasks or [])],
        release_notes=release.release_notes,
        release_prs=release.release_prs or [],
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
            merge_results = await _merge_release_prs_to_main(release, session)

    await session.flush()
    await session.refresh(release)
    return _release_to_response(release, merge_results)


async def _merge_release_prs(release: Release, session: AsyncSession) -> list[dict]:
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

        logger.info("PR #%d in %s merge result: %s", pr_number, repo, "success" if success else "failed")
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


async def _merge_release_prs_to_main(release: Release, session: AsyncSession) -> list[dict]:
    """Merge release PRs (stage → main) that were created during release formation."""
    results: list[dict] = []
    release_prs = release.release_prs or []

    if not release_prs:
        logger.warning("No release PRs found for release %s", release.version)
        return results

    for rp in release_prs:
        repo = rp.get("repo", "")
        pr_number = rp.get("pr_number")
        pr_url = rp.get("pr_url", "")

        if not repo or not pr_number:
            continue

        logger.info("Merging release PR #%d stage→main for repo %s", pr_number, repo)
        try:
            success = await merge_release_pr(repo, pr_number)
        except Exception as exc:
            logger.error("Error merging release PR #%d for %s: %s", pr_number, repo, exc)
            success = False
            results.append(
                {"repo": repo, "pr_number": pr_number, "pr_url": pr_url, "success": False, "error": str(exc)}
            )
            continue

        logger.info("Release PR #%d for %s: %s", pr_number, repo, "success" if success else "failed")
        results.append({"repo": repo, "pr_number": pr_number, "pr_url": pr_url, "success": success})

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


@router.post("/trigger", summary="Manually trigger release formation")
async def trigger_release(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Manually trigger Release Manager to form a release from ready_to_release tasks."""
    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from autodev.release_worker import check_and_create_release, notify_release

    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://autodev:autodev@localhost:5432/autodev")
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        result = await check_and_create_release(factory)
        if result:
            await notify_release(result)
            return {"status": "released", **result}

        # Check how many SP are waiting
        ready = await session.execute(select(Task).where(Task.status == "ready_to_release"))
        tasks = ready.scalars().all()
        total_sp = sum(t.story_points or 1 for t in tasks)

        return {
            "status": "not_enough_sp",
            "tasks": len(tasks),
            "total_sp": total_sp,
            "min_required": 10,
        }
    finally:
        await engine.dispose()


class ReleaseFeedbackBody(BaseModel):
    comment: str
    task_ids: list[str] = []  # specific tasks, or empty for general feedback


@router.post("/{release_id}/feedback", summary="Submit feedback on staging release")
async def release_feedback(
    release_id: str,
    body: ReleaseFeedbackBody,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Submit feedback on a staging release. Creates follow-up tasks."""
    try:
        uid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid release ID")

    release = await session.get(Release, uid)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    created = []

    if body.task_ids:
        # Feedback for specific tasks
        for tid_str in body.task_ids:
            try:
                tid = uuid.UUID(tid_str)
            except ValueError:
                continue
            task = await session.get(Task, tid)
            if not task:
                continue

            followup = Task(
                id=uuid.uuid4(),
                title=f"Правки: {task.title[:80]}",
                description=(
                    f'Правки к задаче "{task.title}" (релиз {release.version}):\n\n'
                    f"{body.comment}\n\n---\n"
                    f"Original task: {tid_str}\nRelease: {release.version}\n"
                    f"PR: {task.pr_url or 'N/A'}"
                ),
                status="queued",
                priority=task.priority,
                repo=task.repo,
                story_points=max(1, (task.story_points or 1) // 2),  # fixes are usually simpler
                created_by="user-feedback",
                task_type="hotfix",
            )
            session.add(followup)
            await session.flush()
            created.append({"id": str(followup.id), "title": followup.title})
    else:
        # General feedback — create one task
        followup = Task(
            id=uuid.uuid4(),
            title=f"Правки по релизу {release.version}",
            description=f"Фидбек по релизу {release.version}:\n\n{body.comment}",
            status="queued",
            priority="high",
            repo="",  # will be determined by PM
            story_points=3,
            created_by="user-feedback",
            task_type="hotfix",
        )
        session.add(followup)
        await session.flush()
        created.append({"id": str(followup.id), "title": followup.title})

    return {
        "status": "feedback_received",
        "tasks_created": len(created),
        "tasks": created,
        "release": release.version,
    }


@router.post("/{release_id}/remove-task/{task_id}", summary="Remove task from release")
async def remove_task_from_release(
    release_id: str,
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Remove a task from release: revert merge commit on develop, remove from release, reset task."""
    import asyncio
    import os
    import tempfile

    import httpx

    try:
        release_uuid = uuid.UUID(release_id)
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ID format")

    release = await session.get(Release, release_uuid)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    task = await session.get(Task, task_uuid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    actions = []
    github_token = os.environ.get("GITHUB_TOKEN", "")

    # 1. Revert the merge commit on develop (if PR was merged)
    if task.pr_url and task.repo and github_token:
        try:
            # Get merge commit SHA
            parts = task.pr_url.rstrip("/").split("/")
            pr_number = parts[-1]

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{task.repo}/pulls/{pr_number}",
                    headers={"Authorization": f"token {github_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    pr_data = resp.json()
                    merge_sha = pr_data.get("merge_commit_sha")
                    was_merged = pr_data.get("merged", False)

                    if was_merged and merge_sha:
                        # Git revert via clone + push
                        tmpdir = tempfile.mkdtemp(prefix="revert-")
                        clone_url = f"https://x-access-token:{github_token}@github.com/{task.repo}.git"

                        proc = await asyncio.create_subprocess_exec(
                            "/bin/bash",
                            "-c",
                            f"git clone -b develop {clone_url} {tmpdir} && "
                            f"cd {tmpdir} && "
                            f"git revert {merge_sha} --no-edit -m 1 && "
                            f"git push origin develop",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

                        if proc.returncode == 0:
                            actions.append(f"Reverted merge commit {merge_sha[:12]} on develop")
                        else:
                            actions.append(f"Failed to revert: {stderr.decode()[:200]}")

                        await asyncio.create_subprocess_exec("/bin/rm", "-rf", tmpdir)
                    elif not was_merged:
                        # PR not merged — just close it
                        await client.patch(
                            f"https://api.github.com/repos/{task.repo}/pulls/{pr_number}",
                            headers={"Authorization": f"token {github_token}"},
                            json={"state": "closed"},
                            timeout=10.0,
                        )
                        actions.append(f"Closed unmerged PR #{pr_number}")
        except Exception as e:
            actions.append(f"Revert error: {e}")

    # 2. Delete branch
    if task.branch and task.repo and github_token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"https://api.github.com/repos/{task.repo}/git/refs/heads/{task.branch}",
                    headers={"Authorization": f"token {github_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 204:
                    actions.append(f"Deleted branch {task.branch}")
        except Exception:
            pass

    # 3. Remove task from release
    if release.tasks and task_uuid in release.tasks:
        release.tasks = [t for t in release.tasks if t != task_uuid]
        actions.append(f"Removed from release {release.version}")

    # 4. Reset task
    task.status = "queued"
    task.release_id = None
    task.branch = None
    task.pr_number = None
    task.pr_url = None
    task.assigned_to = None
    actions.append("Task reset to queued")

    return {
        "status": "removed",
        "task": task.title,
        "release": release.version,
        "actions": actions,
    }
