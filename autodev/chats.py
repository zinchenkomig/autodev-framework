"""Chats with an agent about something — the reusable part.

A chat is about a *subject*: a task now, a project or the whole system later. The
subject decides two things:

- the **topic**: the agent's context (what the task is, its test plan, its follow-ups…)
  and the project whose code the agent reads;
- the **actions** the agent may propose (a follow-up, a new task…).

The agent never changes anything itself. It answers, and when something should
change it proposes an action; the proposal waits in its message until the owner
approves it in the dashboard, and only then the API applies it.

To chat about something new, subclass :class:`Subject` and add it to ``SUBJECTS``;
the API (``/api/chats``), the worker's chat slots and the dashboard's ``<Chat>``
work as they are.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev import pm, review
from autodev.core.models import Chat, ChatMessage, Project, Task, TaskStatus

#: Proposal states. Only "pending" ones can be approved or rejected.
PENDING, APPLIED, REJECTED = "pending", "applied", "rejected"


@dataclass
class Topic:
    """What the agent needs to know about a chat's subject."""

    title: str
    project: Project | None
    context: str  # Markdown for the agent

    @property
    def digest(self) -> str:
        """Changes when the context does, so the agent is told what's new."""
        return hashlib.sha256(self.context.encode()).hexdigest()[:16]


@dataclass
class Applied:
    """What an approved action did: an event message in the chat, plus a link for the UI."""

    text: str
    result: dict[str, Any] = field(default_factory=dict)  # {"task_id": ..., "ticket_number": ...}


Apply = Callable[[AsyncSession, Chat, dict], Awaitable[Applied]]


@dataclass
class Action:
    name: str
    label: str  # the approve button, in Russian
    hint: str  # for the agent: what it does and when to propose it
    apply: Apply


class Subject:
    kind: str = ""
    #: One chat per subject id, or many: a new chat per question, the older ones kept as history.
    single: bool = True
    actions: dict[str, Action] = {}

    async def topic(self, session: AsyncSession, subject_id: str | None) -> Topic | None:
        """The topic, or None if the subject doesn't exist (anymore)."""
        raise NotImplementedError

    def instructions(self) -> str:
        """The actions part of the agent's system prompt."""
        if not self.actions:
            return "There are no actions for this chat: just answer."
        lines = ["Actions you can propose (set `action` to the name):"]
        lines += [f"- {a.name}: {a.hint}" for a in self.actions.values()]
        return "\n".join(lines)

    def schema(self) -> dict[str, Any]:
        """The structured result of every agent turn."""
        return {
            "type": "object",
            "properties": {
                "reply": {
                    "type": "string",
                    "description": "Your message to the owner, in Russian; light Markdown readable on a phone",
                },
                "proposals": {
                    "type": "array",
                    "description": "Actions for the owner to approve; usually empty",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": sorted(self.actions)},
                            "title": {"type": "string", "description": "Short title in Russian"},
                            "description": {
                                "type": "string",
                                "description": "The full self-contained brief for the developer agent, in Russian",
                            },
                        },
                        "required": ["action", "title", "description"],
                    },
                },
            },
            "required": ["reply", "proposals"],
        }

    def proposals(self, raw: Any) -> list[dict]:
        """The agent's proposals that name a known action, ready to store."""
        out = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or item.get("action") not in self.actions:
                continue
            title, description = str(item.get("title") or "").strip(), str(item.get("description") or "").strip()
            if title and description:
                out.append(
                    {"action": item["action"], "title": title[:300], "description": description, "state": PENDING}
                )
        return out[:5]


# ---------------------------------------------------------------------------
# A task: questions while checking it on stage
# ---------------------------------------------------------------------------


async def _task(session: AsyncSession, chat: Chat) -> Task:
    from fastapi import HTTPException

    task = await session.get(Task, uuid.UUID(chat.subject_id), with_for_update=True) if chat.subject_id else None
    if task is None:
        raise HTTPException(409, "Задачи больше нет")
    return task


