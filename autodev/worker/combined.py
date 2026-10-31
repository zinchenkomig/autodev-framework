"""One diff for a task with its follow-ups.

Each follow-up is its own PR, squash-merged into the base branch between other
tasks' merges, so no GitHub page shows the task's code as a whole. Here the
family's merge commits are replayed, in merge order, on the commit the first one
started from, and the result is pushed to ``refs/autodev/task-<N>`` — a ref
outside branches and tags, so it starts no workflows — for a GitHub compare link.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from autodev.core import shell
from autodev.core.models import Task
from autodev.worker.context import WorkerContext

logger = logging.getLogger(__name__)

#: Main-task metadata: a merge happened in the family, the diff is to be rebuilt.
PENDING = "full_diff_pending"
#: Main-task metadata: {"url", "shas", "tasks"} or {"error", "shas"}.
KEY = "full_diff"


def ref(ticket: int) -> str:
    return f"refs/autodev/task-{ticket}"


async def family(ctx: WorkerContext, root_id: uuid.UUID) -> tuple[Task | None, list[Task]]:
    """The main task and its merged tasks (itself included) in its repo."""
    async with ctx.session_factory() as session:
        root = await session.get(Task, root_id)
        if root is None:
            return None, []
        rows = await session.execute(select(Task).where(Task.parent_id == root_id))
        tasks = [root, *rows.scalars()]
    return root, [t for t in tasks if t.merge_sha and t.repo == root.repo]


async def pending(ctx: WorkerContext) -> list[uuid.UUID]:
    async with ctx.session_factory() as session:
        rows = await session.execute(select(Task.id, Task.metadata_).where(Task.parent_id.is_(None)))
        return [task_id for task_id, metadata in rows if (metadata or {}).get(PENDING)]


async def backfill(ctx: WorkerContext) -> None:
    """Families merged before this existed (or while a rebuild was lost) get their diff on start."""
    async with ctx.session_factory() as session:
        rows = await session.execute(
            select(Task.parent_id).where(Task.parent_id.is_not(None), Task.merge_sha.is_not(None)).distinct()
        )
        for root_id in rows.scalars():
            root = await session.get(Task, root_id)
            if root is not None and KEY not in (root.metadata_ or {}):
                root.metadata_ = {**(root.metadata_ or {}), PENDING: True}
        await session.commit()


async def rebuild(ctx: WorkerContext, root_id: uuid.UUID) -> None:
    root, merged = await family(ctx, root_id)
    if root is None:
        return
    shas = sorted(t.merge_sha for t in merged)
    if len(merged) < 2 or root.project is None:
        await _save(ctx, root_id, shas, None)  # one PR is the whole change
        return
    path = Path(ctx.settings.workdir) / "combined" / str(root_id)
    shutil.rmtree(path, ignore_errors=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    env = ctx.env()

    async def git(*args: str, timeout: float = 120) -> str:
        return await shell.run("git", *args, cwd=str(path), env=env, timeout=timeout)

    try:
        base_branch = root.project.base_branch
        await shell.run(
            "git", "clone", "--filter=blob:none", "-b", base_branch,
            f"https://github.com/{root.repo}.git", str(path), env=env, timeout=600,
        )  # fmt: skip
        history = (await git("rev-list", "--reverse", "--first-parent", f"origin/{base_branch}")).split()
        wanted = set(shas)
        order = [sha for sha in history if sha in wanted]
        if len(order) < 2:
            await _save(ctx, root_id, shas, None)
            return
        base = (await git("rev-parse", f"{order[0]}^1")).strip()
        await git("checkout", "-q", "--detach", base)
        for sha in order:
            parents = (await git("rev-list", "--parents", "-n", "1", sha)).split()[1:]
            mainline = ["-m", "1"] if len(parents) > 1 else []
            try:
                await git("cherry-pick", "--allow-empty", "--keep-redundant-commits", *mainline, sha)
            except shell.CommandError:
                task = next(t for t in merged if t.merge_sha == sha)
                await _save(ctx, root_id, shas, {"error": f"#{task.ticket_number} не накладывается поверх предыдущих"})
                return
        head = (await git("rev-parse", "HEAD")).strip()
        await git("push", "--force", "origin", f"HEAD:{ref(root.ticket_number)}", timeout=300)
        url = f"https://github.com/{root.repo}/compare/{base}...{head}"
        await _save(ctx, root_id, shas, {"url": url, "tasks": len(order)})
        logger.info("full diff for #%s: %d merges → %s", root.ticket_number, len(order), url)
    finally:
        shutil.rmtree(path, ignore_errors=True)


async def _save(ctx: WorkerContext, root_id: uuid.UUID, shas: list[str], result: dict | None) -> None:
    """Store the result; leave the rebuild pending if another merge landed meanwhile."""
    _, merged = await family(ctx, root_id)
    current = sorted(t.merge_sha for t in merged)

    def apply(metadata: dict) -> None:
        if result is None:
            metadata.pop(KEY, None)
        else:
            metadata[KEY] = {**result, "shas": shas}
        if current == shas:
            metadata.pop(PENDING, None)

    await ctx.store.patch_metadata(root_id, apply)
