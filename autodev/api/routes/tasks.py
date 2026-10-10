"""Task endpoints: the kanban's backend."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import (
    MERGED_STATUSES,
    AgentLog,
    Priority,
    Project,
    Task,
    TaskArtifact,
    TaskStatus,
    TaskTransition,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    project_id: str | None = None  # optional when only one project exists
    repo: str | None = None  # full name, bare name or role; optional for single-repo projects
    priority: Priority = Priority.NORMAL
    depends_on: list[uuid.UUID] = Field(default_factory=list)
    created_by: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    repo: str | None = None
    project_id: str | None = None


class FeedbackRequest(BaseModel):
    text: str = Field(min_length=1)


class TaskResponse(BaseModel):
    id: str
    ticket_number: int
    title: str
    description: str | None
    project_id: str | None
    repo: str | None
    source: str
    priority: str
    status: str
    assigned_to: str | None
    branch: str | None
    pr_number: int | None
    pr_url: str | None
    summary: str | None
    error: str | None
    attempts: int
    pending_fix: str | None  # kind of the queued fix round, if any
    qa: dict | None  # {"ok": bool, "problems": [...], "skipped": str | None} after stage QA
    depends_on: list[str]
    created_by: str | None
    created_at: datetime
    status_changed_at: datetime
    updated_at: datetime


class LogResponse(BaseModel):
    id: str
    agent_id: str
    level: str
    message: str
    details: str | None
    created_at: datetime


class ArtifactResponse(BaseModel):
    id: str
    kind: str
    name: str
    url: str
    created_at: datetime


class TransitionResponse(BaseModel):
    id: str
    from_status: str
    to_status: str
    reason: str | None
    triggered_by: str | None
    created_at: datetime


def to_response(task: Task) -> TaskResponse:
    fix = (task.metadata_ or {}).get("fix")
    return TaskResponse(
        id=str(task.id),
        ticket_number=task.ticket_number,
        title=task.title,
        description=task.description,
        project_id=task.project_id,
        repo=task.repo,
        source=task.source,
        priority=task.priority,
        status=task.status,
        assigned_to=task.assigned_to,
        branch=task.branch,
        pr_number=task.pr_number,
        pr_url=task.pr_url,
        summary=task.summary,
        error=task.error,
        attempts=task.attempts,
        pending_fix=fix.get("kind") if isinstance(fix, dict) else None,
        qa=(task.metadata_ or {}).get("qa"),
        depends_on=[str(d) for d in task.depends_on or []],
        created_by=task.created_by,
        created_at=task.created_at,
        status_changed_at=task.status_changed_at,
        updated_at=task.updated_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def load_task(session: AsyncSession, task_id: str, *, lock: bool = False) -> Task:
    try:
        pk = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(404, "Task not found") from None
    task = await session.get(Task, pk, with_for_update=lock)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


async def resolve_target(session: AsyncSession, project_id: str | None, repo: str | None) -> tuple[Project, str | None]:
    """Validate project/repo for a new task.

    Repo may stay None for a multi-repo project: the worker then triages the
    task (picks the repo, or splits it into one task per repo).
    """
    if project_id:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(422, f"Unknown project {project_id!r}")
    else:
        projects = list((await session.execute(select(Project).where(Project.enabled))).scalars())
        if repo:
            projects = [p for p in projects if p.repo(repo) is not None]
        if len(projects) != 1:
            raise HTTPException(422, "Specify project_id")
        project = projects[0]

    entry = project.repo(repo)
    if repo and entry is None:
        raise HTTPException(422, f"Repo {repo!r} is not part of project {project.id}")
    return project, entry["name"] if entry else None


def move(session: AsyncSession, task: Task, to: str, reason: str, by: str = "dashboard", **fields: Any) -> None:
    old = task.status
    for key, value in fields.items():
        setattr(task, key, value)
    task.status = to
    task.status_changed_at = datetime.now(UTC)
    session.add(TaskTransition(task_id=task.id, from_status=old, to_status=to, reason=reason, triggered_by=by))
    session.add(AgentLog(agent_id=by, task_id=task.id, level="transition", message=f"📌 {old} → {to} ({reason})"))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List tasks")
async def list_tasks(
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TaskResponse]:
    stmt = select(Task).order_by(Task.status_changed_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status.in_(status))
    return [to_response(t) for t in (await session.execute(stmt)).scalars()]


@router.post("/", summary="Create a task", status_code=201)
async def create_task(body: TaskCreate, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    project, repo = await resolve_target(session, body.project_id, body.repo)
    task = Task(
        title=body.title.strip(),
        description=body.description.strip(),
        project_id=project.id,
        repo=repo,
        priority=body.priority,
        depends_on=body.depends_on,
        created_by=body.created_by or "dashboard",
        status=TaskStatus.QUEUED,
        metadata_={},
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return to_response(task)


@router.get("/{task_id}", summary="Get a task")
async def get_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    return to_response(await load_task(session, task_id))


@router.patch("/{task_id}", summary="Edit a task")
async def update_task(
    task_id: str, body: TaskUpdate, session: Annotated[AsyncSession, Depends(get_session)]
) -> TaskResponse:
    task = await load_task(session, task_id, lock=True)
    if body.title is not None:
        task.title = body.title.strip()
    if body.description is not None:
        task.description = body.description
    if body.priority is not None:
        task.priority = body.priority
    if body.project_id is not None or body.repo is not None:
        if task.status != TaskStatus.QUEUED or task.branch:
            raise HTTPException(409, "Project/repo can only change before work starts")
        project, repo = await resolve_target(session, body.project_id or task.project_id, body.repo)
        task.project_id, task.repo = project.id, repo
    await session.flush()
    return to_response(task)


@router.delete("/{task_id}", summary="Delete a task", status_code=204)
async def delete_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> None:
    task = await load_task(session, task_id, lock=True)
    if task.status in (TaskStatus.IN_PROGRESS, TaskStatus.CI, TaskStatus.DEPLOYING):
        raise HTTPException(409, "Cancel the task first")
    await session.delete(task)


@router.post("/{task_id}/cancel", summary="Stop working on a task")
async def cancel_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    task = await load_task(session, task_id, lock=True)
    if task.status not in (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.CI):
        raise HTTPException(409, f"Can't cancel a task in {task.status}")
    move(session, task, TaskStatus.CANCELLED, "cancelled by owner")
    return to_response(task)


@router.post("/{task_id}/retry", summary="Run a failed or cancelled task again")
async def retry_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    task = await load_task(session, task_id, lock=True)
    if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(409, f"Can't retry a task in {task.status}")
    metadata = dict(task.metadata_ or {})
    if task.error:
        # Keep the reason so the agent knows what went wrong last time.
        metadata["fix"] = {"kind": "retry", "details": f"Previous attempt failed:\n{task.error[:3000]}"}
    move(session, task, TaskStatus.QUEUED, "retry", attempts=0, error=None, metadata_=metadata)
    return to_response(task)


@router.post("/{task_id}/feedback", summary="Ask for changes")
async def feedback(
    task_id: str, body: FeedbackRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> TaskResponse:
    """Owner feedback. Before merge: another round on the same PR. After merge: a follow-up task."""
    task = await load_task(session, task_id, lock=True)
    text = body.text.strip()

    if task.status in MERGED_STATUSES:
        follow_up = Task(
            title=f"{task.title} — доработка",
            description=f"{text}\n\n---\nFollow-up to #{task.ticket_number} ({task.pr_url or 'no PR'}).",
            project_id=task.project_id,
            repo=task.repo,
            priority=task.priority,
            depends_on=[task.id],
            created_by="feedback",
            status=TaskStatus.QUEUED,
            metadata_={},
        )
        session.add(follow_up)
        await session.flush()
        await session.refresh(follow_up)
        return to_response(follow_up)

    if task.status in (TaskStatus.CI, TaskStatus.FAILED, TaskStatus.CANCELLED) and task.pr_number:
        metadata = dict(task.metadata_ or {})
        metadata["fix"] = {"kind": "feedback", "details": text}
        move(session, task, TaskStatus.QUEUED, "owner feedback", metadata_=metadata, error=None)
        return to_response(task)

    if task.status == TaskStatus.QUEUED and not task.branch:
        task.description = f"{task.description or ''}\n\n{text}".strip()
        return to_response(task)

    raise HTTPException(409, f"Can't take feedback while the task is {task.status}")


@router.get("/{task_id}/logs", summary="Task log")
async def task_logs(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    after: datetime | None = Query(default=None, description="Only entries newer than this (for polling)"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[LogResponse]:
    task = await load_task(session, task_id)
    stmt = select(AgentLog).where(AgentLog.task_id == task.id).order_by(AgentLog.created_at).limit(limit)
    if after is not None:
        stmt = stmt.where(AgentLog.created_at > after)
    return [
        LogResponse(
            id=str(log.id),
            agent_id=log.agent_id,
            level=log.level,
            message=log.message,
            details=log.details,
            created_at=log.created_at,
        )
        for log in (await session.execute(stmt)).scalars()
    ]


@router.get("/{task_id}/transitions", summary="Status history")
async def task_transitions(
    task_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[TransitionResponse]:
    task = await load_task(session, task_id)
    rows = await session.execute(
        select(TaskTransition).where(TaskTransition.task_id == task.id).order_by(TaskTransition.created_at)
    )
    return [
        TransitionResponse(
            id=str(t.id),
            from_status=t.from_status,
            to_status=t.to_status,
            reason=t.reason,
            triggered_by=t.triggered_by,
            created_at=t.created_at,
        )
        for t in rows.scalars()
    ]


@router.get("/{task_id}/artifacts", summary="Screenshots and other files")
async def task_artifacts(
    task_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ArtifactResponse]:
    task = await load_task(session, task_id)
    rows = await session.execute(
        select(TaskArtifact.id, TaskArtifact.kind, TaskArtifact.name, TaskArtifact.created_at)
        .where(TaskArtifact.task_id == task.id)
        .order_by(TaskArtifact.created_at.desc())
    )
    return [
        ArtifactResponse(
            id=str(a.id),
            kind=a.kind,
            name=a.name,
            url=f"/api/tasks/{task.id}/artifacts/{a.id}",
            created_at=a.created_at,
        )
        for a in rows.all()
    ]


@router.get("/{task_id}/artifacts/{artifact_id}", summary="Download an artifact")
async def task_artifact(
    task_id: str, artifact_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> Response:
    task = await load_task(session, task_id)
    try:
        artifact = await session.get(TaskArtifact, uuid.UUID(artifact_id))
    except ValueError:
        artifact = None
    if artifact is None or artifact.task_id != task.id:
        raise HTTPException(404, "Artifact not found")
    return Response(
        artifact.content, media_type=artifact.content_type, headers={"Cache-Control": "private, max-age=86400"}
    )
