"""Triage of multi-repo tasks."""

from __future__ import annotations

from autodev.core.claude import ClaudeResult
from autodev.core.config import Settings
from autodev.core.models import Task, TaskStatus
from autodev.worker import triage as triage_mod
from autodev.worker.context import WorkerContext
from tests.conftest import make_project


class Runner:
    data: dict = {}

    def __init__(self, cwd, **kw) -> None:
        self.schema = kw["schema"]

    async def run(self, prompt, **kw):
        return ClaudeResult(ok=True, summary="", data=Runner.data)


async def test_split_into_dependent_tasks(session_factory, tmp_path, monkeypatch) -> None:
    project = make_project(repos=[{"name": "acme/api", "role": "backend"}, {"name": "acme/web", "role": "frontend"}])
    task = Task(title="Поиск по пользователям", project_id="shop", status=TaskStatus.IN_PROGRESS, metadata_={})
    async with session_factory() as s:
        s.add_all([project, task])
        await s.commit()
        await s.refresh(task)

    Runner.data = {
        "parts": [
            {"repo": "acme/api", "title": "API поиска", "description": "GET /users?q="},
            {"repo": "acme/web", "title": "Поле поиска", "description": "use GET /users?q="},
        ]
    }
    monkeypatch.setattr(triage_mod, "ClaudeRunner", Runner)
    ctx = WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path)), session_factory=session_factory)

    async def log(*a):
        return None

    updated = await triage_mod.triage(ctx, task, project, log)
    assert updated.repo == "acme/api" and "GET /users?q=" in updated.description

    async with session_factory() as s:
        from sqlalchemy import select

        child = (await s.execute(select(Task).where(Task.id != task.id))).scalar_one()
    assert child.repo == "acme/web" and child.depends_on == [task.id] and child.status == TaskStatus.QUEUED
    assert child.parent_id == task.id


def test_schema_limits_repos() -> None:
    project = make_project(repos=[{"name": "acme/api"}, {"name": "acme/web"}])
    enum = triage_mod.triage_schema(project)["properties"]["parts"]["items"]["properties"]["repo"]["enum"]
    assert enum == ["acme/api", "acme/web"]
