"""One scout pass over a project (see :mod:`autodev.scout`).

A project is due when it is switched on and idle: no work in the pipeline, the PM not
checking anything, room under the stage limit, and enough time passed since the last run.
The owner's button skips everything but the limit. Scout sessions run one at a time,
beside the developer slots.

Proposals come as a batch: run after run, without the interval, until the limit is full
or the scout finds less than it was asked for (``scout_run["collecting"]`` while it goes on).
Then the owner gets the batch in one message, and the next batch starts once they have
decided on all of it — nothing new turns up while they are going through it.
"""

from __future__ import annotations

import logging
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev import notify, pm, scout
from autodev.core.claude import READ_ONLY_WITH_SCRIPTS, ClaudeRunner
from autodev.core.models import (
    MERGED_STATUSES,
    OPEN_STATUSES,
    Priority,
    Project,
    Task,
    TaskArtifact,
    TaskSource,
    TaskStatus,
)
from autodev.worker import prompts
from autodev.worker.context import WorkerContext
from autodev.worker.workspace import clone_stage

logger = logging.getLogger(__name__)

AGENT = "scout"
#: Findings of one run, however much room there is: the owner reads them, the developers take turns.
MAX_FINDINGS = 5
MAX_SHOTS = 8
#: Recent tasks the scout is told about, so it doesn't find them again.
KNOWN_TASKS = 100

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "In Russian, 1-3 sentences for the owner: what you looked at and how the project is doing",
        },
        "findings": {
            "type": "array",
            "description": "What is worth fixing, most important first; empty when nothing is",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short, in Russian"},
                    "kind": {"type": "string", "enum": list(scout.KINDS)},
                    "description": {
                        "type": "string",
                        "description": "The whole brief for a developer, in Russian: what is wrong now and where, "
                        "what it should be, how to check",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "What proves it, in Russian: file:line, what the browser showed, a failing case",
                    },
                    "screenshots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File names from the screenshots directory that show it",
                    },
                },
                "required": ["title", "kind", "description", "evidence"],
            },
        },
    },
    "required": ["summary", "findings"],
}


async def recover(ctx: WorkerContext) -> None:
    """A run cut short by a restart starts over."""
    async with ctx.session_factory() as session:
        for project in (await session.execute(select(Project))).scalars():
            if scout.last_run(project).get("state") == scout.RUNNING:
                scout.request(project)
        await session.commit()


async def next_run(ctx: WorkerContext) -> str | None:
    """The project to scout next: the ones the owner asked for go first."""
    async with ctx.session_factory() as session:
        rows = await session.execute(select(Project).where(Project.enabled).order_by(Project.id))
        projects = [p for p in rows.scalars() if p.repo() is not None]
        for project in projects:
            if scout.last_run(project).get("state") == scout.REQUESTED:
                return project.id
        for project in projects:
            if await _due(ctx, session, project):
                return project.id
    return None


async def _due(ctx: WorkerContext, session: AsyncSession, project: Project) -> bool:
    if project.scout == scout.OFF:
        return False
    last = scout.last_run(project)
    collecting = last.get("collecting") and last.get("state") == scout.DONE
    if collecting:
        wait = 0
    elif last.get("state") == scout.DONE and last.get("found") == 0:
        # Nothing found: the code hardly changes by the hour, don't pay to read it again.
        wait = ctx.settings.scout_idle_interval
    else:
        wait = ctx.settings.scout_interval
    if last.get("at") and datetime.now(UTC) - datetime.fromisoformat(last["at"]) < timedelta(seconds=wait):
        return False
    if await _count(session, project.id, OPEN_STATUSES) or await _accepting(session, project.id):
        return False
    # A batch the owner is still going through: the next one waits.
    if not last.get("collecting") and await _count(session, project.id, {TaskStatus.PROPOSED}):
        return False
    return await scout.room(session, project) > 0


async def _count(session: AsyncSession, project_id: str, statuses) -> int:
    return await session.scalar(
        select(func.count()).select_from(Task).where(Task.project_id == project_id, Task.status.in_(statuses))
    )


async def _accepting(session: AsyncSession, project_id: str) -> bool:
    """The PM is walking a task on stage: what it finds comes first."""
    rows = await session.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.parent_id.is_(None),
            Task.status.in_(MERGED_STATUSES),
            cast(Task.metadata_, String).like(f'%"{pm.CHECKING}"%'),
        )
    )
    return any((pm.acceptance(t) or {}).get("state") == pm.CHECKING for t in rows.scalars())


