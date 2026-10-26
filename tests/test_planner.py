"""Plan refresh: the planner rewrites a main task's plan from the task, its follow-ups and stage."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autodev.core.claude import ClaudeResult
from autodev.core.config import Settings
from autodev.core.models import Project, Task, TaskStatus
from autodev.worker import planner, prompts
from autodev.worker.context import WorkerContext
from tests.conftest import make_project


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def bare_repo(tmp_path: Path, name: str) -> Path:
    """A local 'origin' with a stage branch holding one file named after the repo."""
    bare, seed = tmp_path / f"{name}.git", tmp_path / f"{name}-seed"
    git("init", "-q", "--bare", "-b", "stage", str(bare), cwd=tmp_path)
    git("init", "-q", "-b", "stage", str(seed), cwd=tmp_path)
    (seed / f"{name}.txt").write_text(name)
    git("add", "-A", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=seed)
    git("remote", "add", "origin", str(bare), cwd=seed)
    git("push", "-q", "origin", "stage", cwd=seed)
    return bare


class FakeRunner:
    calls: list[dict] = []
    result = ClaudeResult(
        ok=True, summary="План по всему", data={"status": "done", "test_plan": ["Новый 1", "Новый 2"]}
    )
    before_return = None

    def __init__(self, cwd, **kw) -> None:
        self.cwd = Path(cwd)
        self.kw = kw

    async def run(self, prompt, *, resume=None, on_log=None, should_cancel=None):
        FakeRunner.calls.append(
            {"prompt": prompt, "cwd": self.cwd, "checkouts": sorted(p.name for p in self.cwd.iterdir()), **self.kw}
        )
        if FakeRunner.before_return:
            await FakeRunner.before_return()
        return FakeRunner.result


@pytest.fixture
def ctx(monkeypatch, tmp_path, session_factory):
    origins = {r: bare_repo(tmp_path, r.split("/")[-1]) for r in ("acme/back", "acme/front")}
    real_run = planner.shell.run

    async def local_clone(*args, **kw):  # github.com → the local bare repos
        args = [
            str(origins[a.removeprefix("https://github.com/").removesuffix(".git")])
            if a.startswith("https://github.com/")
            else a
            for a in args
        ]
        return await real_run(*args, **kw)

    monkeypatch.setattr(planner.shell, "run", local_clone)
    monkeypatch.setattr(planner, "ClaudeRunner", FakeRunner)
    FakeRunner.calls, FakeRunner.before_return = [], None
    FakeRunner.result = ClaudeResult(
        ok=True, summary="План по всему", data={"status": "done", "test_plan": ["Новый 1", "Новый 2"]}
    )
    return WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path / "work")), session_factory=session_factory)


async def add(session_factory, **kw) -> Task:
    async with session_factory() as s:
        t = Task(**{"project_id": "alerter", "status": TaskStatus.ON_STAGE, "metadata_": {}, **kw})
        s.add(t)
        await s.commit()
        await s.refresh(t)
        return t


async def reload(session_factory, task_id) -> Task:
    async with session_factory() as s:
        return await s.get(Task, task_id)


@pytest.fixture
async def family(session_factory):
    async with session_factory() as s:
        s.add(make_project("alerter", repos=[{"name": "acme/back"}]))
        await s.commit()
    main = await add(
        session_factory, title="Откаты метрик", repo="acme/back", summary="бэкенд",
        metadata_={"plan_refresh": {"requested_at": "2026-10-26T10:00:00"}, "test_plan": ["Старый"], "plan_checked": [0]},
    )  # fmt: skip
    ui = await add(
        session_factory, title="Экран проблем", repo="acme/front", parent_id=main.id, metadata_={"test_plan": ["свой"]}
    )
    await add(session_factory, title="В работе", repo="acme/front", parent_id=main.id, status=TaskStatus.CI)
    await add(session_factory, title="Отменена", repo="acme/other", parent_id=main.id, status=TaskStatus.CANCELLED)
    return main, ui


async def test_refresh_rewrites_the_plan_from_landed_follow_ups(ctx, session_factory, family) -> None:
    main, ui = family
    assert await planner.next_request(ctx) == main.id
    await planner.refresh_plan(ctx, main.id)

    got = await reload(session_factory, main.id)
    assert got.metadata_["test_plan"] == ["Новый 1", "Новый 2"]
    assert "plan_refresh" not in got.metadata_ and "plan_checked" not in got.metadata_
    assert await planner.next_request(ctx) is None

    call = FakeRunner.calls[0]
    assert call["checkouts"] == ["back", "front"]  # stage of every repo that landed work; not the cancelled one
    assert f"#{ui.ticket_number}" in call["prompt"] and "Экран проблем" in call["prompt"] and "свой" in call["prompt"]
    assert "В работе" not in call["prompt"] and "Отменена" not in call["prompt"]
    assert "Старый" in call["prompt"]
    assert call["schema"] is planner.SCHEMA and call["system_prompt_append"] == prompts.PLANNER_SYSTEM
    assert not call["cwd"].exists()  # checkouts cleaned up


async def test_follow_up_landing_during_refresh_keeps_its_steps(ctx, session_factory, family) -> None:
    main, _ = family

    async def child_lands():
        async with session_factory() as s:
            t = await s.get(Task, main.id)
            t.metadata_ = {**t.metadata_, "test_plan": ["Старый", "Фильтр"]}
            await s.commit()

    FakeRunner.before_return = child_lands
    await planner.refresh_plan(ctx, main.id)
    assert (await reload(session_factory, main.id)).metadata_["test_plan"] == ["Новый 1", "Новый 2", "Фильтр"]


async def test_failed_refresh_keeps_the_old_plan(ctx, session_factory, family) -> None:
    main, _ = family
    FakeRunner.result = ClaudeResult(ok=False, summary="Не вышло")
    await planner.refresh_plan(ctx, main.id)
    got = await reload(session_factory, main.id)
    assert got.metadata_["test_plan"] == ["Старый"] and got.metadata_["plan_checked"] == [0]
    assert "plan_refresh" not in got.metadata_  # the owner can ask again


async def test_rate_limit_keeps_the_request(ctx, session_factory, family) -> None:
    from datetime import UTC, datetime, timedelta

    main, _ = family
    until = datetime.now(UTC) + timedelta(hours=1)
    FakeRunner.result = ClaudeResult(ok=False, summary="limit", rate_limited_until=until)
    await planner.refresh_plan(ctx, main.id)
    assert "plan_refresh" in (await reload(session_factory, main.id)).metadata_
    assert ctx.paused_until == until


def test_prompt_without_follow_ups() -> None:
    project = Project(id="p", name="P", repos=[{"name": "acme/p"}], stage_url="https://stage.p", base_branch="stage")
    main = Task(ticket_number=7, title="Медленно", description="ускорь", repo="acme/p", metadata_={})
    text = prompts.plan_refresh(main, [], project, ["acme/p"])
    assert "#7" in text and "ускорь" in text and "https://stage.p" in text and "`p/` = acme/p" in text
