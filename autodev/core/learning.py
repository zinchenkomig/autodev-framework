"""Learning system — agents learn from past outcomes (Issue #16).

Provides :class:`LearningStore` backed by SQLAlchemy async sessions.
Agents record task outcomes (success/failure + lessons) and can retrieve
relevant context before starting a new task to avoid repeating mistakes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from autodev.core.models import Base, Task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ORM Model
# ---------------------------------------------------------------------------


class Lesson(Base):
    """Persistent record of a task outcome and any lesson learned.

    Attributes:
        id: Auto-incrementing primary key.
        task_id: UUID of the task this lesson relates to (may be NULL if task deleted).
        agent_id: Identifier of the agent that executed the task.
        success: Whether the task completed successfully.
        error: Error message if the task failed (NULL on success).
        lesson_text: Human/LLM-authored lesson text to help future runs.
        created_at: Timestamp when this record was inserted.
    """

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lesson_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Lesson id={self.id} agent={self.agent_id!r} "
            f"task={self.task_id!r} success={self.success}>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the lesson to a plain dict."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "success": self.success,
            "error": self.error,
            "lesson_text": self.lesson_text,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# LearningStore
# ---------------------------------------------------------------------------


class LearningStore:
    """Async store for recording and querying agent learning outcomes.

    Args:
        session_factory: An :class:`~sqlalchemy.ext.asyncio.async_sessionmaker`
            bound to the target database.

    Example::

        store = LearningStore(session_factory)
        await store.record_outcome(
            task_id=str(task.id),
            agent_id="developer-1",
            success=False,
            error="ImportError: No module named 'foo'",
            lesson="Always check pyproject.toml for missing deps before coding.",
        )
        context = await store.build_context(task)
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        task_id: str | uuid.UUID | None,
        agent_id: str | None,
        success: bool,
        error: str | None = None,
        lesson: str | None = None,
    ) -> Lesson:
        """Persist a task outcome and optional lesson.

        Args:
            task_id: UUID of the related task (string or UUID).
            agent_id: Identifier of the agent that ran the task.
            success: ``True`` if the task succeeded, ``False`` otherwise.
            error: Error message on failure; ``None`` on success.
            lesson: Free-form lesson text for future runs.

        Returns:
            The newly created :class:`Lesson` ORM object.
        """
        lesson_obj = Lesson(
            task_id=str(task_id) if task_id is not None else None,
            agent_id=agent_id,
            success=success,
            error=error,
            lesson_text=lesson,
            created_at=datetime.now(UTC),
        )
        async with self._factory() as session:
            session.add(lesson_obj)
            await session.commit()
            await session.refresh(lesson_obj)

        logger.debug(
            "Recorded outcome: agent=%r task=%r success=%s",
            agent_id,
            task_id,
            success,
        )
        return lesson_obj

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_lessons(
        self,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[Lesson]:
        """Retrieve recent lessons, optionally filtered by agent.

        Args:
            agent_id: If provided, only return lessons for this agent.
            limit: Maximum number of lessons to return.

        Returns:
            List of :class:`Lesson` objects ordered by ``created_at`` descending.
        """
        async with self._factory() as session:
            stmt = select(Lesson).order_by(desc(Lesson.created_at)).limit(limit)
            if agent_id is not None:
                stmt = stmt.where(Lesson.agent_id == agent_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_similar_failures(
        self,
        description: str,
        limit: int = 5,
    ) -> list[Lesson]:
        """Find past failure lessons whose error or lesson text resembles *description*.

        Uses simple substring matching (LIKE) — no vector embeddings required.
        For production use, replace with a semantic search backend.

        Args:
            description: A phrase or error message to search for.
            limit: Maximum number of matching lessons to return.

        Returns:
            List of :class:`Lesson` objects (failures only) ordered by recency.
        """
        keywords = [kw.strip() for kw in description.split() if len(kw.strip()) > 3][:5]

        async with self._factory() as session:
            base = select(Lesson).where(Lesson.success == False)  # noqa: E712

            if keywords:
                from sqlalchemy import or_
                conditions = []
                for kw in keywords:
                    pattern = f"%{kw}%"
                    conditions.append(Lesson.error.ilike(pattern))
                    conditions.append(Lesson.lesson_text.ilike(pattern))
                base = base.where(or_(*conditions))

            stmt = base.order_by(desc(Lesson.created_at)).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    async def build_context(self, task: Task) -> str:
        """Build a context string from past lessons relevant to *task*.

        Retrieves the most recent failures for the assigned agent plus
        similar failure patterns based on the task description.

        Args:
            task: The :class:`~autodev.core.models.Task` about to be executed.

        Returns:
            A formatted string summarising past lessons that the agent
            should consider before starting work.  Empty string if no
            relevant lessons exist.
        """
        agent_id = task.assigned_to
        description = (task.description or task.title or "")[:300]

        # Fetch recent lessons for this specific agent
        agent_lessons: list[Lesson] = []
        if agent_id:
            agent_lessons = await self.get_lessons(agent_id=agent_id, limit=5)

        # Fetch similar past failures based on description keywords
        similar_failures = await self.get_similar_failures(description=description, limit=5)

        # Deduplicate by lesson id
        seen: set[int] = set()
        combined: list[Lesson] = []
        for lesson in agent_lessons + similar_failures:
            if lesson.id not in seen:
                seen.add(lesson.id)
                combined.append(lesson)

        if not combined:
            return ""

        lines: list[str] = [
            "## Past Lessons (from previous task runs)",
            "",
        ]
        for lesson in combined:
            status = "✅ success" if lesson.success else "❌ failure"
            lines.append(f"### Lesson #{lesson.id} — {status}")
            if lesson.task_id:
                lines.append(f"- Task: {lesson.task_id}")
            if lesson.agent_id:
                lines.append(f"- Agent: {lesson.agent_id}")
            if lesson.error:
                lines.append(f"- Error: {lesson.error}")
            if lesson.lesson_text:
                lines.append(f"- Lesson: {lesson.lesson_text}")
            if lesson.created_at:
                lines.append(f"- Recorded: {lesson.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Statistics helpers
    # ------------------------------------------------------------------

    async def success_rate(self, agent_id: str | None = None) -> float:
        """Return the overall success rate (0.0–1.0) for *agent_id* or all agents.

        Args:
            agent_id: Filter to a specific agent; ``None`` for all agents.

        Returns:
            Float in [0, 1].  Returns 0.0 if no records exist.
        """
        from sqlalchemy import func

        async with self._factory() as session:
            base_filter = []
            if agent_id is not None:
                base_filter.append(Lesson.agent_id == agent_id)

            total_stmt = select(func.count()).select_from(Lesson)
            success_stmt = select(func.count()).select_from(Lesson).where(
                Lesson.success == True  # noqa: E712
            )
            if base_filter:
                total_stmt = total_stmt.where(*base_filter)
                success_stmt = success_stmt.where(*base_filter)

            total = (await session.execute(total_stmt)).scalar_one()
            if total == 0:
                return 0.0
            successes = (await session.execute(success_stmt)).scalar_one()
            return successes / total
