"""Task endpoints: the kanban's backend."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev import review
from autodev.api.database import get_session
from autodev.core.models import (
    MERGED_STATUSES,
    AgentLog,
    Chat,
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


class StepCheck(BaseModel):
    done: bool


class VerifyRequest(BaseModel):
    verified: bool


class TaskRef(BaseModel):
    id: str
    ticket_number: int
    title: str
    status: str


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
    # The task's code with its follow-ups as one GitHub compare: {"url", "tasks"}, or {"error"}
    # when a follow-up doesn't replay; None while there's a single PR.
    full_diff: dict | None
    # The owner checks a main task as a whole: a follow-up/part has no plan of its
    # own and shows its main task's "verified" mark.
    test_plan: list[str]  # manual check steps for the owner, from the developer agent
    plan_checked: list[int]  # indices of the test_plan steps the owner has ticked
    plan_earlier: list[int]  # steps ticked on an earlier version, to check again on this one
    verified_at: datetime | None  # when the owner accepted the change on stage
    plan_refreshing: bool  # the owner asked to rebuild the plan; the planner agent hasn't finished yet
    waiting_for: list[TaskRef]  # follow-ups/parts not on stage yet; the check waits for them
    depends_on: list[str]
    parent: TaskRef | None  # the main task, for follow-ups and parts
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


def _ref(task: Task) -> TaskRef:
    return TaskRef(id=str(task.id), ticket_number=task.ticket_number, title=task.title, status=task.status)


def to_response(task: Task, parent: Task | None = None, waiting: list[Task] = ()) -> TaskResponse:
    fix = (task.metadata_ or {}).get("fix")
    with_main = review.checked_with_main(task)
    checked_on = parent if with_main and parent is not None else task
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
        full_diff=(task.metadata_ or {}).get("full_diff"),
        test_plan=[] if with_main else (task.metadata_ or {}).get("test_plan") or [],
        plan_checked=[] if with_main else review.plan_checked(task),
        plan_earlier=[] if with_main else review.plan_earlier(task),
        verified_at=review.verified_at(checked_on),
        plan_refreshing=review.REFRESH in (task.metadata_ or {}),
        waiting_for=[_ref(t) for t in waiting],
        depends_on=[str(d) for d in task.depends_on or []],
        parent=_ref(parent) if parent is not None else None,
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


async def respond(session: AsyncSession, tasks: list[Task]) -> list[TaskResponse]:
    """Responses with each task's parent and open children filled in (two extra queries)."""
    ids = {t.parent_id for t in tasks if t.parent_id}
    parents = {}
    if ids:
        parents = {p.id: p for p in (await session.execute(select(Task).where(Task.id.in_(ids)))).scalars()}
    waiting = await review.waiting_children(session, {t.id for t in tasks if not t.parent_id})
    return [to_response(t, parents.get(t.parent_id), waiting.get(t.id, [])) for t in tasks]


async def respond_one(session: AsyncSession, task: Task) -> TaskResponse:
    return (await respond(session, [task]))[0]


async def resolve_target(session: AsyncSession, project_id: str | None, repo: str | None) -> tuple[Project, str]:
    """Validate project/repo for a new task; the repo is always the project's one."""
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
    if entry is None:
        raise HTTPException(422, f"Repo {repo!r} is not the repo of project {project.id}")
    return project, entry["name"]


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
    parent_id: uuid.UUID | None = Query(default=None, description="Only follow-ups and parts of this task"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TaskResponse]:
    stmt = select(Task).order_by(Task.status_changed_at.desc()).limit(limit)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status.in_(status))
    if parent_id:
        stmt = select(Task).where(Task.parent_id == parent_id).order_by(Task.ticket_number).limit(limit)
    return await respond(session, list((await session.execute(stmt)).scalars()))


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
    return await respond_one(session, task)


@router.get("/{task_id}", summary="Get a task")
async def get_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    return await respond_one(session, await load_task(session, task_id))


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
    return await respond_one(session, task)


@router.delete("/{task_id}", summary="Delete a task", status_code=204)
async def delete_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> None:
    task = await load_task(session, task_id, lock=True)
    if task.status in (TaskStatus.IN_PROGRESS, TaskStatus.CI, TaskStatus.DEPLOYING):
        raise HTTPException(409, "Cancel the task first")
    await session.execute(delete(Chat).where(Chat.subject == "task", Chat.subject_id == str(task.id)))
    await session.delete(task)


