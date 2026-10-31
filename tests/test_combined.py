"""One diff for a task and its follow-ups: their merges replayed without the other tasks' merges in between."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autodev.core.config import Settings
from autodev.core.models import Task, TaskStatus
from autodev.worker import combined
from autodev.worker.context import WorkerContext
from tests.conftest import make_project


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class Origin:
    """A local 'GitHub' repo with a stage branch; merge() lands a squash commit on it."""

    def __init__(self, tmp_path: Path) -> None:
        self.bare, self.seed = tmp_path / "shop.git", tmp_path / "seed"
        git("init", "-q", "--bare", "-b", "stage", str(self.bare), cwd=tmp_path)
        git("init", "-q", "-b", "stage", str(self.seed), cwd=tmp_path)
        git("remote", "add", "origin", str(self.bare), cwd=self.seed)
        self.merge({"app.txt": "v0\n"}, "init")

    def merge(self, files: dict[str, str], message: str) -> str:
        for name, text in files.items():
            (self.seed / name).write_text(text)
        git("add", "-A", cwd=self.seed)
        git("commit", "-qm", message, cwd=self.seed)
        git("push", "-q", "origin", "stage", cwd=self.seed)
        return git("rev-parse", "HEAD", cwd=self.seed)

    def files(self, ref: str) -> dict[str, str]:
        names = git("--git-dir", str(self.bare), "ls-tree", "--name-only", ref, cwd=self.seed).split()
        return {n: git("--git-dir", str(self.bare), "show", f"{ref}:{n}", cwd=self.seed) for n in names}


@pytest.fixture
def origin(tmp_path, monkeypatch) -> Origin:
    origin = Origin(tmp_path)
    real_run = combined.shell.run

    async def local(*args, **kw):  # github.com → the local bare repo
        args = [str(origin.bare) if a == "https://github.com/acme/shop.git" else a for a in args]
        return await real_run(*args, **kw)

    monkeypatch.setattr(combined.shell, "run", local)
    return origin


@pytest.fixture
async def ctx(tmp_path, session_factory) -> WorkerContext:
    async with session_factory() as s:
        s.add(make_project("shop"))
        await s.commit()
    return WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path / "work")), session_factory=session_factory)


async def add(ctx: WorkerContext, **kw) -> Task:
    async with ctx.session_factory() as s:
        t = Task(**{"project_id": "shop", "repo": "acme/shop", "status": TaskStatus.ON_STAGE, "metadata_": {}, **kw})
        s.add(t)
        await s.commit()
        await s.refresh(t)
        return t


async def metadata(ctx: WorkerContext, task_id) -> dict:
    async with ctx.session_factory() as s:
        return (await s.get(Task, task_id)).metadata_


async def test_follow_ups_replayed_without_other_tasks(ctx, origin) -> None:
    main = await add(ctx, title="Главная", merge_sha=origin.merge({"app.txt": "v1\n"}, "main task"))
    origin.merge({"other.txt": "чужое\n"}, "someone else's task")
    await add(ctx, title="Доработка", parent_id=main.id, merge_sha=origin.merge({"app.txt": "v2\n"}, "follow-up"))
    await add(ctx, title="Ещё в CI", parent_id=main.id, status=TaskStatus.CI)
    await ctx.store.patch_metadata(main.id, lambda m: m.update({combined.PENDING: True}))
    assert await combined.pending(ctx) == [main.id]

    await combined.rebuild(ctx, main.id)

    full = (await metadata(ctx, main.id))[combined.KEY]
    assert full["tasks"] == 2
    base, head = full["url"].removeprefix("https://github.com/acme/shop/compare/").split("...")
    assert origin.files(base) == {"app.txt": "v0"}
    assert origin.files(combined.ref(main.ticket_number)) == {"app.txt": "v2"}  # no other.txt
    assert git("--git-dir", str(origin.bare), "rev-parse", combined.ref(main.ticket_number), cwd=origin.seed) == head
    assert await combined.pending(ctx) == []


async def test_single_pr_needs_no_diff(ctx, origin) -> None:
    main = await add(ctx, title="Главная", merge_sha=origin.merge({"app.txt": "v1\n"}, "main task"))
    await ctx.store.patch_metadata(main.id, lambda m: m.update({combined.PENDING: True}))

    await combined.rebuild(ctx, main.id)

    assert await metadata(ctx, main.id) == {}


async def test_follow_up_that_needs_the_skipped_task_is_reported(ctx, origin) -> None:
    main = await add(ctx, title="Главная", merge_sha=origin.merge({"app.txt": "v1\n"}, "main task"))
    origin.merge({"app.txt": "чужое\n"}, "someone else rewrote the same line")
    child = await add(
        ctx, title="Доработка", parent_id=main.id, merge_sha=origin.merge({"app.txt": "v2\n"}, "follow-up")
    )

    await combined.rebuild(ctx, main.id)

    full = (await metadata(ctx, main.id))[combined.KEY]
    assert "url" not in full
    assert f"#{child.ticket_number}" in full["error"]


async def test_backfill_marks_families_merged_earlier(ctx, origin) -> None:
    main = await add(ctx, title="Главная", merge_sha="a" * 40)
    await add(ctx, title="Доработка", parent_id=main.id, merge_sha="b" * 40)
    alone = await add(ctx, title="Без доработок", merge_sha="c" * 40)

    await combined.backfill(ctx)

    assert await combined.pending(ctx) == [main.id]
    assert await metadata(ctx, alone.id) == {}
