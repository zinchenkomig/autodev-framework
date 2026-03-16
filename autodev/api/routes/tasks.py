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
    created_by: str | None
    created_at: datetime
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
        created_by=task.created_by,
        created_at=task.created_at,
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
