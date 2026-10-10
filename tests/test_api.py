"""REST API."""

from __future__ import annotations

import pytest

from autodev.core.models import AgentLog, Task, TaskStatus
from tests.conftest import make_project
from tests.fakes import FakeGitHub


async def test_health(client) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_project_crud(client) -> None:
    body = {
        "id": "shop",
        "name": "Shop",
        "repos": [{"name": "acme/api", "role": "backend"}, {"name": "acme/web", "role": "frontend"}],
    }
    r = await client.post("/api/projects/", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["base_branch"] == "stage"
    assert (await client.post("/api/projects/", json=body)).status_code == 409

    body["stage_url"] = "https://stage.shop"
    r = await client.put("/api/projects/shop", json={k: v for k, v in body.items() if k != "id"})
    assert r.json()["stage_url"] == "https://stage.shop"
    assert [p["id"] for p in (await client.get("/api/projects/")).json()] == ["shop"]
    assert (await client.delete("/api/projects/shop")).status_code == 204


@pytest.mark.parametrize(
    "body",
    [
        {"id": "Bad Slug", "name": "x", "repos": [{"name": "a/b"}]},
        {"id": "ok", "name": "x", "repos": []},
        {"id": "ok", "name": "x", "repos": [{"name": "no-owner"}]},
    ],
)
async def test_project_validation(client, body) -> None:
    assert (await client.post("/api/projects/", json=body)).status_code == 422


async def test_create_task_single_project_single_repo(client, project) -> None:
    r = await client.post("/api/tasks/", json={"title": "Add search"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["project_id"] == "shop" and t["repo"] == "acme/shop" and t["status"] == "queued"
    assert t["ticket_number"] >= 1


async def test_create_task_multi_repo_leaves_repo_for_triage(client, session_factory) -> None:
    async with session_factory() as s:
        s.add(make_project(repos=[{"name": "acme/api", "role": "backend"}, {"name": "acme/web", "role": "frontend"}]))
        await s.commit()
    r = await client.post("/api/tasks/", json={"title": "Add search", "project_id": "shop"})
    assert r.json()["repo"] is None
    r = await client.post("/api/tasks/", json={"title": "Fix", "project_id": "shop", "repo": "frontend"})
    assert r.json()["repo"] == "acme/web"
    r = await client.post("/api/tasks/", json={"title": "Fix", "project_id": "shop", "repo": "mobile"})
    assert r.status_code == 422


async def test_create_task_needs_project_when_ambiguous(client, session_factory, project) -> None:
    async with session_factory() as s:
        s.add(make_project("blog"))
        await s.commit()
    assert (await client.post("/api/tasks/", json={"title": "x"})).status_code == 422
    assert (await client.post("/api/tasks/", json={"title": "x", "project_id": "nope"})).status_code == 422
    assert (await client.post("/api/tasks/", json={"title": "x", "repo": "acme/blog"})).json()["project_id"] == "blog"


async def set_status(session_factory, task_id: str, status: str, **fields) -> None:
    import uuid

    async with session_factory() as s:
        t = await s.get(Task, uuid.UUID(task_id))
        t.status = status
        for k, v in fields.items():
            setattr(t, k, v)
        await s.commit()


async def test_cancel_and_retry(client, project, session_factory) -> None:
    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    r = await client.post(f"/api/tasks/{t['id']}/cancel")
    assert r.json()["status"] == "cancelled"
    assert (await client.post(f"/api/tasks/{t['id']}/cancel")).status_code == 409

    await set_status(session_factory, t["id"], TaskStatus.FAILED, error="boom", attempts=3)
    r = (await client.post(f"/api/tasks/{t['id']}/retry")).json()
    assert r["status"] == "queued" and r["attempts"] == 0 and r["pending_fix"] == "retry" and r["error"] is None

    transitions = (await client.get(f"/api/tasks/{t['id']}/transitions")).json()
    assert [x["to_status"] for x in transitions] == ["cancelled", "queued"]


async def test_feedback_before_merge_reopens_pr(client, project, session_factory) -> None:
    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    await set_status(session_factory, t["id"], TaskStatus.CI, pr_number=5, branch="autodev/1-x")
    r = (await client.post(f"/api/tasks/{t['id']}/feedback", json={"text": "сделай кнопку синей"})).json()
    assert r["id"] == t["id"] and r["status"] == "queued" and r["pending_fix"] == "feedback"


async def test_feedback_after_merge_creates_follow_up(client, project, session_factory) -> None:
    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    await set_status(session_factory, t["id"], TaskStatus.ON_STAGE, pr_url="https://pr/1")
    r = (await client.post(f"/api/tasks/{t['id']}/feedback", json={"text": "ещё и экспорт"})).json()
    assert r["id"] != t["id"] and r["depends_on"] == [t["id"]] and "ещё и экспорт" in r["description"]


async def test_logs_incremental(client, project, session_factory) -> None:
    import uuid

    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    async with session_factory() as s:
        s.add(AgentLog(agent_id="developer-1", task_id=uuid.UUID(t["id"]), message="one"))
        await s.commit()
    logs = (await client.get(f"/api/tasks/{t['id']}/logs")).json()
    assert [entry["message"] for entry in logs] == ["one"]
    after = logs[-1]["created_at"]
    async with session_factory() as s:
        s.add(AgentLog(agent_id="developer-1", task_id=uuid.UUID(t["id"]), message="two"))
        await s.commit()
    newer = (await client.get(f"/api/tasks/{t['id']}/logs", params={"after": after})).json()
    assert [entry["message"] for entry in newer] == ["two"]


async def test_delete_rules(client, project, session_factory) -> None:
    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    await set_status(session_factory, t["id"], TaskStatus.IN_PROGRESS)
    assert (await client.delete(f"/api/tasks/{t['id']}")).status_code == 409
    await set_status(session_factory, t["id"], TaskStatus.FAILED)
    assert (await client.delete(f"/api/tasks/{t['id']}")).status_code == 204
    assert (await client.get(f"/api/tasks/{t['id']}")).status_code == 404


async def test_release_endpoint(client, project, session_factory, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod

    gh = FakeGitHub()
    gh.ahead_by["acme/shop"] = 2
    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: gh)
    t = (await client.post("/api/tasks/", json={"title": "Search"})).json()
    await set_status(session_factory, t["id"], TaskStatus.ON_STAGE)

    r = await client.post("/api/projects/shop/release")
    assert r.status_code == 201, r.text
    rel = r.json()
    assert rel["status"] == "pending" and rel["tasks"] == [t["id"]] and "Search" in rel["release_notes"]
    assert gh.prs[1]["head_ref"] == "stage" and gh.prs[1]["base_ref"] == "main"
    assert (await client.post("/api/projects/shop/release")).status_code == 409  # one at a time
    assert [x["id"] for x in (await client.get("/api/releases/", params={"project_id": "shop"})).json()] == [rel["id"]]


async def test_release_nothing_to_ship(client, project, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod

    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: FakeGitHub())
    assert (await client.post("/api/projects/shop/release")).status_code == 409
