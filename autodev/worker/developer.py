"""Developer: one Claude session per task round, then push and PR."""

from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select

from autodev import notify, review
from autodev.core.claude import ClaudeResult, ClaudeRunner
from autodev.core.models import Task, TaskStatus
from autodev.worker import prompts
from autodev.worker.context import WorkerContext
from autodev.worker.workspace import Workspace, branch_name

logger = logging.getLogger(__name__)


class TaskFailed(Exception):
    """The round failed for a reason worth showing to the owner."""


async def develop(ctx: WorkerContext, task_id: uuid.UUID, slot: str) -> None:
    """Run one development round for a task that is already ``in_progress``."""
    store = ctx.store
    task = await store.get(task_id)
    if task is None:
        return

    async def log(level: str, message: str, details: str | None = None) -> None:
        await store.log(task_id, message, level=level, details=details, agent=slot)

    async def cancelled() -> bool:
        current = await store.get(task_id)
        return current is None or current.status == TaskStatus.CANCELLED

    project = task.project
    ws: Workspace | None = None
    try:
        if project is None:
            raise TaskFailed("Task has no project")
        repo = project.repo()
        if repo is None:
            raise TaskFailed(f"Project {project.id} has no repo")

        fix: dict | None = (task.metadata_ or {}).get("fix")
        branch = task.branch or branch_name(task.ticket_number, task.title)
        existing = bool(task.branch and task.pr_number)
        task = await store.update(task_id, branch=branch, repo=repo["name"]) or task
        base = project.base_branch

        ws = Workspace(ctx.settings.workdir, str(task_id), repo["name"], ctx.env())
        await log("info", f"📥 {repo['name']}: {'branch ' + branch if existing else 'new branch from ' + base}")
        await ws.prepare(base, branch, existing)

        need_agent = True
        if fix and fix.get("kind") == "conflict" and existing:
            if await ws.merge_base(base):
                await log("info", f"🔀 Merged {base} without conflicts")
                need_agent = False

        if not existing and repo.get("setup"):
            await log("info", "⚙️ Running repo setup")
            try:
                out = await ws.run_setup(repo["setup"])
                await log("info", "⚙️ Setup done", details=out[-4000:] or None)
            except Exception as exc:  # setup helps the agent but is not required
                await log("warning", "⚙️ Setup failed, continuing without it", details=str(exc)[-4000:])

        if need_agent:
            deps = await _load_deps(ctx, task)
            # A follow-up/part is checked as part of its main task: the agent updates the main task's plan.
            main = await store.get(task.parent_id) if task.parent_id else None
            main_plan = list((main.metadata_ or {}).get("test_plan") or []) if main else []
            result = await _run_agent(ctx, task, project, repo, deps, fix, existing, ws.path, log, cancelled, main)
            if result.cancelled:
                await log("warning", "⏹ Cancelled")
                return
            if result.rate_limited:
                await _requeue_rate_limited(ctx, task, result.rate_limited_until, slot, result.session_id)
                return
            await log(
                "info",
                f"🧠 Agent finished: {result.num_turns} turns, ${result.cost_usd:.2f}",
                details=result.summary or None,
            )
            if result.blocked:
                moved = await store.transition(
                    task_id,
                    TaskStatus.FAILED,
                    reason="agent is blocked",
                    by=slot,
                    only_from={TaskStatus.IN_PROGRESS},
                    error=result.summary,
                    session_id=result.session_id,
                )
                if moved:
                    await notify.blocked(moved, result.summary)
                return
            if not result.ok:
                raise TaskFailed(result.summary or "Agent session failed")
            fields: dict = {"session_id": result.session_id or task.session_id}
            if not fix:
                fields["summary"] = result.summary
            title = agent_title(result.data.get("title"))
            if title and not existing and not (task.metadata_ or {}).get(OWNER_TITLE):
                fields["title"] = title  # before the PR is opened: it takes the title too
            metadata = dict(task.metadata_ or {})
            paths = _strings(result.data.get("check_paths"))
            if paths:
                metadata["check_paths"] = paths[:5]
            plan = _strings(result.data.get("test_plan"))
            if plan and main is not None:
                metadata["root_plan"] = {"base": main_plan, "plan": plan[: review.MAX_PLAN]}
            elif plan and plan[:15] != metadata.get("test_plan"):
                metadata = review.new_version(metadata, plan[:15])
            if metadata != (task.metadata_ or {}):
                fields["metadata_"] = metadata
            task = await store.update(task_id, **fields) or task

        if await ws.in_merge():
            unresolved = (await ws.git("diff", "--name-only", "--diff-filter=U")).strip()
            if unresolved:
                raise TaskFailed(f"Merge conflicts left unresolved:\n{unresolved}")
        await ws.commit_leftovers(f"chore: finish #{task.ticket_number} {task.title[:60]}")
        if await ws.commits_ahead(base) == 0:
            raise TaskFailed("The agent finished without committing any change.\n\n" + (task.summary or ""))

        await ws.push(branch)
        await log("info", f"⬆️ Pushed {branch}")
        pr_number, pr_url = await _ensure_pr(ctx, task, repo["name"], base, branch)

        metadata = dict(task.metadata_ or {})
        metadata.pop("fix", None)
        moved = await store.transition(
            task_id,
            TaskStatus.CI,
            reason=f"PR #{pr_number}",
            by=slot,
            only_from={TaskStatus.IN_PROGRESS},
            pr_number=pr_number,
            pr_url=pr_url,
            metadata_=metadata,
            error=None,
        )
        if moved is None:
            await log("warning", "Task changed state while running (cancelled?) — leaving the PR as is")

    except Exception as exc:
        reason = str(exc) if isinstance(exc, TaskFailed) else f"{type(exc).__name__}: {exc}"
        if not isinstance(exc, TaskFailed):
            logger.exception("task %s crashed", task_id)
        await log("error", f"❌ {reason.splitlines()[0][:200]}", details=reason)
        moved = await store.transition(
            task_id, TaskStatus.FAILED, reason="round failed", by=slot, only_from={TaskStatus.IN_PROGRESS}, error=reason
        )
        if moved:
            await notify.failed(moved, reason)
    finally:
        if ws is not None:
            ws.cleanup()


