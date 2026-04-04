"""Task management REST endpoints.

CRUD operations for development tasks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Task

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    source: str = "manual"
    priority: str = "normal"
    status: str = "queued"
    assigned_to: str | None = None
    repo: str | None = None
    issue_number: int | None = None
    pr_number: int | None = None
    created_by: str | None = None
    metadata_: dict[str, Any] | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    assigned_to: str | None = None
    repo: str | None = None
    issue_number: int | None = None
    pr_number: int | None = None
    metadata_: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str | None
    source: str
    priority: str
    status: str
    assigned_to: str | None
    repo: str | None
    issue_number: int | None
    pr_number: int | None
    pr_url: str | None
    branch: str | None
    story_points: int
    depends_on: list[str] | None
    created_by: str | None
    created_at: datetime
    status_changed_at: datetime | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


def _task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),
        title=task.title,
        description=task.description,
        source=task.source,
        priority=task.priority,
        status=task.status,
        assigned_to=task.assigned_to,
        repo=task.repo,
        issue_number=task.issue_number,
        pr_number=task.pr_number,
        pr_url=task.pr_url,
        branch=task.branch,
        story_points=task.story_points or 1,
        depends_on=[str(d) for d in task.depends_on] if task.depends_on else None,
        created_by=task.created_by,
        created_at=task.created_at,
        status_changed_at=task.status_changed_at,
        updated_at=task.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List all tasks")
async def list_tasks(
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = Query(default=None),
    repo: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[TaskResponse]:
    """Return tasks with optional filtering."""
    stmt = select(Task)
    if status:
        stmt = stmt.where(Task.status == status)
    if repo:
        stmt = stmt.where(Task.repo == repo)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    stmt = stmt.offset(offset).limit(limit).order_by(Task.created_at.desc())
    result = await session.execute(stmt)
    tasks = result.scalars().all()
    return [_task_to_response(t) for t in tasks]


@router.post("/", summary="Create a task", status_code=201)
async def create_task(
    body: TaskCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskResponse:
    """Create and persist a new development task."""
    task = Task(
        title=body.title,
        description=body.description,
        source=body.source,
        priority=body.priority,
        status=body.status,
        assigned_to=body.assigned_to,
        repo=body.repo,
        issue_number=body.issue_number,
        pr_number=body.pr_number,
        created_by=body.created_by,
        metadata_=body.metadata_ or {},
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return _task_to_response(task)


@router.get("/{task_id}", summary="Get task by ID")
async def get_task(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskResponse:
    """Fetch a single task by its UUID."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task ID format")
    task = await session.get(Task, uid)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)