async def _follow_up(session: AsyncSession, chat: Chat, proposal: dict) -> Applied:
    from autodev.api.routes.tasks import request_changes

    task = await _task(session, chat)
    brief = f"{proposal['title']}\n\n{proposal['description']}"
    target = await request_changes(session, task, brief, by="chat")
    ref = {"task_id": str(target.id), "ticket_number": target.ticket_number}
    if target.id != task.id:
        return Applied(f"Создана доработка #{target.ticket_number}", ref)
    if target.status == TaskStatus.QUEUED and target.branch:
        return Applied(f"Правки отправлены агенту — он обновит PR #{target.pr_number}", ref)
    return Applied("Добавлено в описание задачи — агент учтёт, когда возьмёт её", ref)


async def _new_task(session: AsyncSession, chat: Chat, proposal: dict) -> Applied:
    task = await _task(session, chat)
    new = Task(
        title=proposal["title"],
        description=f"{proposal['description']}\n\n---\nFrom the chat about #{task.ticket_number}.",
        project_id=task.project_id,
        repo=task.repo,
        priority=task.priority,
        created_by="chat",
        status=TaskStatus.QUEUED,
        metadata_={},
    )
    session.add(new)
    await session.flush()
    await session.refresh(new)
    return Applied(f"Создана задача #{new.ticket_number}", {"task_id": str(new.id), "ticket_number": new.ticket_number})


async def _principle(session: AsyncSession, chat: Chat, proposal: dict) -> Applied:
    task = await _task(session, chat)
    project = await session.get(Project, task.project_id, with_for_update=True) if task.project_id else None
    if project is None:
        from fastapi import HTTPException

        raise HTTPException(409, "У задачи нет проекта")
    line = f"- {' '.join(proposal['description'].split())}"
    project.principles = f"{(project.principles or '').rstrip()}\n{line}".strip()
    return Applied(f"Принцип добавлен в проект {project.name}: PM учтёт его в следующих задачах")


STATUS_TEXT = {
    "queued": "в очереди",
    "in_progress": "агент работает",
    "ci": "PR открыт, идут проверки",
    "deploying": "смержено, выкатывается на stage",
    "on_stage": "на stage, ждёт проверки владельцем",
    "released": "в проде",
    "failed": "не получилось",
    "cancelled": "отменена",
}


class TaskSubject(Subject):
    """A task's chat: the owner asks about it while checking it on stage by its test plan."""

    kind = "task"
    # A chat per question: a finished one (say, it ended in a follow-up) doesn't weigh on the next.
    # What they decided reaches the next chat through the task's context.
    single = False
    actions = {
        "follow_up": Action(
            "follow_up",
            "Доработать",
            "changes to THIS task, when something in it works wrong, is missing, or the owner wants it "
            "different. Becomes a follow-up task if the change is already merged, or another round on its "
            "open PR. The description says what is wrong now, what should happen instead, and how to check.",
            _follow_up,
        ),
        "new_task": Action(
            "new_task",
            "Создать задачу",
            "a separate new task in the same project, for something unrelated to this task's change.",
            _new_task,
        ),
        "principle": Action(
            "principle",
            "Запомнить",
            "remember a product principle of the owner for the whole project, when the owner's correction "
            "shows a general preference the PM should apply to future tasks without being told (e.g. «a "
            "label or icon must match the real behaviour», «fewer taps over more settings»). Usually next "
            "to a follow_up. The description is the principle itself: one general sentence, not about this "
            "task.",
            _principle,
        ),
    }

    async def topic(self, session: AsyncSession, subject_id: str | None) -> Topic | None:
        try:
            task = await session.get(Task, uuid.UUID(subject_id or ""))
        except ValueError:
            return None
        if task is None:
            return None
        main = await session.get(Task, task.parent_id) if task.parent_id else None
        children = []
        if main is None:
            rows = await session.execute(select(Task).where(Task.parent_id == task.id).order_by(Task.ticket_number))
            children = list(rows.scalars())
        project = await session.get(Project, task.project_id) if task.project_id else None
        context = task_context(task, main, children, project)
        decided = await decisions(session, self.kind, subject_id)
        if decided:
            context += "\n\n" + decided
        return Topic(title=f"#{task.ticket_number} {task.title}", project=project, context=context)