#: Task metadata: the owner renamed the task; the agent's title doesn't replace theirs.
OWNER_TITLE = "title_by_owner"


def agent_title(value) -> str | None:
    """The agent's title for the task, tidied; None if it gave none."""
    if not isinstance(value, str):
        return None
    title = " ".join(value.split()).strip("«»\"' .")
    return title[:140] or None


def _strings(value) -> list[str]:
    return [v.strip() for v in value or [] if isinstance(v, str) and v.strip()]


async def _requeue_rate_limited(
    ctx: WorkerContext, task: Task, until, slot: str, session_id: str | None = None
) -> None:
    ctx.paused_until = until
    await ctx.store.transition(
        task.id,
        TaskStatus.QUEUED,
        reason=f"Claude limit, resumes {until:%H:%M} UTC",
        by=slot,
        only_from={TaskStatus.IN_PROGRESS},
        session_id=session_id or task.session_id,
    )


async def _run_agent(ctx, task, project, repo, deps, fix, existing, cwd, log, cancelled, main=None) -> ClaudeResult:
    runner = ClaudeRunner(
        cwd,
        model=project.model or ctx.settings.model,
        timeout=ctx.settings.claude_timeout,
        env=ctx.env(),
        system_prompt_append=prompts.SYSTEM,
    )
    if fix and existing and task.session_id:
        await log("info", f"🧠 Resuming session for {fix.get('kind')} fix")
        result = await runner.run(
            prompts.fix(fix.get("kind", ""), fix.get("details", ""), task, project, main),
            resume=task.session_id,
            on_log=log,
            should_cancel=cancelled,
        )
        if not result.session_missing:
            return result
        await log("warning", "Previous session is gone — starting a fresh one")

    if fix and existing:
        prompt = prompts.fix_fresh(fix.get("kind", ""), fix.get("details", ""), task, project, repo, deps, main)
    else:
        prompt = prompts.initial(task, project, repo, deps, main)
        if fix and fix.get("details"):
            prompt += "\n\n## Notes from the previous attempt\n" + fix["details"]
    await log("info", "🧠 Agent started")
    return await runner.run(prompt, on_log=log, should_cancel=cancelled)


async def _load_deps(ctx: WorkerContext, task: Task) -> list[Task]:
    if not task.depends_on:
        return []
    async with ctx.session_factory() as session:
        rows = await session.execute(select(Task).where(Task.id.in_(task.depends_on)))
        return list(rows.scalars())


async def _ensure_pr(ctx: WorkerContext, task: Task, repo: str, base: str, branch: str) -> tuple[int, str]:
    if task.pr_number and task.pr_url:
        return task.pr_number, task.pr_url
    body = (task.summary or task.description or task.title).strip()
    metadata = task.metadata_ or {}
    plan = metadata.get("test_plan") or (metadata.get("root_plan") or {}).get("plan") or []
    if plan:
        body += "\n\n### Как проверить на stage\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(plan, 1))
    body += f"\n\n---\nAutoDev task #{task.ticket_number}"
    if ctx.settings.public_url:
        body += f" · {ctx.settings.public_url.rstrip('/')}/tasks/{task.id}"
    async with ctx.github() as gh:
        try:
            pr = await gh.create_pr(title=task.title, head=branch, base=base, body=body, repo=repo)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422:
                raise
            pr = await gh.find_open_pr(branch, base, repo)
            if pr is None:
                raise TaskFailed(f"Could not open a PR: {exc.response.text[:500]}") from exc
    await ctx.store.log(task.id, f"🔗 PR #{pr['number']}: {pr['html_url']}")
    return pr["number"], pr["html_url"]
