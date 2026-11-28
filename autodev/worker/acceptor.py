"""The PM tests a main task on stage before the owner is called (see :mod:`autodev.pm`).

Delivery marks the main task ``acceptance.state = checking`` when it (or its last open
follow-up) lands on stage and the PM is on for it, and holds back the owner's
"on stage" notification. This loop runs one Claude session per such task, in a headless
phone-sized browser, in two steps:

1. a newcomer: the session knows only what the owner asked and looks for the way itself.
   The test plan names every tap, so an agent that has read it can't tell whether a user
   without it would get there;
2. a tester: the same session gets the brief and the plan, walks the plan and then tries
   what the plan doesn't.

It either accepts — the owner is notified — or sends a follow-up with what it found
(at most ``pm.MAX_FIXES`` per cycle; then the owner gets it with the issues).
"""

from __future__ import annotations

import logging
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, select

from autodev import notify, pm, review
from autodev.core.claude import READ_ONLY_WITH_SCRIPTS, ClaudeRunner
from autodev.core.models import MERGED_STATUSES, Project, Task, TaskStatus
from autodev.worker import prompts
from autodev.worker.context import WorkerContext
from autodev.worker.workspace import clone_stage

logger = logging.getLogger(__name__)

AGENT = "pm"

#: Step 1: what a user comes to do with the change, and how each went without instructions.
WALK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "description": "One to three things a user would come to do with this change",
            "items": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "In Russian, in the user's words"},
                    "reached": {"type": "boolean", "description": "Done from the home page, through the UI only"},
                    "path": {"type": "string", "description": "In Russian: what you tapped, screen by screen"},
                    "friction": {
                        "type": "string",
                        "description": "In Russian: where you hesitated, guessed, went wrong or got stuck, and why; "
                        "empty if nowhere",
                    },
                },
                "required": ["goal", "reached", "path", "friction"],
            },
        },
    },
    "required": ["goals"],
}

#: Step 2: the verdict.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["accepted", "changes", "unchecked"]},
        "summary": {
            "type": "string",
            "description": "In Russian, 2-4 sentences for the owner: how it went without instructions, what you "
            "tried beyond the plan, what you found. For unchecked: why it couldn't be tested",
        },
        "issues": {
            "type": "array",
            "description": "For verdict=changes: one item per problem the owner would send back",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short, in Russian"},
                    "description": {
                        "type": "string",
                        "description": "The whole brief for a developer, in Russian: what is wrong now and where, "
                        "what it should be, how to check",
                    },
                },
                "required": ["title", "description"],
            },
        },
    },
    "required": ["verdict", "summary"],
}


async def next_request(ctx: WorkerContext) -> uuid.UUID | None:
    """The main task waiting longest for the PM's acceptance."""
    async with ctx.session_factory() as session:
        rows = await session.execute(
            select(Task).where(
                Task.parent_id.is_(None),
                Task.status.in_(MERGED_STATUSES),
                cast(Task.metadata_, String).like(f'%"{pm.CHECKING}"%'),
            )
        )
        pending = [t for t in rows.scalars() if (pm.acceptance(t) or {}).get("state") == pm.CHECKING]
    pending.sort(key=lambda t: str(pm.acceptance(t).get("at", "")))
    return pending[0].id if pending else None


async def accept(ctx: WorkerContext, task_id: uuid.UUID) -> None:
    """One test of a main task on stage. Leaves the task ``checking`` only when Claude is rate-limited."""
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
    root = Path(ctx.settings.workdir) / "acceptance" / str(task_id)
    shots = root / "shots"
    try:
        if project is None or not project.stage_url or project.repo() is None:
            raise RuntimeError("у проекта нет stage или репозитория")
        await log("info", "🕵️ PM проверяет на stage, прежде чем звать вас")
        shutil.rmtree(root, ignore_errors=True)
        shots.mkdir(parents=True)
        checkout = root / "code"
        await clone_stage(project, checkout, ctx.env())
        walk = prompts.newcomer_walk(main, children, project, sys.executable, str(shots))
        result = await _runner(ctx, main, project, checkout, WALK_SCHEMA).run(walk, on_log=log)
        if result.ok:
            goals = _goals(result.data.get("goals"))
            reached = f"дошёл до цели в {sum(g['reached'] for g in goals)} из {len(goals)}" if goals else "целей нет"
            await log(
                "info",
                f"🕵️ Без инструкции: {reached}, ${result.cost_usd:.2f} — теперь по плану проверки",
                details="\n\n".join(_goal_text(g) for g in goals) or None,
            )
            result = await _runner(ctx, main, project, checkout, SCHEMA).run(
                prompts.acceptance(main, children), resume=result.session_id, on_log=log
            )
        if result.rate_limited:
            await ctx.pause(result.rate_limited_until)
            await log("warning", f"⏸ Лимит Claude, продолжу в {result.rate_limited_until:%H:%M} UTC")
            return
        if not result.ok:
            raise RuntimeError(result.summary or "сессия PM не завершилась")
        screenshot = await store.attach_screenshots(task_id, sorted(shots.glob("*.png")), "PM")
        await _decide(ctx, main, project, result.data, screenshot, result.cost_usd, log)
    except Exception as exc:
        logger.exception("acceptance of %s failed", task_id)
        reason = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
        await log("error", f"❌ PM не смог проверить: {reason}", details=str(exc)[-4000:])
        await _finish(ctx, task_id, pm.FAILED, summary=f"PM не смог проверить: {reason}")
        await _notify(ctx, task_id, project)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _runner(ctx: WorkerContext, main: Task, project: Project, checkout: Path, schema: dict) -> ClaudeRunner:
    """A step of the test: both run in *checkout*, so the second resumes the first one's session."""
    return ClaudeRunner(
        str(checkout),
        model=main.model or project.model or ctx.settings.model,
        effort=main.effort or project.effort or ctx.settings.effort,
        timeout=ctx.settings.claude_timeout,
        env=ctx.env(),
        system_prompt_append=prompts.ACCEPT_SYSTEM,
        schema=schema,
        disallowed_tools=READ_ONLY_WITH_SCRIPTS,
    )