async def decisions(session: AsyncSession, kind: str, subject_id: str | None) -> str:
    """What the owner decided on proposals in all chats about this subject: the next chat shouldn't repeat them."""
    rows = await session.execute(
        select(ChatMessage.proposals)
        .join(Chat, Chat.id == ChatMessage.chat_id)
        .where(Chat.subject == kind, Chat.subject_id == subject_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at)
    )
    lines = []
    for proposals in rows.scalars():
        for p in proposals or []:
            if p.get("state") == APPLIED:
                ref = (p.get("result") or {}).get("ticket_number")
                lines.append(f"- approved {p['action']} «{p['title']}»" + (f" → task #{ref}" if ref else ""))
            elif p.get("state") == REJECTED:
                lines.append(f"- rejected {p['action']} «{p['title']}»")
    if not lines:
        return ""
    return "\n".join(["### Proposals the owner already decided on (in this and earlier chats)", *lines[-30:]])


def task_context(task: Task, main: Task | None, children: list[Task], project: Project | None) -> str:
    parts = [
        f"## Task #{task.ticket_number}: {task.title}",
        f"Status: {task.status} ({STATUS_TEXT.get(task.status, '')})",
    ]
    if task.pr_url:
        parts.append(f"PR: {task.pr_url} (see it with `gh pr view {task.pr_url}` / `gh pr diff {task.pr_url}`)")
    if main is not None:
        parts.append(
            f"This is a follow-up to main task #{main.ticket_number} «{main.title}»; "
            "the owner checks the main task as a whole, by its one test plan."
        )
    parts += ["", "### What the owner asked", (task.description or "").strip()[:6000] or "(only the title)"]
    if pm.brief(task):
        parts += ["", "### The PM's brief the developer followed", pm.brief(task).strip()[:4000]]
    if task.summary:
        parts += ["", "### What the developer agent did", task.summary.strip()[:4000]]
    if task.error and task.status == TaskStatus.FAILED:
        parts += ["", "### Why it failed", task.error.strip()[-3000:]]

    checked_on = main or task
    plan = (checked_on.metadata_ or {}).get("test_plan") or []
    if plan:
        ticked, earlier = set(review.plan_checked(checked_on)), set(review.plan_earlier(checked_on))
        owner = f" of main task #{main.ticket_number}" if main else ""
        parts += [
            "",
            f"### Test plan{owner}: the owner's manual check on stage",
            "([x] = ticked; [~] = ticked on the previous version, not yet checked again on this one)",
        ]
        parts += [
            f"{i}. [{'x' if i - 1 in ticked else '~' if i - 1 in earlier else ' '}] {step}"
            for i, step in enumerate(plan, 1)
        ]
        if review.verified_at(checked_on):
            parts.append("The owner has marked it verified.")

    qa = (task.metadata_ or {}).get("qa")
    if isinstance(qa, dict) and not qa.get("skipped"):
        parts += ["", "### Automatic stage QA", "No problems found." if qa.get("ok") else "Problems:"]
        parts += [f"- {p}" for p in (qa.get("problems") or [])[:10]]

    if children:
        parts += ["", "### Follow-ups of this task (oldest first)"]
        for c in children:
            asked = (c.description or "").split("\n\n---\n")[0].strip().replace("\n", " ")[:500]
            line = f"- #{c.ticket_number} [{c.status}] {asked or c.title}"
            if c.summary:
                line += f"\n  Done: {c.summary.strip().replace(chr(10), ' ')[:500]}"
            if c.pr_url:
                line += f"\n  PR: {c.pr_url}"
            parts.append(line)

    if project is not None:
        repo = project.repo()
        parts += ["", f"## Project: {project.name}"]
        if repo:
            parts.append(f"Repository: {repo['name']}; the current directory is its `{project.base_branch}` branch.")
        if project.stage_url:
            parts.append(f"Stage: {project.stage_url}")
        if project.principles:
            parts += ["", "The owner's product principles (already remembered):", project.principles.strip()[:3000]]
        if project.instructions:
            parts += ["", "Project instructions:", project.instructions.strip()[:3000]]
    return "\n".join(parts)


SUBJECTS: dict[str, Subject] = {s.kind: s for s in (TaskSubject(),)}
