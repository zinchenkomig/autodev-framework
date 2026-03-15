"""Task management REST endpoints.

CRUD operations for development tasks plus queue submission.

TODO: Add pagination to list endpoint.
TODO: Add filtering by status, agent, and date range.
TODO: Add bulk task creation endpoint.
TODO: Connect to real database session.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class TaskCreate(BaseModel):
    """Request body for creating a new task.

    TODO: Add priority field.
    TODO: Add parent_task_id for subtasks.
    """

    title: str
    description: str = ""


class TaskResponse(BaseModel):
    """Task representation returned by the API.

    TODO: Add assigned_agent and status fields.
    """

    id: int
    title: str
    description: str


@router.get("/", summary="List all tasks")
async def list_tasks() -> list[TaskResponse]:
    """Return all tasks.

    TODO: Query from database with pagination.
    """
    # TODO: Implement database query
    return []


@router.post("/", summary="Create a task", status_code=201)
async def create_task(body: TaskCreate) -> TaskResponse:
    """Create and enqueue a new development task.

    TODO: Persist to database.
    TODO: Enqueue to TaskQueue.
    TODO: Publish task.created domain event.
    """
    # TODO: Implement task creation
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/{task_id}", summary="Get task by ID")
async def get_task(task_id: int) -> TaskResponse:
    """Fetch a single task by its ID.

    TODO: Query from database.
    """
    # TODO: Implement lookup
    raise HTTPException(status_code=404, detail="Task not found")


@router.delete("/{task_id}", summary="Delete a task", status_code=204)
async def delete_task(task_id: int) -> None:
    """Delete a task.

    TODO: Soft-delete with audit trail.
    """
    # TODO: Implement deletion
    raise HTTPException(status_code=501, detail="Not implemented")
