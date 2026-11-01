"""The PM: thinks a task through as the owner would, before the developer starts.

The owner sends raw thoughts from a phone. Without a PM the developer turns them
straight into code, and the product questions (what exactly it means, edge cases,
where it lives in the UI, does the label match the behaviour) reach the owner only
on stage. The PM answers them first and writes a brief the developer follows
(``metadata["brief"]``), shown on the task page.

When the main task (with all its follow-ups) lands on stage, the PM also accepts
it before the owner is called (``metadata["acceptance"]``, :mod:`autodev.worker.acceptor`):
it walks the test plan in a phone-sized browser and sends back a follow-up with what
it found, at most ``MAX_FIXES`` times; then the owner gets the task with its verdict.

Each costs a Claude session and some minutes, so the PM can be switched off: per project
(``Project.pm``, the default for new tasks) and per task (``metadata["pm"]``) —
for obvious tasks, or when the owner wants to decide everything themselves.
Follow-ups inherit their main task's choice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.models import Chat, ChatMessage, Task

#: Task metadata: whether the PM works on the task (absent: the project's default).
KEY = "pm"
#: Task metadata: the PM's brief for the developer (Markdown).
BRIEF = "brief"


def enabled(task: Task) -> bool:
    value = (task.metadata_ or {}).get(KEY)
    if isinstance(value, bool):
        return value
    return task.project.pm if task.project is not None else True


def brief(task: Task) -> str | None:
    value = (task.metadata_ or {}).get(BRIEF)
    return value if isinstance(value, str) and value.strip() else None


async def history(session: AsyncSession, project_id: str, limit: int = 25) -> list[str]:
    """What the owner corrected and asked about lately in the project, oldest first.

    The PM reads it to ask the questions the owner would: it's the owner's taste in practice.
    """
    items: list[tuple[datetime, str]] = []
    follow_ups = await session.execute(
        select(Task.created_at, Task.title, Task.description)
        .where(Task.project_id == project_id, Task.created_by.in_(("feedback", "chat")))
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    for created_at, title, description in follow_ups.all():
        asked = (description or "").split("\n\n---\n")[0].strip()
        items.append((created_at, f"Asked for a change to «{title.removesuffix(' — доработка')}»: {_flat(asked)}"))
    questions = await session.execute(
        select(ChatMessage.created_at, ChatMessage.text, Chat.title)
        .join(Chat, Chat.id == ChatMessage.chat_id)
        .where(Chat.project_id == project_id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    for created_at, text, title in questions.all():
        items.append((created_at, f"Asked in the chat about «{title}»: {_flat(text)}"))
    items.sort(key=lambda item: item[0])
    return [text for _, text in items[-limit:]]


def _flat(text: str, limit: int = 500) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Acceptance: the PM checks the main task on stage before the owner is called
# ---------------------------------------------------------------------------

#: Main task metadata: {"state", "fixes", "summary", "issues", "fix_task", "at"}.
ACCEPTANCE = "acceptance"
#: The PM is checking stage now / waits for its own follow-up to land.
CHECKING, FIXING = "checking", "fixing"
#: Done: the PM accepted it / issues remain after its fix rounds / it couldn't check.
ACCEPTED, CONCERNS, FAILED = "accepted", "concerns", "failed"
#: The owner isn't called while the PM still works on it.
IN_PROGRESS = frozenset({CHECKING, FIXING})
#: Follow-ups the PM may send before it hands the task to the owner as it is.
MAX_FIXES = 2
#: ``created_by`` of the PM's follow-ups.
PM_AUTHOR = "pm"


def acceptance(task: Task) -> dict | None:
    value = (task.metadata_ or {}).get(ACCEPTANCE)
    return value if isinstance(value, dict) else None


def start_acceptance(metadata: dict, landed: Task) -> None:
    """*landed* (the main task or one of its follow-ups) reached stage: the PM checks the whole again.

    Its own follow-ups count toward MAX_FIXES; anything else (the owner's follow-up, a QA fix after
    the owner's change…) starts the count over.
    """
    previous = metadata.get(ACCEPTANCE) if isinstance(metadata.get(ACCEPTANCE), dict) else {}
    own = landed.created_by == PM_AUTHOR and previous.get("state") == FIXING
    metadata[ACCEPTANCE] = {"state": CHECKING, "fixes": previous.get("fixes", 0) if own else 0, "at": _now()}


def finish_acceptance(metadata: dict, state: str, **fields) -> None:
    current = metadata.get(ACCEPTANCE) if isinstance(metadata.get(ACCEPTANCE), dict) else {}
    metadata[ACCEPTANCE] = {**current, **fields, "state": state, "at": _now()}


def _now() -> str:
    return datetime.now(UTC).isoformat()
