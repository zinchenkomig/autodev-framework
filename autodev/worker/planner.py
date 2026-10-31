"""Rebuild a main task's one test plan on request.

The plan normally grows incrementally: each follow-up's agent proposes the main
task's updated plan and it is folded in when the follow-up lands (see
:mod:`autodev.review`). That breaks for tasks from before one-plan-per-task, and
after bugs or changes in that mechanism. A refresh (``plan_refresh`` in the main
task's metadata, set by the API) has an agent write the whole plan again from
the main task, its landed follow-ups and the code on stage.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, select

from autodev import review
from autodev.core import shell
from autodev.core.claude import ClaudeRunner
from autodev.core.models import MERGED_STATUSES, Project, Task
from autodev.worker import prompts
from autodev.worker.context import WorkerContext

logger = logging.getLogger(__name__)

FLAG = review.REFRESH
AGENT = "planner"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked"]},
        "summary": {
            "type": "string",
            "description": "1-3 sentences in Russian: what the plan covers, or why it can't be written",
        },
        "test_plan": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The main task's whole manual test plan in Russian, one step per item. Step 1 opens "
            "the stage home page; after that navigate only through the UI (labels in «quotes»).",
        },
    },
    "required": ["status", "summary", "test_plan"],
}


async def next_request(ctx: WorkerContext) -> uuid.UUID | None:
    """The oldest main task waiting for a plan refresh."""
    async with ctx.session_factory() as session:
        rows = await session.execute(
            select(Task).where(Task.parent_id.is_(None), cast(Task.metadata_, String).like(f'%"{FLAG}"%'))
        )
        pending = [t for t in rows.scalars() if FLAG in (t.metadata_ or {})]
    pending.sort(key=lambda t: str((t.metadata_ or {})[FLAG].get("requested_at", "")))
    return pending[0].id if pending else None


async def refresh_plan(ctx: WorkerContext, task_id: uuid.UUID) -> None:
    """Write the main task's plan again. Leaves the request in place only when Claude is rate-limited."""
    store = ctx.store

    async def log(level: str, message: str, details: str | None = None) -> None:
        await store.log(task_id, message, level=level, details=details, agent=AGENT)

    async with ctx.session_factory() as session:
        main = await session.get(Task, task_id)
        if main is None:
            return
        project = await session.get(Project, main.project_id) if main.project_id else None
        children = list(
            (
                await session.execute(
                    select(Task)
                    .where(Task.parent_id == main.id, Task.status.in_(MERGED_STATUSES))
                    .order_by(Task.ticket_number)
                )
            ).scalars()
        )
    base_plan = list((main.metadata_ or {}).get("test_plan") or [])
    root = Path(ctx.settings.workdir) / "plans" / str(task_id)
    try:
        if project is None:
            raise RuntimeError("У задачи нет проекта")
        repos = _repos(project, [main, *children])
        if not repos:
            raise RuntimeError(f"У проекта {project.id} нет репозитория")
        await log("info", f"🧭 Пересобираю план: задача и доработки {_tickets(children) or '— нет'}")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        for repo in repos:
            await shell.run(
                "git", "clone", "--filter=blob:none", "-b", project.base_branch,
                f"https://github.com/{repo}.git", str(root / repo.split("/")[-1]),
                env=ctx.env(), timeout=600,
            )  # fmt: skip
        runner = ClaudeRunner(
            str(root),
            model=project.model or ctx.settings.model,
            timeout=ctx.settings.claude_timeout,
            env=ctx.env(),
            system_prompt_append=prompts.PLANNER_SYSTEM,
            schema=SCHEMA,
        )
        result = await runner.run(prompts.plan_refresh(main, children, project, repos), on_log=log)
        if result.rate_limited:
            ctx.paused_until = result.rate_limited_until
            await log("warning", f"⏸ Лимит Claude, продолжу в {result.rate_limited_until:%H:%M} UTC")
            return
        plan = [s.strip() for s in result.data.get("test_plan") or [] if isinstance(s, str) and s.strip()]
        if not result.ok or not plan:
            raise RuntimeError(result.summary or "Агент не вернул план")
        changed = await _save(ctx, task_id, base_plan, plan[: review.MAX_PLAN])
        await log(
            "info",
            f"🧭 План пересобран: {len(plan[: review.MAX_PLAN])} шагов"
            + ("" if changed else " (не изменился)")
            + f", ${result.cost_usd:.2f}",
            details=result.summary or None,
        )
    except Exception as exc:
        logger.exception("plan refresh for %s failed", task_id)
        await log("error", f"❌ План не пересобран: {str(exc).splitlines()[0][:200]}", details=str(exc)[-4000:])
        await _clear(ctx, task_id)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _repos(project: Project, tasks: list[Task]) -> list[str]:
    """Every repo the task and its follow-ups changed; the project's repo if they don't say."""
    names: list[str] = []
    for task in tasks:
        if task.repo and task.repo not in names:
            names.append(task.repo)
    entry = project.repo()
    if not names and entry:
        names.append(entry["name"])
    return names


def _tickets(tasks: list[Task]) -> str:
    return ", ".join(f"#{t.ticket_number}" for t in tasks)


async def _save(ctx: WorkerContext, task_id: uuid.UUID, base: list[str], plan: list[str]) -> bool:
    """Store *plan* and drop the request. A follow-up that landed meanwhile keeps its new steps."""
    async with ctx.session_factory() as session:
        task = await session.get(Task, task_id, with_for_update=True)
        if task is None:
            return False
        metadata = {k: v for k, v in (task.metadata_ or {}).items() if k != FLAG}
        current = metadata.get("test_plan") or []
        new = (
            plan
            if current == base
            else (plan + [s for s in current if s not in base and s not in plan])[: review.MAX_PLAN]
        )
        changed = new != current
        if changed:
            metadata = review.new_version(metadata, new)
        task.metadata_ = metadata
        await session.commit()
        return changed


async def _clear(ctx: WorkerContext, task_id: uuid.UUID) -> None:
    async with ctx.session_factory() as session:
        task = await session.get(Task, task_id, with_for_update=True)
        if task is not None and FLAG in (task.metadata_ or {}):
            task.metadata_ = {k: v for k, v in task.metadata_.items() if k != FLAG}
            await session.commit()