@router.post("/{task_id}/cancel", summary="Stop working on a task")
async def cancel_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    task = await load_task(session, task_id, lock=True)
    if task.status not in (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.CI):
        raise HTTPException(409, f"Can't cancel a task in {task.status}")
    move(session, task, TaskStatus.CANCELLED, "cancelled by owner")
    return await respond_one(session, task)


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
    return await respond_one(session, task)


@router.post("/{task_id}/feedback", summary="Ask for changes")
async def feedback(
    task_id: str, body: FeedbackRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> TaskResponse:
    """Owner feedback. Before merge: another round on the same PR. After merge: a follow-up task."""
    task = await load_task(session, task_id, lock=True)
    return await respond_one(session, await request_changes(session, task, body.text))


async def request_changes(session: AsyncSession, task: Task, text: str, by: str = "feedback") -> Task:
    """Ask for changes to *task* (locked). Returns the task that will do them: *task* or a new follow-up.

    *by* is who asked: the follow-up's ``created_by`` ("feedback" from the owner directly,
    "chat" when the owner approved a chat agent's proposal).
    """
    text = text.strip()
    if task.status in MERGED_STATUSES:
        follow_up = Task(
            title=f"{task.title.removesuffix(' — доработка')} — доработка",
            description=f"{text}\n\n---\nFollow-up to #{task.ticket_number} ({task.pr_url or 'no PR'}).",
            project_id=task.project_id,
            repo=task.repo,
            priority=task.priority,
            depends_on=[task.id],
            parent_id=task.root_id,
            created_by=by,
            status=TaskStatus.QUEUED,
            metadata_={},
        )
        session.add(follow_up)
        # The main task now includes unfinished work: the owner will check it again.
        root = task if task.parent_id is None else await session.get(Task, task.parent_id, with_for_update=True)
        if root is not None:
            root.metadata_ = review.unverify(root.metadata_ or {})
        await session.flush()
        await session.refresh(follow_up)
        return follow_up

    if task.status in (TaskStatus.CI, TaskStatus.FAILED, TaskStatus.CANCELLED) and task.pr_number:
        metadata = dict(task.metadata_ or {})
        metadata["fix"] = {"kind": "feedback", "details": text}
        move(session, task, TaskStatus.QUEUED, "owner feedback", metadata_=metadata, error=None)
        return task

    if task.status == TaskStatus.QUEUED and not task.branch:
        task.description = f"{task.description or ''}\n\n{text}".strip()
        return task

    raise HTTPException(409, f"Can't take feedback while the task is {task.status}")


# Before /plan/{step}, which would take "refresh" for a step number.
@router.post("/{task_id}/plan/refresh", summary="Rebuild the test plan from the task, its follow-ups and stage")
async def refresh_plan(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> TaskResponse:
    """Queue a rebuild of the main task's one plan; the worker's planner agent writes it again."""
    task = await load_task(session, task_id, lock=True)
    try:
        review.request_refresh(task)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from None
    session.add(AgentLog(agent_id="dashboard", task_id=task.id, level="info", message="🧭 Запрошена пересборка плана"))
    return await respond_one(session, task)


@router.post("/{task_id}/plan/{step}", summary="Tick or untick a test-plan step")
async def check_step(
    task_id: str, step: int, body: StepCheck, session: Annotated[AsyncSession, Depends(get_session)]
) -> TaskResponse:
    task = await load_task(session, task_id, lock=True)
    waiting = (await review.waiting_children(session, {task.id})).get(task.id, [])
    try:
        review.check_step(task, step, body.done, waiting)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from None
    return await respond_one(session, task)


@router.post("/{task_id}/verify", summary="Mark a task checked on stage (or take the mark back)")
async def verify_task(
    task_id: str, body: VerifyRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> TaskResponse:
    task = await load_task(session, task_id, lock=True)
    waiting = (await review.waiting_children(session, {task.id})).get(task.id, [])
    try:
        review.set_verified(task, body.verified, waiting)
    except review.ReviewError as exc:
        raise HTTPException(409, str(exc)) from None
    return await respond_one(session, task)


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
