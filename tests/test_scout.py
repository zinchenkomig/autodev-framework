"""The scout: when it runs, what it files, and the stage limit that stops it."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from autodev import pm, scout
from autodev.core.claude import ClaudeResult
from autodev.core.config import Settings
from autodev.core.models import Project, Task, TaskArtifact, TaskStatus
from autodev.worker import scout as worker_scout
from autodev.worker.context import WorkerContext
from autodev.worker.loop import Worker


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def finding(title="Кнопка не работает", **kw) -> dict:
    return {
        "title": title,
        "kind": "bug",
        "description": "На экране корзины кнопка ничего не делает. Должна оформлять заказ.",
        "evidence": "app.py:10, клик не вызывает запрос",
        **kw,
    }


class FakeRunner:
    calls: list[dict] = []
    result = ClaudeResult(ok=True, summary="", data={"summary": "Всё прошёл", "findings": []})
    shots_on_call = 1  # from which session on the agent has taken screenshots

    def __init__(self, cwd, **kw) -> None:
        self.cwd = Path(cwd)
        self.kw = kw

    async def run(self, prompt, *, resume=None, on_log=None, should_cancel=None):
        FakeRunner.calls.append({"prompt": prompt, "cwd": self.cwd, "resume": resume, **self.kw})
        if len(FakeRunner.calls) >= FakeRunner.shots_on_call:
            shots = Path(prompt.split("Screenshots directory: `")[1].split("`")[0])
            (shots / "01-cart.png").write_bytes(b"\x89PNGcart")
            (shots / "notes.png").write_text("not a png")
        return FakeRunner.result


def found(*items) -> None:
    FakeRunner.result = ClaudeResult(ok=True, summary="", data={"summary": "Прошёл корзину", "findings": list(items)})


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
    real_run = worker_scout.shell.run

    async def local_clone(*args, **kw):
        args = [str(bare) if a == "https://github.com/acme/shop.git" else a for a in args]
        return await real_run(*args, **kw)

    monkeypatch.setattr(worker_scout.shell, "run", local_clone)
    monkeypatch.setattr(worker_scout, "ClaudeRunner", FakeRunner)
    monkeypatch.setattr(worker_scout.notify, "scouted", AsyncMock())
    monkeypatch.setattr(worker_scout.notify, "proposals", AsyncMock())
    FakeRunner.calls, FakeRunner.shots_on_call = [], 1
    found()
    return WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path / "work")), session_factory=session_factory)


async def configure(session_factory, **fields) -> None:
    async with session_factory() as s:
        project = await s.get(Project, "shop")
        for key, value in fields.items():
            setattr(project, key, value)
        await s.commit()


async def add(session_factory, status=TaskStatus.ON_STAGE, **kw) -> Task:
    async with session_factory() as s:
        t = Task(**{"title": "Задача", "project_id": "shop", "repo": "acme/shop", "status": status, **kw})
        s.add(t)
        await s.commit()
        return t


async def tasks(session_factory) -> list[Task]:
    async with session_factory() as s:
        rows = await s.execute(select(Task).where(Task.created_by == scout.AUTHOR).order_by(Task.ticket_number))
        return list(rows.scalars())


async def run_state(session_factory) -> dict:
    async with session_factory() as s:
        return scout.last_run(await s.get(Project, "shop"))


def ago(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


# ---------------------------------------------------------------------------
# When it runs
# ---------------------------------------------------------------------------


async def test_off_by_default(ctx, project):
    assert await worker_scout.next_run(ctx) is None


@pytest.mark.parametrize("mode", [scout.PROPOSE, scout.AUTO])
async def test_idle_project_is_due(ctx, project, session_factory, mode):
    await configure(session_factory, scout=mode)
    assert await worker_scout.next_run(ctx) == "shop"


@pytest.mark.parametrize("status", [TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.CI, TaskStatus.DEPLOYING])
async def test_waits_while_work_or_decisions_are_open(ctx, project, session_factory, status):
    await configure(session_factory, scout=scout.AUTO)
    await add(session_factory, status=status)
    assert await worker_scout.next_run(ctx) is None


async def test_waits_for_the_pm_on_stage(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO)
    await add(session_factory, metadata_={pm.ACCEPTANCE: {"state": pm.CHECKING}})
    assert await worker_scout.next_run(ctx) is None


async def test_keeps_the_interval_between_runs(ctx, project, session_factory):
    await configure(
        session_factory, scout=scout.AUTO, scout_run={"state": scout.DONE, "at": ago(minutes=5), "found": 2}
    )
    assert await worker_scout.next_run(ctx) is None
    await configure(session_factory, scout_run={"state": scout.DONE, "at": ago(hours=2), "found": 2})
    assert await worker_scout.next_run(ctx) == "shop"


async def test_nothing_found_waits_longer(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO, scout_run={"state": scout.DONE, "at": ago(hours=2), "found": 0})
    assert await worker_scout.next_run(ctx) is None
    await configure(session_factory, scout_run={"state": scout.DONE, "at": ago(hours=25), "found": 0})
    assert await worker_scout.next_run(ctx) == "shop"


async def test_disabled_project_is_skipped(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO, enabled=False)
    assert await worker_scout.next_run(ctx) is None


async def test_the_owners_request_skips_idle_and_mode(ctx, project, session_factory):
    await configure(session_factory, scout_run={"state": scout.REQUESTED, "at": ago(seconds=1)})
    await add(session_factory, status=TaskStatus.IN_PROGRESS)
    assert await worker_scout.next_run(ctx) == "shop"


# ---------------------------------------------------------------------------
# The stage limit
# ---------------------------------------------------------------------------


async def test_stage_limit_stops_it_counting_follow_ups(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO, stage_limit=3)
    main = await add(session_factory)
    await add(session_factory)
    assert await worker_scout.next_run(ctx) == "shop"
    await add(session_factory, parent_id=main.id)  # a follow-up on stage takes room too
    assert await worker_scout.next_run(ctx) is None


async def test_release_makes_room(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO, stage_limit=1)
    task = await add(session_factory)
    assert await worker_scout.next_run(ctx) is None
    async with session_factory() as s:
        (await s.get(Task, task.id)).status = TaskStatus.RELEASED
        await s.commit()
    assert await worker_scout.next_run(ctx) == "shop"


async def test_its_failed_tasks_count_the_owners_dont(ctx, project, session_factory):
    await configure(session_factory, stage_limit=2)
    await add(session_factory, status=TaskStatus.FAILED)
    await add(session_factory, status=TaskStatus.FAILED, created_by=scout.AUTHOR)
    async with session_factory() as s:
        assert await scout.stage_load(s, "shop") == 1


async def test_never_goes_over_the_limit(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO, stage_limit=3)
    await add(session_factory)
    found(*(finding(f"Находка {i}") for i in range(5)))
    await worker_scout.run(ctx, "shop")
    assert "Report at most 2 findings." in FakeRunner.calls[0]["prompt"]
    assert len(await tasks(session_factory)) == 2


async def test_limit_filled_during_the_run_is_respected(ctx, project, session_factory, monkeypatch):
    await configure(session_factory, scout=scout.AUTO, stage_limit=2)
    found(finding("Раз"), finding("Два"))
    real = FakeRunner.run

    async def owner_adds_a_task(self, prompt, **kw):
        await add(session_factory, status=TaskStatus.QUEUED)
        return await real(self, prompt, **kw)

    monkeypatch.setattr(FakeRunner, "run", owner_adds_a_task)
    await worker_scout.run(ctx, "shop")
    assert [t.title for t in await tasks(session_factory)] == ["Раз"]


async def test_full_project_spends_no_session(ctx, project, session_factory):
    await configure(session_factory, stage_limit=1)
    await add(session_factory)
    await worker_scout.run(ctx, "shop")
    assert FakeRunner.calls == []
    assert (await run_state(session_factory))["state"] == scout.DONE


# ---------------------------------------------------------------------------
# What it files
# ---------------------------------------------------------------------------


async def test_propose_mode_waits_for_the_owner(ctx, project, session_factory):
    await configure(session_factory, scout=scout.PROPOSE)
    found(finding())
    await worker_scout.run(ctx, "shop")
    task = (await tasks(session_factory))[0]
    assert task.status == TaskStatus.PROPOSED
    assert task.priority == "low"
    assert task.source == "agent_created"
    assert "app.py:10" in task.description
    assert task.metadata_[scout.KEY] == {"kind": "bug", "evidence": "app.py:10, клик не вызывает запрос"}
    worker_scout.notify.scouted.assert_not_awaited()
    worker_scout.notify.proposals.assert_awaited_once()  # found less than asked: the batch is done
    state = await run_state(session_factory)
    assert (state["state"], state["found"], state["summary"]) == (scout.DONE, 1, "Прошёл корзину")
    assert state["collecting"] is False


async def test_auto_mode_goes_straight_to_development(ctx, project, session_factory):
    await configure(session_factory, scout=scout.AUTO)
    found(finding("Раз"), finding("Два", kind="ux"))
    await worker_scout.run(ctx, "shop")
    assert [t.status for t in await tasks(session_factory)] == [TaskStatus.QUEUED, TaskStatus.QUEUED]
    worker_scout.notify.scouted.assert_awaited_once()
    worker_scout.notify.proposals.assert_not_awaited()


def five(start: int = 0) -> None:
    found(*(finding(f"Находка {i}") for i in range(start, start + 5)))


async def test_propose_mode_collects_a_batch_up_to_the_limit(ctx, project, session_factory):
    await configure(session_factory, scout=scout.PROPOSE, stage_limit=12)
    five()
    await worker_scout.run(ctx, "shop")
    assert (await run_state(session_factory))["collecting"] is True
    worker_scout.notify.proposals.assert_not_awaited()
    # Proposals waiting don't stop it, and it goes on without the interval.
    assert await worker_scout.next_run(ctx) == "shop"

    five(5)
    await worker_scout.run(ctx, "shop")
    assert await worker_scout.next_run(ctx) == "shop"
    five(10)
    await worker_scout.run(ctx, "shop")
    assert "Report at most 2 findings." in FakeRunner.calls[-1]["prompt"]
    assert len(await tasks(session_factory)) == 12
    assert (await run_state(session_factory))["collecting"] is False
    batch = worker_scout.notify.proposals.await_args.args[1]
    assert len(batch) == 12
    assert await worker_scout.next_run(ctx) is None


async def test_next_batch_waits_until_the_owner_decided_on_all(ctx, project, session_factory):
    await configure(session_factory, scout=scout.PROPOSE)
    found(finding("Раз"), finding("Два"))
    await worker_scout.run(ctx, "shop")
    await configure(session_factory, scout_run={"state": scout.DONE, "at": ago(hours=2), "found": 2})
    first, second = await tasks(session_factory)
    async with session_factory() as s:
        (await s.get(Task, first.id)).status = TaskStatus.CANCELLED
        await s.commit()
    assert await worker_scout.next_run(ctx) is None  # one still waits
    async with session_factory() as s:
        (await s.get(Task, second.id)).status = TaskStatus.CANCELLED
        await s.commit()
    assert await worker_scout.next_run(ctx) == "shop"


async def test_a_failed_run_keeps_the_batch_after_the_interval(ctx, project, session_factory):
    await configure(session_factory, scout=scout.PROPOSE)
    five()
    await worker_scout.run(ctx, "shop")
    FakeRunner.result = ClaudeResult(ok=False, summary="сессия упала")
    await worker_scout.run(ctx, "shop")
    state = await run_state(session_factory)
    assert (state["state"], state["collecting"]) == (scout.FAILED, True)
    assert await worker_scout.next_run(ctx) is None
    await configure(session_factory, scout_run={**state, "at": ago(hours=2)})
    assert await worker_scout.next_run(ctx) == "shop"


async def test_the_button_is_one_run_not_a_batch(ctx, project, session_factory):
    five()
    await worker_scout.run(ctx, "shop")
    assert (await run_state(session_factory))["collecting"] is False
    worker_scout.notify.proposals.assert_awaited_once()


async def test_button_without_a_mode_proposes(ctx, project, session_factory):
    found(finding())
    await worker_scout.run(ctx, "shop")
    assert (await tasks(session_factory))[0].status == TaskStatus.PROPOSED


async def test_at_most_five_a_run(ctx, project, session_factory):
    await configure(session_factory, stage_limit=50)
    found(*(finding(f"Находка {i}") for i in range(9)))
    await worker_scout.run(ctx, "shop")
    assert len(await tasks(session_factory)) == worker_scout.MAX_FINDINGS


async def test_findings_without_evidence_are_dropped(ctx, project, session_factory):
    found(finding("Без доказательства", evidence=" "), finding("С доказательством"), "мусор")
    await worker_scout.run(ctx, "shop")
    assert [t.title for t in await tasks(session_factory)] == ["С доказательством"]


async def test_a_task_the_project_has_is_not_filed_again(ctx, project, session_factory):
    await add(session_factory, title="Кнопка не работает", status=TaskStatus.RELEASED)
    found(finding("  кнопка НЕ работает "), finding("Новое"), finding("Новое"))
    await worker_scout.run(ctx, "shop")
    assert [t.title for t in await tasks(session_factory)] == ["Новое"]


async def test_nothing_found_is_a_normal_run(ctx, project, session_factory):
    await worker_scout.run(ctx, "shop")
    state = await run_state(session_factory)
    assert (state["state"], state["found"]) == (scout.DONE, 0)
    worker_scout.notify.scouted.assert_not_awaited()


async def test_screenshots_stay_inside_and_are_png(ctx, project, session_factory):
    found(finding(screenshots=["01-cart.png", "notes.png", "../../seed/app.txt", "missing.png"]))
    await worker_scout.run(ctx, "shop")
    task = (await tasks(session_factory))[0]
    async with session_factory() as s:
        shots = list((await s.execute(select(TaskArtifact).where(TaskArtifact.task_id == task.id))).scalars())
    assert [a.name for a in shots] == ["Скаут: 01-cart"]


async def test_read_only_session_on_the_stage_branch(ctx, project, session_factory):
    await worker_scout.run(ctx, "shop")
    call = FakeRunner.calls[0]
    assert "Edit" in call["disallowed_tools"]
    assert call["schema"] is worker_scout.SCHEMA
    assert not (Path(ctx.settings.workdir) / "scout" / "shop").exists()


async def test_no_look_at_stage_sends_it_back_to_look(ctx, project, session_factory):
    FakeRunner.shots_on_call = 2
    FakeRunner.result = ClaudeResult(
        ok=True, summary="", session_id="s1", data={"summary": "Смотрел код", "findings": [finding()]}
    )
    await worker_scout.run(ctx, "shop")
    assert [c["resume"] for c in FakeRunner.calls] == [None, "s1"]
    assert "without a single screenshot" in FakeRunner.calls[1]["prompt"]
    assert len(await tasks(session_factory)) == 1


async def test_it_asks_to_look_only_once(ctx, project, session_factory):
    FakeRunner.shots_on_call = 99
    await worker_scout.run(ctx, "shop")
    assert len(FakeRunner.calls) == 2
    assert (await run_state(session_factory))["state"] == scout.DONE


async def test_screenshots_mean_it_looked(ctx, project, session_factory):
    await worker_scout.run(ctx, "shop")
    assert len(FakeRunner.calls) == 1


async def test_no_stage_nothing_to_look_at(ctx, project, session_factory):
    await configure(session_factory, stage_url=None)
    FakeRunner.shots_on_call = 99
    await worker_scout.run(ctx, "shop")
    assert len(FakeRunner.calls) == 1


async def test_prompt_knows_the_idea_tasks_rejections_and_principles(ctx, project, session_factory):
    await configure(session_factory, idea="Магазин одной кнопки", principles="- Меньше настроек")
    await add(session_factory, title="Уже на stage")
    await add(
        session_factory,
        title="Тёмная тема",
        status=TaskStatus.CANCELLED,
        created_by=scout.AUTHOR,
        metadata_={scout.KEY: {"kind": "ux", "rejected": "не нужна"}},
    )
    await worker_scout.run(ctx, "shop")
    prompt = FakeRunner.calls[0]["prompt"]
    assert "Уже на stage" in prompt
    assert "Тёмная тема — REJECTED by the owner: не нужна" in prompt
    assert "Меньше настроек" in prompt
    assert "Магазин одной кнопки" in prompt


@pytest.mark.parametrize("kind", ["feature", "simplify"])
async def test_it_may_add_what_the_idea_lacks_and_remove_what_it_doesnt_need(ctx, project, session_factory, kind):
    found(finding(kind=kind))
    await worker_scout.run(ctx, "shop")
    (task,) = await tasks(session_factory)
    assert task.metadata_[scout.KEY]["kind"] == kind


async def test_rejection_teaches_the_pm_too(project, session_factory):
    await add(
        session_factory,
        title="Тёмная тема",
        status=TaskStatus.CANCELLED,
        created_by=scout.AUTHOR,
        metadata_={scout.KEY: {"rejected": "не нужна"}},
    )
    await add(session_factory, title="Отменил сам", status=TaskStatus.CANCELLED, created_by=scout.AUTHOR)
    async with session_factory() as s:
        history = await pm.history(s, "shop")
    assert history == ["Rejected the scout's proposal «Тёмная тема»: не нужна"]


# ---------------------------------------------------------------------------
# When a run goes wrong
# ---------------------------------------------------------------------------


async def test_rate_limit_runs_again_after_the_reset(ctx, project, session_factory):
    until = datetime.now(UTC) + timedelta(hours=1)
    FakeRunner.result = ClaudeResult(ok=False, summary="limit", rate_limited_until=until)
    await worker_scout.run(ctx, "shop")
    assert ctx.paused_until == until
    assert (await run_state(session_factory))["state"] == scout.REQUESTED


async def test_failed_session_is_shown_and_files_nothing(ctx, project, session_factory):
    FakeRunner.result = ClaudeResult(ok=False, summary="сессия упала")
    await worker_scout.run(ctx, "shop")
    state = await run_state(session_factory)
    assert state["state"] == scout.FAILED
    assert "сессия упала" in state["summary"]
    assert await tasks(session_factory) == []


async def test_restart_resumes_a_cut_run(ctx, project, session_factory):
    await configure(session_factory, scout_run={"state": scout.RUNNING, "at": ago(minutes=1)})
    await worker_scout.recover(ctx)
    assert (await run_state(session_factory))["state"] == scout.REQUESTED


async def test_worker_never_claims_a_proposal(ctx, project, session_factory):
    await add(session_factory, status=TaskStatus.PROPOSED)
    assert await Worker(ctx).claim("developer-1") is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


async def test_project_settings_default_and_roundtrip(client, project):
    body = (await client.get("/api/projects/shop")).json()
    assert (body["scout"], body["stage_limit"], body["stage_load"], body["scout_run"]) == ("off", 10, 0, None)
    payload = {k: body[k] for k in ("name", "repos", "base_branch", "prod_branch", "stage_url", "max_parallel")}
    response = await client.put("/api/projects/shop", json={**payload, "scout": "auto", "stage_limit": 4})
    assert response.status_code == 200
    assert (response.json()["scout"], response.json()["stage_limit"]) == ("auto", 4)


@pytest.mark.parametrize("bad", [{"scout": "always"}, {"stage_limit": 0}])
async def test_project_settings_are_validated(client, project, bad):
    body = (await client.get("/api/projects/shop")).json()
    payload = {k: body[k] for k in ("name", "repos", "base_branch", "prod_branch")}
    assert (await client.put("/api/projects/shop", json={**payload, **bad})).status_code == 422


async def test_button_requests_a_run_once(client, project, session_factory):
    response = await client.post("/api/projects/shop/scout")
    assert response.status_code == 202
    assert response.json()["scout_run"]["state"] == scout.REQUESTED
    first = (await run_state(session_factory))["at"]
    assert (await client.post("/api/projects/shop/scout")).status_code == 202
    assert (await run_state(session_factory))["at"] == first


async def test_button_respects_the_limit(client, project, session_factory):
    await configure(session_factory, stage_limit=1)
    await add(session_factory)
    response = await client.post("/api/projects/shop/scout")
    assert response.status_code == 409
    assert "Лимит" in response.json()["detail"]


async def test_button_on_a_disabled_project(client, project, session_factory):
    await configure(session_factory, enabled=False)
    assert (await client.post("/api/projects/shop/scout")).status_code == 409


async def test_approve_sends_a_proposal_to_the_queue(client, project, session_factory):
    task = await add(session_factory, status=TaskStatus.PROPOSED, created_by=scout.AUTHOR)
    response = await client.post(f"/api/tasks/{task.id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


async def test_reject_keeps_the_reason(client, project, session_factory):
    task = await add(
        session_factory, status=TaskStatus.PROPOSED, created_by=scout.AUTHOR, metadata_={scout.KEY: {"kind": "ux"}}
    )
    response = await client.post(f"/api/tasks/{task.id}/reject", json={"reason": " не нужно "})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["scout"] == {"kind": "ux", "rejected": "не нужно"}


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_decisions_are_only_for_proposals(client, project, session_factory, action):
    task = await add(session_factory, status=TaskStatus.QUEUED)
    assert (await client.post(f"/api/tasks/{task.id}/{action}", json={})).status_code == 409


async def test_feedback_on_a_proposal_goes_into_its_description(client, project, session_factory):
    task = await add(session_factory, status=TaskStatus.PROPOSED, description="Находка")
    response = await client.post(f"/api/tasks/{task.id}/feedback", json={"text": "только на мобильных"})
    assert response.status_code == 200
    assert response.json()["description"] == "Находка\n\nтолько на мобильных"
    assert response.json()["status"] == "proposed"
