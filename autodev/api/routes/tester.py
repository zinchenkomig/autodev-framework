"""Tester Agent API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Task, TaskStatus

router = APIRouter(tags=["tester"])


class TriggerResponse(BaseModel):
    message: str
    tasks_queued: int


@router.post("/trigger", summary="Trigger tester agent")
async def trigger_tester(
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TriggerResponse:
    """Trigger the tester agent to process tasks in review."""
    # Count tasks in review
    stmt = select(Task).where(Task.status == TaskStatus.REVIEW)
    result = await session.execute(stmt)
    tasks = result.scalars().all()

    if tasks:
        # Import here to avoid circular imports
        from autodev.agents.tester import TesterAgent

        async def run_tester():
            from autodev.api.database import async_session_factory

            async with async_session_factory() as sess:
                agent = TesterAgent(sess)
                await agent.run()
                await sess.commit()

        background_tasks.add_task(run_tester)

    return TriggerResponse(
        message="Tester agent triggered",
        tasks_queued=len(tasks),
    )