async def _decide(ctx: WorkerContext, main: Task, project: Project, data: dict, screenshot, cost: float, log) -> None:
    summary = str(data.get("summary") or "").strip()
    if data.get("verdict") == "unchecked":  # nobody looked: that isn't an acceptance, and the owner hears so
        await log("warning", "🕵️ PM не смог проверить на stage", details=summary or None)
        why = "PM не смог проверить" + (f": {summary}" if summary else "")
        await _finish(ctx, main.id, pm.FAILED, summary=why, issues=[])
        await _notify(ctx, main.id, project, screenshot)
        return
    issues = _issues(data.get("issues")) if data.get("verdict") == "changes" else []
    if not issues:
        await log("info", f"🕵️ PM принял, ${cost:.2f}", details=summary or None)
        await _finish(ctx, main.id, pm.ACCEPTED, summary=summary, issues=[])
        await _notify(ctx, main.id, project, screenshot)
        return

    titles = [i["title"] for i in issues]
    fixes = (pm.acceptance(main) or {}).get("fixes", 0)
    details = "\n".join(f"- {i['title']}: {i['description']}" for i in issues)
    if fixes >= pm.MAX_FIXES:
        await log("warning", f"🕵️ PM: замечания остались после {fixes} доработок — зову вас", details=details)
        await _finish(ctx, main.id, pm.CONCERNS, summary=summary, issues=titles)
        await _notify(ctx, main.id, project, screenshot)
        return

    fix = await _follow_up(ctx, main, issues)
    await log(
        "info", f"🕵️ PM нашёл замечания ({len(issues)}) — доработка #{fix.ticket_number}, ${cost:.2f}", details=details
    )
    await _finish(
        ctx,
        main.id,
        pm.FIXING,
        summary=summary,
        issues=titles,
        fixes=fixes + 1,
        fix_task={"id": str(fix.id), "ticket_number": fix.ticket_number},
    )


def _goals(raw) -> list[dict]:
    """The newcomer's goals from step 1, tidied for the task log."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and str(item.get("goal") or "").strip():
            out.append(
                {
                    "goal": str(item["goal"]).strip(),
                    "reached": item.get("reached") is True,
                    "path": str(item.get("path") or "").strip(),
                    "friction": str(item.get("friction") or "").strip(),
                }
            )
    return out


def _goal_text(goal: dict) -> str:
    lines = [f"{'✅' if goal['reached'] else '❌'} {goal['goal']}"]
    if goal["path"]:
        lines.append(f"Путь: {goal['path']}")
    if goal["friction"]:
        lines.append(f"Где споткнулся: {goal['friction']}")
    return "\n".join(lines)


def _issues(raw) -> list[dict]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title, description = str(item.get("title") or "").strip(), str(item.get("description") or "").strip()
        if title and description:
            out.append({"title": title[:200], "description": description})
    return out[:8]


async def _follow_up(ctx: WorkerContext, main: Task, issues: list[dict]) -> Task:
    """One follow-up with everything the PM found: one round, one PR."""
    brief = "\n\n".join(f"### {i['title']}\n{i['description']}" for i in issues)
    async with ctx.session_factory() as session:
        fix = Task(
            title=f"{main.title.removesuffix(' — доработка')} — доработка",
            description=f"PM проверил задачу на stage и нашёл:\n\n{brief}\n\n---\nFollow-up to #{main.ticket_number} "
            f"({main.pr_url or 'no PR'}), from the PM's acceptance.",
            project_id=main.project_id,
            repo=main.repo,
            priority=main.priority,
            depends_on=[main.id],
            parent_id=main.id,
            created_by=pm.PM_AUTHOR,
            status=TaskStatus.QUEUED,
            metadata_={pm.KEY: True, **main.carried()},
        )
        session.add(fix)
        root = await session.get(Task, main.id, with_for_update=True)
        if root is not None:
            root.metadata_ = review.unverify(root.metadata_ or {})
        await session.commit()
        await session.refresh(fix)
        return fix


async def _finish(ctx: WorkerContext, task_id: uuid.UUID, state: str, **fields) -> None:
    await ctx.store.patch_metadata(task_id, lambda m: pm.finish_acceptance(m, state, **fields))


async def _notify(ctx: WorkerContext, task_id: uuid.UUID, project: Project | None, screenshot: bytes | None = None):
    main = await ctx.store.get(task_id)
    if main is not None:
        await notify.accepted(main, project, screenshot=screenshot)
