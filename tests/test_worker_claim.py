"""Task claiming: priority, dependencies, per-project parallelism, project resolution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from autodev.core.config import Settings
from autodev.core.models import Agent, Task, TaskStatus
from autodev.worker.context import WorkerContext
from autodev.worker.loop import Worker
from tests.conftest import make_project


def worker(session_factory) -> Worker:
    return Worker(WorkerContext(settings=Settings(), session_factory=session_factory))


async def add(session_factory, *objs) -> None:
    async with session_factory() as s:
        s.add_all(objs)
        await s.commit()


def task(title: str, **kw) -> Task:
    kw.setdefault("project_id", "shop")
    kw.setdefault("status", TaskStatus.QUEUED)
    return Task(title=title, metadata_={}, **kw)


async def test_priority_then_age(session_factory, project) -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    await add(
        session_factory,
        task("low", priority="low", created_at=old),
        task("high", priority="high"),
        task("normal old", created_at=old),
    )
    w = worker(session_factory)
    first = await w.claim("s1")
    async with session_factory() as s:
        claimed = await s.get(Task, first)
        assert claimed.title == "high"
        assert claimed.status == TaskStatus.IN_PROGRESS and claimed.assigned_to == "s1"


async def test_max_parallel_per_project(session_factory, project) -> None:
    await add(session_factory, task("a"), task("b"))
    w = worker(session_factory)
    assert await w.claim("s1") is not None
    assert await w.claim("s2") is None  # max_parallel=1


async def test_other_project_runs_in_parallel(session_factory, project) -> None:
    await add(session_factory, make_project("blog"))
    await add(session_factory, task("a"), task("b", project_id="blog"))
    w = worker(session_factory)
    assert await w.claim("s1") is not None
    assert await w.claim("s2") is not None


async def test_dependencies_must_be_merged(session_factory, project) -> None:
    dep = task("dep", status=TaskStatus.CI)
    await add(session_factory, dep)
    await add(session_factory, task("child", depends_on=[dep.id]))
    w = worker(session_factory)
    assert await w.claim("s1") is None
    async with session_factory() as s:
        (await s.get(Task, dep.id)).status = TaskStatus.ON_STAGE
        await s.commit()
    assert await w.claim("s1") is not None


async def test_disabled_project_and_global_switch(session_factory) -> None:
    await add(session_factory, make_project(enabled=False), make_project("blog"))
    await add(session_factory, task("a"))
    w = worker(session_factory)
    assert await w.claim("s1") is None

    await add(session_factory, task("b", project_id="blog"), Agent(id="developer", role="developer", enabled=False))
    assert not await w.developers_enabled()


async def test_project_inferred_from_repo(session_factory, project) -> None:
    await add(session_factory, make_project("blog"))
    await add(session_factory, task("legacy", project_id=None, repo="acme/blog"))
    claimed = await worker(session_factory).claim("s1")
    async with session_factory() as s:
        assert (await s.get(Task, claimed)).project_id == "blog"


async def test_unresolvable_project_fails(session_factory, project) -> None:
    await add(session_factory, make_project("blog"))
    t = task("orphan", project_id=None, repo="acme/unknown")
    await add(session_factory, t)
    assert await worker(session_factory).claim("s1") is None
    async with session_factory() as s:
        orphan = await s.get(Task, t.id)
        assert orphan.status == TaskStatus.FAILED and "project" in orphan.error


async def test_recover_requeues_in_progress(session_factory, project) -> None:
    t = task("stuck", status=TaskStatus.IN_PROGRESS, assigned_to="s1")
    await add(session_factory, t)
    await worker(session_factory).recover()
    async with session_factory() as s:
        assert (await s.get(Task, t.id)).status == TaskStatus.QUEUED


async def test_drain_file_stops_new_claims(session_factory, project, tmp_path, monkeypatch) -> None:
    from autodev.worker import loop as loop_mod

    drain = tmp_path / "drain"
    w = Worker(
        WorkerContext(
            settings=Settings(AUTODEV_DRAIN_FILE=str(drain), AUTODEV_POLL_INTERVAL=0.01),
            session_factory=session_factory,
        )
    )
    developed: list = []

    async def fake_develop(ctx, task_id, slot):
        developed.append(task_id)

    monkeypatch.setattr(loop_mod, "develop", fake_develop)
    await add(session_factory, task("waits for the update"))
    drain.touch()
    slot = asyncio.create_task(w.slot_loop("s1"))
    await asyncio.sleep(0.1)
    assert developed == []

    drain.unlink()
    for _ in range(100):
        if developed:
            break
        await asyncio.sleep(0.02)
    w.stop()
    await asyncio.wait_for(slot, 1)
    assert len(developed) == 1


async def test_stop_lets_running_task_finish(session_factory, project, monkeypatch) -> None:
    from autodev.worker import loop as loop_mod

    w = Worker(WorkerContext(settings=Settings(AUTODEV_POLL_INTERVAL=0.01), session_factory=session_factory))
    started, release = asyncio.Event(), asyncio.Event()
    finished: list = []

    async def slow_develop(ctx, task_id, slot):
        started.set()
        await release.wait()
        finished.append(task_id)

    monkeypatch.setattr(loop_mod, "develop", slow_develop)
    await add(session_factory, task("long one"), task("must not start"))
    slot = asyncio.create_task(w.slot_loop("s1"))
    await asyncio.wait_for(started.wait(), 2)

    w.stop()
    await asyncio.sleep(0.05)
    assert not slot.done()  # still waiting for the running session
    release.set()
    await asyncio.wait_for(slot, 1)
    assert len(finished) == 1
    async with session_factory() as s:
        statuses = sorted((await s.execute(select(Task.status))).scalars())
    assert statuses.count(TaskStatus.QUEUED) == 1
