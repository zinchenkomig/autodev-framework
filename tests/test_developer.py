"""develop(): real git against a local bare repo, fake Claude and GitHub."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from autodev.core.claude import ClaudeResult
from autodev.core.config import Settings
from autodev.core.models import Task, TaskStatus
from autodev.worker import developer as dev_mod
from autodev.worker.context import WorkerContext
from autodev.worker.developer import develop
from autodev.worker.workspace import Workspace, branch_name
from tests.fakes import FakeGitHub


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """Bare 'origin' with main and stage branches."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    git("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
    (seed / "README.md").write_text("hello\n")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "init", "--allow-empty", cwd=seed)
    git("add", "README.md", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "readme", cwd=seed)
    git("remote", "add", "origin", str(bare), cwd=seed)
    git("push", "-q", "origin", "main", "main:stage", cwd=seed)
    return bare


class FakeRunner:
    """Stands in for ClaudeRunner; `behaviour` edits the checkout."""

    calls: list[dict] = []
    behaviour = None
    result = ClaudeResult(ok=True, summary="Добавил файл", session_id="sess-1", num_turns=2)

    def __init__(self, cwd, **kw) -> None:
        self.cwd = Path(cwd)

    async def run(self, prompt, *, resume=None, on_log=None, should_cancel=None):
        FakeRunner.calls.append({"prompt": prompt, "resume": resume, "cwd": self.cwd})
        if FakeRunner.behaviour:
            FakeRunner.behaviour(self.cwd)
        return FakeRunner.result


def write_and_commit(cwd: Path) -> None:
    (cwd / "feature.txt").write_text("new feature\n")
    git("add", "-A", cwd=cwd)
    git("-c", "user.name=a", "-c", "user.email=a@a", "commit", "-qm", "feat: add feature", cwd=cwd)


@pytest.fixture
def wired(monkeypatch, remote, tmp_path, session_factory, project):
    FakeRunner.calls = []
    FakeRunner.behaviour = write_and_commit
    FakeRunner.result = ClaudeResult(ok=True, summary="Добавил файл", session_id="sess-1", num_turns=2)
    monkeypatch.setattr(dev_mod, "ClaudeRunner", FakeRunner)

    class LocalWorkspace(Workspace):
        def __init__(self, root, task_id, repo, env):
            super().__init__(root, task_id, repo, env)
            self.url = str(remote)

    monkeypatch.setattr(dev_mod, "Workspace", LocalWorkspace)
    gh = FakeGitHub()
    ctx = WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path / "work")), session_factory=session_factory)
    monkeypatch.setattr(ctx, "github", lambda: gh)
    monkeypatch.setattr(dev_mod.notify, "failed", AsyncMock())
    monkeypatch.setattr(dev_mod.notify, "blocked", AsyncMock())
    return ctx, gh, remote


async def new_task(session_factory, **kw) -> Task:
    t = Task(
        title="Add feature", project_id="shop", repo="acme/shop", status=TaskStatus.IN_PROGRESS, metadata_={}, **kw
    )
    async with session_factory() as s:
        s.add(t)
        await s.commit()
        await s.refresh(t)
    return t


async def reload(session_factory, task_id) -> Task:
    async with session_factory() as s:
        return await s.get(Task, task_id)


def test_branch_name() -> None:
    assert branch_name(12, "Добавь поиск: users & teams!") == "autodev/12-users-teams"
    assert branch_name(13, "Добавь поиск") == "autodev/13"
    assert branch_name(3, "Add search to Users page") == "autodev/3-add-search-to-users-page"


async def test_first_round_pushes_and_opens_pr(wired, session_factory) -> None:
    ctx, gh, remote = wired
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")

    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.CI, t.error
    assert t.branch == branch_name(t.ticket_number, "Add feature")
    assert t.pr_number == 1 and t.session_id == "sess-1" and t.summary == "Добавил файл"
    assert "feature.txt" in git("ls-tree", "-r", "--name-only", t.branch, cwd=remote)
    assert gh.prs[1]["base_ref"] == "stage" and "Добавил файл" in gh.prs[1]["body"]
    assert "Add feature" in FakeRunner.calls[0]["prompt"] and FakeRunner.calls[0]["resume"] is None
    assert not Path(FakeRunner.calls[0]["cwd"]).exists()  # workspace cleaned up


