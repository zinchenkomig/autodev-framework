"""PM agent chat endpoints.

Provides a rule-based PM chat interface that can:
- Report project status (tasks/agents summary)
- Suggest next tasks to work on
- Accept natural language task descriptions and decompose them into subtasks
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import (
    Agent,
    ChatMessage,
    Priority,
    Release,
    ReleaseStatus,
    Task,
    TaskSource,
    TaskStatus,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str


class TaskCreated(BaseModel):
    id: str
    title: str
    priority: str


class ChatResponse(BaseModel):
    response: str
    tasks_created: list[TaskCreated] = []


class ProjectStatus(BaseModel):
    in_progress: int
    queued: int
    done_this_week: int
    open_bugs: int
    last_release: str | None
    busy_agents: list[str]


# ---------------------------------------------------------------------------
# Rule-based PM logic helpers
# ---------------------------------------------------------------------------

# Keywords for status intent
_STATUS_RE = re.compile(r"\b(стату[с|т]|status|статистик|статус)\b", re.IGNORECASE)
# Keywords for suggestion intent
_SUGGEST_RE = re.compile(
    r"(что делать|что можно сделать|suggest|предложи|next tasks?|следующ)", re.IGNORECASE
)

# Subtask templates for common high-level requests
_SUBTASK_TEMPLATES: list[tuple[re.Pattern, list[tuple[str, str]]]] = [
    (
        re.compile(r"(авторизаци|аутентификаци|регистраци|\bauth\b|\blogin\b)", re.IGNORECASE),
        [
            ("Backend: JWT аутентификация middleware", "high"),
            ("Backend: User model + registration endpoint", "high"),
            ("Frontend: Login/Register страницы", "high"),
            ("Frontend: Protected routes", "normal"),
        ],
    ),
    (
        re.compile(r"\b(уведомлени|notification|notify)\b", re.IGNORECASE),
        [
            ("Backend: Notification model + queue", "high"),
            ("Backend: Email/Telegram delivery service", "normal"),
            ("Frontend: Notification bell component", "normal"),
        ],
    ),
    (
        re.compile(r"\b(поиск|search)\b", re.IGNORECASE),
        [
            ("Backend: Full-text search index", "high"),
            ("Backend: Search API endpoint", "high"),
            ("Frontend: Search bar + results page", "normal"),
        ],
    ),
    (
        re.compile(r"\b(тест|test|покрытие|coverage)\b", re.IGNORECASE),
        [
            ("Add unit tests for core modules", "normal"),
            ("Add integration tests for API endpoints", "normal"),
            ("Configure coverage reporting in CI", "low"),
        ],
    ),
    (
        re.compile(r"\b(дашборд|dashboard|метрики|metrics)\b", re.IGNORECASE),
        [
            ("Backend: Metrics aggregation endpoint", "high"),
            ("Frontend: Dashboard charts component", "normal"),
            ("Frontend: Real-time updates via WebSocket", "low"),
        ],
    ),
]


async def _collect_status(session: AsyncSession) -> ProjectStatus:
    """Gather current project statistics from the database."""
    in_progress = await session.scalar(
        select(func.count(Task.id)).where(
            Task.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.ASSIGNED])
        )
    ) or 0

    queued = await session.scalar(
        select(func.count(Task.id)).where(Task.status == TaskStatus.QUEUED)
    ) or 0

    week_start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # approximate: last 7 days
    from datetime import timedelta
    week_ago = week_start - timedelta(days=7)
    done_this_week = await session.scalar(
        select(func.count(Task.id)).where(
            Task.status == TaskStatus.DONE,
            Task.updated_at >= week_ago,
        )
    ) or 0

    open_bugs = await session.scalar(
        select(func.count(Task.id)).where(
            Task.status != TaskStatus.DONE,
            Task.title.ilike("%bug%"),
        )
    ) or 0

    # Last release in staging or deployed
    last_release_row = await session.scalar(
        select(Release.version)
        .where(Release.status.in_([ReleaseStatus.STAGING, ReleaseStatus.DEPLOYED]))
        .order_by(Release.created_at.desc())
        .limit(1)
    )

    busy_agents: list[str] = []
    agents_result = await session.execute(
        select(Agent.id, Agent.current_task_id).where(
            Agent.status.in_(["working", "busy", "assigned"])
        )
    )
    for row in agents_result.fetchall():
        task_info = f"#{str(row.current_task_id)[:8]}" if row.current_task_id else ""
        busy_agents.append(f"{row.id} {task_info}".strip())

    return ProjectStatus(
        in_progress=in_progress,
        queued=queued,
        done_this_week=done_this_week,
        open_bugs=open_bugs,
        last_release=last_release_row,
        busy_agents=busy_agents,
    )


def _format_status(ps: ProjectStatus) -> str:
    agents_str = ", ".join(ps.busy_agents) if ps.busy_agents else "нет"
    release_str = ps.last_release if ps.last_release else "нет релизов"
    return (
        f"📊 Статус проекта:\n"
        f"  - В работе: {ps.in_progress} задач(и) (занятые агенты: {agents_str})\n"
        f"  - В очереди: {ps.queued} задач(и)\n"
        f"  - Завершено за неделю: {ps.done_this_week} задач(и)\n"
        f"  - Открытых багов: {ps.open_bugs}\n"
        f"  - Последний релиз: {release_str}"
    )


async def _suggest_tasks(session: AsyncSession) -> str:
    """Suggest the highest-priority queued tasks."""
    result = await session.execute(
        select(Task)
        .where(Task.status == TaskStatus.QUEUED)
        .order_by(Task.created_at.asc())
        .limit(5)
    )
    tasks = result.scalars().all()
    if not tasks:
        return "🎉 Очередь задач пуста! Все задачи выполнены или в работе."
    lines = ["💡 Предлагаю следующие задачи из очереди:"]
    for i, t in enumerate(tasks, 1):
        lines.append(f"  {i}. [{t.priority.upper()}] {t.title}")
    return "\n".join(lines)


async def _create_subtasks(
    message: str,
    session: AsyncSession,
) -> tuple[str, list[TaskCreated]]:
    """Match message against templates; create subtasks or a single task."""
    created: list[TaskCreated] = []

    # Try template matching
    for pattern, subtasks in _SUBTASK_TEMPLATES:
        if pattern.search(message):
            for title, priority in subtasks:
                task = Task(
                    id=uuid.uuid4(),
                    title=title,
                    description=f"Создано PM агентом из запроса: {message[:200]}",
                    source=TaskSource.AGENT_CREATED,
                    priority=priority,
                    status=TaskStatus.QUEUED,
                    created_by="pm",
                )
                session.add(task)
                created.append(TaskCreated(id=str(task.id), title=title, priority=priority))
            await session.commit()

            lines = [f"Разбил на {len(created)} подзадач(и):"]
            for i, t in enumerate(created, 1):
                lines.append(f"  {i}. {t.title} ({t.priority})")
            lines.append(f"Создал {len(created)} задач(и) в очереди. Начинаю с #1.")
            return "\n".join(lines), created

    # No template match — create a single task from the message text
    title = message[:200].strip()
    task = Task(
        id=uuid.uuid4(),
        title=title,
        description="Создано PM агентом",
        source=TaskSource.AGENT_CREATED,
        priority=Priority.NORMAL,
        status=TaskStatus.QUEUED,
        created_by="pm",
    )
    session.add(task)
    await session.commit()
    created.append(TaskCreated(id=str(task.id), title=title, priority=Priority.NORMAL))
    return f"✅ Создал задачу #{str(task.id)[:8]}: «{title}»", created


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def pm_chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """Handle a PM chat message and return a response with optional created tasks."""
    message = body.message.strip()
    tasks_created: list[TaskCreated] = []

    # Persist user message
    user_msg = ChatMessage(
        id=uuid.uuid4(),
        role="user",
        content=message,
        created_at=datetime.now(UTC),
    )
    session.add(user_msg)
    await session.flush()

    # Determine intent
    if _STATUS_RE.search(message):
        ps = await _collect_status(session)
        response_text = _format_status(ps)
    elif _SUGGEST_RE.search(message):
        response_text = await _suggest_tasks(session)
    else:
        response_text, tasks_created = await _create_subtasks(message, session)

    # Persist PM response
    pm_msg = ChatMessage(
        id=uuid.uuid4(),
        role="pm",
        content=response_text,
        created_at=datetime.now(UTC),
    )
    session.add(pm_msg)
    await session.commit()

    return ChatResponse(response=response_text, tasks_created=tasks_created)


@router.get("/status", response_model=ProjectStatus)
async def pm_status(
    session: AsyncSession = Depends(get_session),
) -> ProjectStatus:
    """Return a structured project status summary."""
    return await _collect_status(session)


@router.get("/history")
async def pm_history(
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
) -> list[dict]:
    """Return recent chat history."""
    result = await session.execute(
        select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit)
    )
    messages = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in reversed(messages)
    ]
