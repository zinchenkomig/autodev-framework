"""PM acceptance: the PM checks a main task on stage before the owner is called."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from autodev import pm
from autodev.core.claude import ClaudeResult
from autodev.core.config import Settings
from autodev.core.models import Task, TaskArtifact, TaskStatus
from autodev.worker import acceptor
from autodev.worker.context import WorkerContext


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class FakeRunner:
    calls: list[dict] = []
    result = ClaudeResult(ok=True, summary="", data={"verdict": "accepted", "summary": "Прошёл план, всё работает"})
    shot = True

    def __init__(self, cwd, **kw) -> None:
        self.cwd = Path(cwd)
        self.kw = kw

    async def run(self, prompt, *, resume=None, on_log=None, should_cancel=None):
        FakeRunner.calls.append({"prompt": prompt, "cwd": self.cwd, **self.kw})
        if FakeRunner.shot:
            shots = Path(prompt.split("Screenshots directory: `")[1].split("`")[0])
            (shots / "01-home.png").write_bytes(b"\x89PNGhome")
            (shots / "notes.txt").write_text("not a screenshot")
        return FakeRunner.result


@pytest.fixture
def ctx(monkeypatch, tmp_path, session_factory):
    bare, seed = tmp_path / "shop.git", tmp_path / "seed"
    git("init", "-q", "--bare", "-b", "stage", str(bare), cwd=tmp_path)
    git("init", "-q", "-b", "stage", str(seed), cwd=tmp_path)
    (seed / "app.txt").write_text("app")
    git("add", "-A", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=seed)
    git("remote", "add", "origin", str(bare), cwd=seed)
    git("push", "-q", "origin", "stage", cwd=seed)
    real_run = acceptor.shell.run

    async def local_clone(*args, **kw):
        args = [str(bare) if a == "https://github.com/acme/shop.git" else a for a in args]
        return await real_run(*args, **kw)

    monkeypatch.setattr(acceptor.shell, "run", local_clone)
    monkeypatch.setattr(acceptor, "ClaudeRunner", FakeRunner)
    FakeRunner.calls, FakeRunner.shot = [], True
    FakeRunner.result = ClaudeResult(
        ok=True, summary="", data={"verdict": "accepted", "summary": "Прошёл план, всё работает"}
    )
    monkeypatch.setattr(acceptor.notify, "accepted", AsyncMock())
    return WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path / "work")), session_factory=session_factory)


async def add(session_factory, **kw) -> Task:
    async with session_factory() as s:
        t = Task(
            **{
                "title": "Откаты метрик",
                "description": "хочу видеть все откаты",
                "project_id": "shop",
                "repo": "acme/shop",
                "status": TaskStatus.ON_STAGE,
                **kw,
            }
        )
        s.add(t)
        await s.commit()
        return t


async def reload(session_factory, task_id) -> Task:
    async with session_factory() as s:
        return await s.get(Task, task_id)


def checking(**extra) -> dict:
    return {
        "pm": True,
        "brief": "**Готово, когда** экран «Проблемы» в меню",
        "test_plan": ["Открой stage", "Нажми «Проблемы»"],
        "acceptance": {"state": "checking", "fixes": 0, "at": "2026-11-01T00:00:00+00:00", **extra},
    }


async def test_next_request_is_the_oldest_checking_main_task(ctx, session_factory, project) -> None:
    assert await acceptor.next_request(ctx) is None
    newer = await add(session_factory, metadata_={"acceptance": {"state": "checking", "at": "2026-11-02"}})
    older = await add(session_factory, metadata_={"acceptance": {"state": "checking", "at": "2026-11-01"}})
    await add(session_factory, metadata_={"acceptance": {"state": "accepted", "at": "2026-10-01"}})
    await add(session_factory, status=TaskStatus.CI, metadata_={"acceptance": {"state": "checking", "at": "2026"}})
    assert await acceptor.next_request(ctx) == older.id
    assert newer.id != older.id


async def test_accepted_calls_the_owner_with_the_pm_screenshots(ctx, session_factory, project) -> None:
    async with session_factory() as s:
        (await s.get(type(project), "shop")).principles = "- Меньше тапов"
        await s.commit()
    main = await add(session_factory, metadata_=checking())
    await add(session_factory, parent_id=main.id, created_by="feedback", description="кнопку выше\n\n---\nFollow-up")
    await acceptor.accept(ctx, main.id)

    main = await reload(session_factory, main.id)
    assert main.metadata_["acceptance"]["state"] == "accepted"
    assert main.metadata_["acceptance"]["summary"] == "Прошёл план, всё работает"
    prompt = FakeRunner.calls[0]["prompt"]
    for part in ("https://stage.shop.test", "хочу видеть все откаты", "экран «Проблемы» в меню", "2. Нажми «Проблемы»"):
        assert part in prompt
    assert "кнопку выше" in prompt and "Меньше тапов" in prompt
    assert (FakeRunner.calls[0]["cwd"] / "app.txt").exists() is False  # cleaned up after the session
    assert "Edit" in FakeRunner.calls[0]["disallowed_tools"]
    async with session_factory() as s:
        shots = (await s.execute(select(TaskArtifact).where(TaskArtifact.task_id == main.id))).scalars().all()
    assert [(a.name, a.content) for a in shots] == [("PM: 01-home", b"\x89PNGhome")]
    acceptor.notify.accepted.assert_awaited_once()
    assert acceptor.notify.accepted.await_args.kwargs["screenshot"] == b"\x89PNGhome"


async def test_changes_become_one_follow_up_then_the_owner_gets_what_is_left(ctx, session_factory, project) -> None:
    FakeRunner.result = ClaudeResult(
        ok=True,
        summary="",
        data={
            "verdict": "changes",
            "summary": "Экран есть, но иконка врёт",
            "issues": [
                {"title": "Иконка ±", "description": "Показывает ±10%, а проверка только вверх: нужно +10%"},
                {"title": "Нет пустого состояния", "description": "Без откатов пустой экран: нужна подпись"},
            ],
        },
    )
    main = await add(session_factory, metadata_={**checking(), "verified_at": "2026-11-01T00:00:00+00:00"})
    await acceptor.accept(ctx, main.id)

    main = await reload(session_factory, main.id)
    state = main.metadata_["acceptance"]
    assert state["state"] == "fixing" and state["fixes"] == 1
    assert state["issues"] == ["Иконка ±", "Нет пустого состояния"]
    async with session_factory() as s:
        fix = (await s.execute(select(Task).where(Task.created_by == "pm"))).scalar_one()
    assert state["fix_task"] == {"id": str(fix.id), "ticket_number": fix.ticket_number}
    assert fix.parent_id == main.id and fix.status == TaskStatus.QUEUED and fix.depends_on == [main.id]
    assert "### Иконка ±\nПоказывает ±10%" in fix.description and "Нет пустого состояния" in fix.description
    assert "verified_at" not in main.metadata_
    acceptor.notify.accepted.assert_not_awaited()

    # Out of fix rounds: the owner gets it as it is, with the issues.
    async with session_factory() as s:
        t = await s.get(Task, main.id)
        t.metadata_ = {**t.metadata_, "acceptance": {**state, "state": "checking", "fixes": pm.MAX_FIXES}}
        await s.commit()
    await acceptor.accept(ctx, main.id)
    state = (await reload(session_factory, main.id)).metadata_["acceptance"]
    assert state["state"] == "concerns" and state["issues"] == ["Иконка ±", "Нет пустого состояния"]
    acceptor.notify.accepted.assert_awaited_once()
    assert "Иконка ±" in FakeRunner.calls[-1]["prompt"]  # it checks what it sent back last time
    async with session_factory() as s:
        assert len((await s.execute(select(Task).where(Task.created_by == "pm"))).scalars().all()) == 1


async def test_failed_check_calls_the_owner_and_rate_limit_waits(ctx, session_factory, project) -> None:
    from datetime import UTC, datetime, timedelta

    until = datetime.now(UTC) + timedelta(hours=1)
    FakeRunner.result = ClaudeResult(ok=False, summary="limit", rate_limited_until=until)
    main = await add(session_factory, metadata_=checking())
    await acceptor.accept(ctx, main.id)
    assert (await reload(session_factory, main.id)).metadata_["acceptance"]["state"] == "checking"
    assert ctx.paused_until == until
    acceptor.notify.accepted.assert_not_awaited()

    FakeRunner.result = ClaudeResult(ok=False, summary="browser crashed")
    await acceptor.accept(ctx, main.id)
    state = (await reload(session_factory, main.id)).metadata_["acceptance"]
    assert state["state"] == "failed" and "browser crashed" in state["summary"]
    acceptor.notify.accepted.assert_awaited_once()


def test_start_acceptance_counts_only_the_pm_own_fixes() -> None:
    meta = {"acceptance": {"state": "fixing", "fixes": 1}}
    pm.start_acceptance(meta, Task(created_by="pm"))
    assert meta["acceptance"]["state"] == "checking" and meta["acceptance"]["fixes"] == 1
    meta = {"acceptance": {"state": "accepted", "fixes": 2}}
    pm.start_acceptance(meta, Task(created_by="feedback"))
    assert meta["acceptance"]["fixes"] == 0
