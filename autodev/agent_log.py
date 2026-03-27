"""Shared agent logging utility."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.models import AgentLog

logger = logging.getLogger(__name__)


async def log_agent(
    session: AsyncSession,
    agent_id: str,
    level: str,
    message: str,
    task_id: str | None = None,
    details: str | None = None,
) -> None:
    """Write an agent log entry to the database."""
    tid = None
    if task_id:
        try:
            tid = uuid.UUID(task_id)
        except ValueError:
            pass
    
    entry = AgentLog(
        id=uuid.uuid4(),
        agent_id=agent_id,
        task_id=tid,
        level=level,
        message=message,
        details=details,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    # Don't commit — caller manages transaction