async def test_test_plan_is_stored_and_put_into_pr(wired, session_factory) -> None:
    ctx, gh, _ = wired
    FakeRunner.result = ClaudeResult(
        ok=True,
        summary="Добавил поиск",
        session_id="sess-1",
        data={"test_plan": ["Открой /users", " ", "Введи «ann» — останется Ann"], "check_paths": ["/users"]},
    )
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")

    t = await reload(session_factory, t.id)
    assert t.metadata_["test_plan"] == ["Открой /users", "Введи «ann» — останется Ann"]
    assert t.metadata_["check_paths"] == ["/users"]
    assert "### Как проверить на stage\n1. Открой /users\n2. Введи «ann»" in gh.prs[1]["body"]


async def test_uncommitted_changes_are_committed(wired, session_factory) -> None:
    ctx, gh, remote = wired

    def leave_files(cwd: Path) -> None:
        (cwd / "loose.txt").write_text("x")
        (cwd / "__pycache__").mkdir()
        (cwd / "__pycache__" / "m.pyc").write_text("junk")

    FakeRunner.behaviour = leave_files
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.CI
    files = git("ls-tree", "-r", "--name-only", t.branch, cwd=remote)
    assert "loose.txt" in files and "__pycache__" not in files


async def test_no_changes_fails(wired, session_factory) -> None:
    ctx, gh, _ = wired
    FakeRunner.behaviour = None
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.FAILED and "without committing" in t.error
    assert not gh.prs


async def test_blocked_agent_fails_with_reason(wired, session_factory) -> None:
    ctx, gh, _ = wired
    FakeRunner.behaviour = None
    FakeRunner.result = ClaudeResult(ok=False, blocked=True, summary="Нужен доступ к API ключу")
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.FAILED and "API ключу" in t.error
    dev_mod.notify.blocked.assert_awaited()


async def test_rate_limit_requeues_and_pauses(wired, session_factory) -> None:
    from datetime import UTC, datetime, timedelta

    ctx, gh, _ = wired
    until = datetime.now(UTC) + timedelta(hours=2)
    FakeRunner.behaviour = None
    FakeRunner.result = ClaudeResult(ok=False, summary="limit", rate_limited_until=until)
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")
    assert (await reload(session_factory, t.id)).status == TaskStatus.QUEUED
    assert ctx.paused_until == until and ctx.paused()


async def test_fix_round_resumes_session_on_same_branch(wired, session_factory) -> None:
    ctx, gh, remote = wired
    t = await new_task(session_factory)
    await develop(ctx, t.id, "developer-1")
    first = await reload(session_factory, t.id)

    async with session_factory() as s:
        task = await s.get(Task, t.id)
        task.status = TaskStatus.IN_PROGRESS
        task.metadata_ = {"fix": {"kind": "ci", "details": "test_x failed"}}
        await s.commit()

    def fix(cwd: Path) -> None:
        (cwd / "feature.txt").write_text("fixed\n")
        git("-c", "user.name=a", "-c", "user.email=a@a", "commit", "-qam", "fix: tests", cwd=cwd)

    FakeRunner.behaviour = fix
    await develop(ctx, t.id, "developer-1")
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.CI and t.pr_number == first.pr_number and len(gh.prs) == 1
    assert FakeRunner.calls[-1]["resume"] == "sess-1"
    assert "test_x failed" in FakeRunner.calls[-1]["prompt"]
    assert "fix" not in t.metadata_
    assert git("show", f"{t.branch}:feature.txt", cwd=remote) == "fixed\n"


async def test_cancelled_while_running_keeps_cancelled(wired, session_factory, monkeypatch) -> None:
    ctx, gh, _ = wired
    t = await new_task(session_factory)
    original_run = FakeRunner.run

    async def run_then_cancel(self, prompt, **kw):
        result = await original_run(self, prompt, **kw)
        async with session_factory() as s:  # owner pressed Cancel meanwhile
            (await s.get(Task, t.id)).status = TaskStatus.CANCELLED
            await s.commit()
        return result

    monkeypatch.setattr(FakeRunner, "run", run_then_cancel)
    await develop(ctx, t.id, "developer-1")
    assert (await reload(session_factory, t.id)).status == TaskStatus.CANCELLED
