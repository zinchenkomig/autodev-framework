"""The PM accepts a main task on stage before the owner is called (see :mod:`autodev.pm`).

Delivery marks the main task ``acceptance.state = checking`` when it (or its last open
follow-up) lands on stage and the PM is on for it, and holds back the owner's
"on stage" notification. This loop runs one Claude session per such task: it walks
the test plan in a headless phone-sized browser, against what was asked and the
brief, and either accepts — the owner is notified — or sends a follow-up with what
it found (at most ``pm.MAX_FIXES`` per cycle; then the owner gets it with the issues).
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
from autodev.core import shell
from autodev.core.claude import ClaudeRunner
from autodev.core.models import MERGED_STATUSES, Project, Task, TaskArtifact, TaskStatus
from autodev.worker import prompts
from autodev.worker.context import WorkerContext

logger = logging.getLogger(__name__)

AGENT = "pm"
MAX_SHOTS = 8

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["accepted", "changes"]},
        "summary": {
            "type": "string",
            "description": "In Russian, 1-3 sentences for the owner: what you checked on stage and how it went",
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
    """One acceptance pass. Leaves the task ``checking`` only when Claude is rate-limited."""
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
        await shell.run(
            "git", "clone", "--filter=blob:none", "-b", project.base_branch,
            f"https://github.com/{project.repo()['name']}.git", str(checkout),
            env=ctx.env(), timeout=600,
        )  # fmt: skip
        runner = ClaudeRunner(
            str(checkout),
            model=project.model or ctx.settings.model,
            timeout=ctx.settings.claude_timeout,
            env=ctx.env(),
            system_prompt_append=prompts.ACCEPT_SYSTEM,
            schema=SCHEMA,
            disallowed_tools=["Edit", "NotebookEdit"],  # Write stays: its browser scripts
        )
        result = await runner.run(prompts.acceptance(main, children, project, sys.executable, str(shots)), on_log=log)
        if result.rate_limited:
            ctx.paused_until = result.rate_limited_until
            await log("warning", f"⏸ Лимит Claude, продолжу в {result.rate_limited_until:%H:%M} UTC")
            return
        if not result.ok:
            raise RuntimeError(result.summary or "сессия PM не завершилась")
        screenshot = await _save_shots(ctx, task_id, shots)
        await _decide(ctx, main, project, result.data, screenshot, result.cost_usd, log)
    except Exception as exc:
        logger.exception("acceptance of %s failed", task_id)
        reason = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
        await log("error", f"❌ PM не смог проверить: {reason}", details=str(exc)[-4000:])
        await _finish(ctx, task_id, pm.FAILED, summary=f"PM не смог проверить: {reason}")
        await _notify(ctx, task_id, project)
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def _decide(ctx: WorkerContext, main: Task, project: Project, data: dict, screenshot, cost: float, log) -> None:
    summary = str(data.get("summary") or "").strip()
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
            metadata_={pm.KEY: True},
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


async def _save_shots(ctx: WorkerContext, task_id: uuid.UUID, shots: Path) -> bytes | None:
    """The PM's screenshots, as the task's artifacts; the first one for the notification."""
    files = sorted(p for p in shots.glob("*.png") if p.is_file())[:MAX_SHOTS]
    first = None
    async with ctx.session_factory() as session:
        for path in files:
            content = path.read_bytes()
            if not content.startswith(b"\x89PNG") or len(content) > 5_000_000:
                continue
            first = first or content
            session.add(
                TaskArtifact(
                    task_id=task_id,
                    kind="screenshot",
                    name=f"PM: {path.stem}",
                    content=content,
                    content_type="image/png",
                )
            )
        await session.commit()
    return first