@router.patch("/{task_id}", summary="Update a task")
async def update_task(
    task_id: str,
    body: TaskUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TaskResponse:
    """Partially update a task."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task ID format")
    task = await session.get(Task, uid)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    task.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(task)
    return _task_to_response(task)


@router.delete("/{task_id}", summary="Delete a task", status_code=204)
async def delete_task(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete a task by its UUID."""
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task ID format")
    task = await session.get(Task, uid)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await session.delete(task)


# ---------------------------------------------------------------------------
# Task Logs
# ---------------------------------------------------------------------------


class TaskLogResponse(BaseModel):
    id: str
    agent_id: str
    level: str
    message: str
    details: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{task_id}/logs", summary="Get logs for a specific task")
async def get_task_logs(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(100, ge=1, le=500),
) -> list[TaskLogResponse]:
    """Get agent logs for a specific task."""
    from autodev.core.models import AgentLog

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await session.execute(
        select(AgentLog).where(AgentLog.task_id == tid).order_by(AgentLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()

    return [
        TaskLogResponse(
            id=str(log.id),
            agent_id=log.agent_id,
            level=log.level,
            message=log.message,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]


class TransitionResponse(BaseModel):
    id: str
    from_status: str
    to_status: str
    reason: str | None
    triggered_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{task_id}/transitions", summary="Get status transition history")
async def get_task_transitions(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TransitionResponse]:
    """Get full status transition history for a task."""
    from autodev.core.models import TaskTransition

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await session.execute(
        select(TaskTransition).where(TaskTransition.task_id == tid).order_by(TaskTransition.created_at.asc())
    )
    transitions = result.scalars().all()

    return [
        TransitionResponse(
            id=str(t.id),
            from_status=t.from_status,
            to_status=t.to_status,
            reason=t.reason,
            triggered_by=t.triggered_by,
            created_at=t.created_at,
        )
        for t in transitions
    ]


@router.post("/{task_id}/restart", summary="Full restart task - delete branch, close PR, requeue")
async def restart_task(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Fully restart a task: delete GitHub branch, close PR, reset to queued."""
    import os

    import httpx

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo = task.repo
    branch = task.branch
    pr_number = task.pr_number

    results = {"task_id": task_id, "actions": []}

    # 1. Close PR if exists
    if pr_number and repo and github_token:
        try:
            async with httpx.AsyncClient() as client:
                # Close the PR
                resp = await client.patch(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                    headers={"Authorization": f"token {github_token}"},
                    json={"state": "closed"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    results["actions"].append(f"Closed PR #{pr_number}")
                else:
                    results["actions"].append(f"Failed to close PR: {resp.status_code}")
        except Exception as e:
            results["actions"].append(f"Error closing PR: {e}")

    # 2. Delete branch if exists
    if branch and repo and github_token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}",
                    headers={"Authorization": f"token {github_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 204:
                    results["actions"].append(f"Deleted branch {branch}")
                elif resp.status_code == 422:
                    results["actions"].append(f"Branch {branch} not found")
                else:
                    results["actions"].append(f"Failed to delete branch: {resp.status_code}")
        except Exception as e:
            results["actions"].append(f"Error deleting branch: {e}")

    # 3. Reset task
    old_status = task.status
    task.status = "queued"
    task.status_changed_at = datetime.now(UTC)
    task.assigned_to = None
    task.branch = None
    task.pr_number = None
    task.pr_url = None

    # 4. Reset developer agent if it was working on this task
    from autodev.core.models import Agent, AgentLog

    dev_agent = await session.get(Agent, "developer")
    if dev_agent and str(dev_agent.current_task_id) == task_id:
        dev_agent.status = "idle"
        dev_agent.current_task_id = None
        results["actions"].append("Reset developer agent")

    # 5. Record status transition
    from autodev.core.models import TaskTransition

    session.add(
        TaskTransition(
            task_id=tid,
            from_status=old_status,
            to_status="queued",
            reason="full restart",
            triggered_by="user",
        )
    )
    log_transition = AgentLog(
        agent_id="orchestrator",
        task_id=tid,
        level="transition",
        message=f"📌 Status: {old_status} → queued (full restart)",
    )
    session.add(log_transition)

    results["actions"].append("Task reset to queued")
    results["status"] = "restarted"

    return results


class RestartStagingBody(BaseModel):
    description: str = ""


@router.post(
    "/{task_id}/restart-staging",
    summary="Restart task from staging - revert merge, requeue as hotfix",
)
async def restart_staging_task(
    task_id: str,
    body: RestartStagingBody,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Restart a staging task: revert the merged PR on stage, remove from release, requeue as hotfix.

    The task goes back to queued with task_type=hotfix so it bypasses release manager
    and goes straight to staging after autoreview.
    """
    import os

    import httpx

    from autodev.core.github_ops import revert_pr_merge
    from autodev.core.models import Release

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "staging":
        raise HTTPException(status_code=400, detail=f"Task must be in staging status (current: {task.status})")

    actions = []
    github_token = os.environ.get("GITHUB_TOKEN", "")

    # 1. Revert the merged PR on stage
    if task.pr_number and task.repo:
        # Extract repo name from full path (e.g., "zinchenkomig/great_alerter_backend" -> "great_alerter_backend")
        repo_name = task.repo.split("/")[-1] if "/" in task.repo else task.repo
        revert_result = await revert_pr_merge(repo_name, task.pr_number)
        if revert_result["success"]:
            actions.append(f"✅ Reverted PR #{task.pr_number} merge on stage (sha: {revert_result['revert_sha'][:8]})")
        else:
            actions.append(f"⚠️ Revert failed: {revert_result['error']}")

    # 2. Close PR if still open (shouldn't be, but just in case)
    if task.pr_number and task.repo and github_token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.patch(
                    f"https://api.github.com/repos/{task.repo}/pulls/{task.pr_number}",
                    headers={"Authorization": f"token {github_token}"},
                    json={"state": "closed"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    actions.append(f"Closed PR #{task.pr_number}")
        except Exception as e:
            actions.append(f"Failed to close PR: {e}")

    # 3. Delete feature branch
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
                elif resp.status_code == 422:
                    actions.append(f"Branch {task.branch} already deleted")
        except Exception as e:
            actions.append(f"Failed to delete branch: {e}")

    # 4. Remove task from release
    if task.release_id:
        release = await session.get(Release, task.release_id)
        if release and release.tasks and tid in release.tasks:
            release.tasks = [t for t in release.tasks if t != tid]
            actions.append(f"Removed from release {release.version}")
        task.release_id = None

    # 5. Append restart feedback to description if provided
    if body.description.strip():
        feedback = body.description.strip()
        restart_note = (
            f"\n\n---\n⚠️ **Restart feedback:**\n{feedback}\n"
            f"(Restarted from staging at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC)"
        )
        task.description = (task.description or "") + restart_note
        actions.append("Appended restart feedback to description")

    task.status = "queued"
    task.status_changed_at = datetime.now(UTC)
    task.task_type = "hotfix"
    task.assigned_to = None
    task.branch = None
    task.pr_number = None
    task.pr_url = None
    task.updated_at = datetime.now(UTC)

    actions.append("Task reset to queued as hotfix (bypasses release manager)")

    # 6. Reset developer agent if stuck on this task
    from autodev.core.models import Agent

    dev_agent = await session.get(Agent, "developer")
    if dev_agent and str(dev_agent.current_task_id) == task_id:
        dev_agent.status = "idle"
        dev_agent.current_task_id = None
        actions.append("Reset developer agent")

    # 7. Log the restart with status transition
    from autodev.core.models import AgentLog

    old_status = "staging"
    from autodev.core.models import TaskTransition

    session.add(
        TaskTransition(
            task_id=tid,
            from_status="staging",
            to_status="queued",
            reason="restart from staging",
            triggered_by="user",
        )
    )
    log_transition = AgentLog(
        agent_id="orchestrator",
        task_id=tid,
        level="transition",
        message=f"📌 Status: {old_status} → queued (restart from staging)",
    )
    session.add(log_transition)

    log = AgentLog(
        agent_id="user",
        task_id=tid,
        level="warning",
        message="Task restarted from staging",
        details="\n".join(actions),
    )
    session.add(log)

    return {
        "task_id": task_id,
        "status": "restarted",
        "task_type": "hotfix",
        "actions": actions,
    }


class RequestChangesBody(BaseModel):
    comment: str
    priority: str = "high"


@router.post("/{task_id}/request-changes", summary="Request changes - create follow-up task")
async def request_changes(
    task_id: str,
    body: RequestChangesBody,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Create a follow-up task for requested changes."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Create follow-up task with reference to original
    followup = Task(
        id=uuid.uuid4(),
        title=f"Правки: {task.title}",
        description=f"Правки к задаче [{task.title}]:\n\n{body.comment}\n\n---\nOriginal task: {task_id}\nPR: {task.pr_url or 'N/A'}",
        status="queued",
        priority=task.priority,
        repo=task.repo,
        created_by="user",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(followup)
    await session.flush()

    return {
        "status": "created",
        "followup_task_id": str(followup.id),
        "followup_title": followup.title,
    }


@router.post("/{task_id}/release", summary="Merge PR and mark as released")
async def release_task(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Merge the PR on GitHub and mark task as released."""
    import os

    import httpx

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.pr_number or not task.repo:
        raise HTTPException(status_code=400, detail="No PR to merge")

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN not configured")

    # Merge PR
    repo = task.repo
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"https://api.github.com/repos/{repo}/pulls/{task.pr_number}/merge",
                headers={"Authorization": f"token {github_token}"},
                json={"merge_method": "squash"},
                timeout=15.0,
            )

            if resp.status_code == 200:
                task.status = "released"
                return {"status": "released", "merged": True}
            else:
                error = resp.json().get("message", resp.text)
                raise HTTPException(status_code=resp.status_code, detail=f"Merge failed: {error}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