async def run(ctx: WorkerContext, project_id: str) -> None:
    """One pass. Leaves the project ``requested`` when Claude is rate-limited, to run again after the reset."""
    async with ctx.session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return
        # A failed run keeps the batch going, after the interval.
        collecting = bool(scout.last_run(project).get("collecting"))
        project.scout_run = {"state": scout.RUNNING, "at": scout.now(), "collecting": collecting}
        limit = min(MAX_FINDINGS, await scout.room(session, project))
        known = list(
            (
                await session.execute(
                    select(Task)
                    .where(Task.project_id == project_id)
                    .order_by(Task.created_at.desc())
                    .limit(KNOWN_TASKS)
                )
            ).scalars()
        )
        history = await pm.history(session, project_id)
        await session.commit()
    if limit == 0:
        await _finish(ctx, project_id, scout.DONE, found=0, summary="Нет места: лимит задач на stage заполнен")
        return

    root = Path(ctx.settings.workdir) / "scout" / project_id
    shots = root / "shots"
    try:
        shutil.rmtree(root, ignore_errors=True)
        shots.mkdir(parents=True)
        checkout = root / "code"
        await clone_stage(project, checkout, ctx.env())
        runner = ClaudeRunner(
            str(checkout),
            model=project.model or ctx.settings.model,
            timeout=ctx.settings.claude_timeout,
            env=ctx.env(),
            system_prompt_append=prompts.SCOUT_SYSTEM,
            schema=SCHEMA,
            disallowed_tools=READ_ONLY_WITH_SCRIPTS,
        )
        prompt = prompts.scouting(project, known, history, limit, sys.executable, str(shots))

        async def log(level: str, message: str, details: str | None = None) -> None:
            logger.info("scout %s: %s", project_id, message)

        result = await runner.run(prompt, on_log=log)
        # What the owner sees matters most, and an agent happy with the code doesn't look.
        if result.ok and project.stage_url and not any(shots.glob("*.png")):
            result = await runner.run(prompts.scout_walk(str(shots)), resume=result.session_id, on_log=log)
        if result.rate_limited:
            await ctx.pause(result.rate_limited_until)
            logger.warning("scout %s: Claude limit until %s", project_id, result.rate_limited_until)
            await _finish(ctx, project_id, scout.REQUESTED)
            return
        if not result.ok:
            raise RuntimeError(result.summary or "сессия скаута не завершилась")
        summary = str(result.data.get("summary") or "").strip()
        tasks = await _file(ctx, project_id, _findings(result.data.get("findings"), known), shots)
        cost = round(result.cost_usd or 0, 2)
        async with ctx.session_factory() as session:
            project = await session.get(Project, project_id)
            # As many as asked: there may be more. Only the mode collects batches, not the button.
            collecting = (
                project.scout == scout.PROPOSE and len(tasks) >= limit and await scout.room(session, project) > 0
            )
            batch = await _proposals(session, project_id)
        await _finish(
            ctx, project_id, scout.DONE, found=len(tasks), summary=summary, cost_usd=cost, collecting=collecting
        )
        if tasks and tasks[0].status == TaskStatus.QUEUED:
            await notify.scouted(project, tasks, summary)
        elif batch and not collecting:
            await notify.proposals(project, batch, summary)
    except Exception as exc:
        logger.exception("scout of %s failed", project_id)
        reason = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
        await _finish(
            ctx, project_id, scout.FAILED, summary=f"Скаут не смог пройти проект: {reason}", collecting=collecting
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def _proposals(session: AsyncSession, project_id: str) -> list[Task]:
    rows = await session.execute(
        select(Task)
        .where(Task.project_id == project_id, Task.status == TaskStatus.PROPOSED)
        .order_by(Task.ticket_number)
    )
    return list(rows.scalars())


def _findings(raw, known: list[Task]) -> list[dict]:
    """Findings worth filing: complete, with evidence, and not a task the project already has."""
    titles = {t.title.strip().casefold() for t in known}
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title, description = str(item.get("title") or "").strip(), str(item.get("description") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not (title and description and evidence) or title.casefold() in titles:
            continue
        titles.add(title.casefold())
        shots = item.get("screenshots")
        out.append(
            {
                "title": title[:200],
                "kind": item.get("kind") if item.get("kind") in scout.KINDS else "debt",
                "description": description,
                "evidence": evidence,
                "screenshots": [str(s) for s in shots] if isinstance(shots, list) else [],
            }
        )
    return out[:MAX_FINDINGS]


async def _file(ctx: WorkerContext, project_id: str, findings: list[dict], shots: Path) -> list[Task]:
    """The findings as tasks. Low priority: what the owner asks for goes first."""
    async with ctx.session_factory() as session:
        project = await session.get(Project, project_id, with_for_update=True)
        # The session took a while: the owner may have added tasks meanwhile.
        findings = findings[: await scout.room(session, project)]
        status = TaskStatus.QUEUED if project.scout == scout.AUTO else TaskStatus.PROPOSED
        tasks = []
        for finding in findings:
            task = Task(
                title=finding["title"],
                description=f"{finding['description']}\n\n**Откуда видно:** {finding['evidence']}",
                project_id=project_id,
                repo=project.repo()["name"],
                source=TaskSource.AGENT_CREATED,
                priority=Priority.LOW,
                created_by=scout.AUTHOR,
                status=status,
                metadata_={scout.KEY: {"kind": finding["kind"], "evidence": finding["evidence"]}},
            )
            session.add(task)
            await session.flush()
            _attach(session, task, finding["screenshots"], shots)
            tasks.append(task)
        await session.commit()
        return tasks


def _attach(session: AsyncSession, task: Task, names: list[str], shots: Path) -> None:
    for name in names[:MAX_SHOTS]:
        path = shots / Path(name).name  # the agent's text, keep it inside the directory
        if not path.is_file():
            continue
        content = path.read_bytes()
        if content.startswith(b"\x89PNG") and len(content) <= 5_000_000:
            session.add(
                TaskArtifact(
                    task_id=task.id,
                    kind="screenshot",
                    name=f"Скаут: {path.stem}",
                    content=content,
                    content_type="image/png",
                )
            )


async def _finish(ctx: WorkerContext, project_id: str, state: str, **fields) -> None:
    async with ctx.session_factory() as session:
        project = await session.get(Project, project_id)
        if project is not None:
            project.scout_run = {**fields, "state": state, "at": scout.now()}
            await session.commit()
