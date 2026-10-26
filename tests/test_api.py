"""REST API."""

from __future__ import annotations

import uuid

import httpx
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
        "repos": [{"name": "acme/shop"}],
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


class FakeRepoGitHub:
    """GitHub that creates repos (default branch main) and records new branches."""

    def __init__(self, exists: bool = False) -> None:
        self.exists = exists
        self.created: list[tuple[str, bool]] = []
        self.refs: list[tuple[str, str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def create_repo(self, full_name, *, private=True, description=""):
        if self.exists:
            request = httpx.Request("POST", "https://api.github.com/user/repos")
            response = httpx.Response(422, text='{"errors":[{"message":"name already exists"}]}', request=request)
            raise httpx.HTTPStatusError("422", request=request, response=response)
        self.created.append((full_name, private))
        return {"full_name": full_name, "default_branch": "main"}

    async def get_branch_sha(self, branch, repo=None):
        return "init1"

    async def create_ref(self, ref, sha, repo=None):
        self.refs.append((repo, ref, sha))
        return {}

    async def put_file(self, path, content, message, branch, repo=None):
        self.files = [*getattr(self, "files", []), (repo, branch, path)]
        return "wf1"


async def test_create_project_in_deployed_org(client, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod
    from autodev.core.config import get_settings

    monkeypatch.setattr(get_settings(), "projects_org", "Apps-Org")
    monkeypatch.setattr(get_settings(), "apps_domain", "example.com")
    gh = FakeRepoGitHub()
    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: gh)
    body = {"id": "notes", "name": "Notes", "repos": [{"name": ""}], "new_repo": {"brief": "Заметки"}}
    r = await client.post("/api/projects/", json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["repos"] == [
        {"name": "Apps-Org/notes", "version_url": "https://notes.stage.example.com/version", "setup": None}
    ]
    assert p["stage_url"] == "https://notes.stage.example.com"
    # The image workflow is committed first, so both branches start with it.
    assert gh.files == [("Apps-Org/notes", "main", ".github/workflows/image.yml")]
    assert gh.refs == [("Apps-Org/notes", "refs/heads/stage", "wf1")]
    (task,) = (await client.get("/api/tasks/", params={"project_id": "notes"})).json()
    assert "deploy/values.yaml" in task["description"] and "/version" in task["description"]

    # An explicit owner/repo outside the org is created as is, without deploy wiring.
    other = {**body, "id": "blog", "repos": [{"name": "someone/blog"}]}
    p = (await client.post("/api/projects/", json=other)).json()
    assert p["repos"][0]["name"] == "someone/blog" and p["stage_url"] is None
    assert len(gh.files) == 1


async def test_create_project_from_scratch(client, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod

    gh = FakeRepoGitHub()
    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: gh)
    body = {
        "id": "notes",
        "name": "Notes",
        "repos": [{"name": "acme/notes"}],
        "new_repo": {"private": False, "brief": "Заметки с тегами и поиском"},
    }
    r = await client.post("/api/projects/", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["task_counts"] == {"queued": 1}
    assert gh.created == [("acme/notes", False)]
    assert gh.refs == [("acme/notes", "refs/heads/stage", "init1")]  # main already exists

    (task,) = (await client.get("/api/tasks/", params={"project_id": "notes"})).json()
    assert task["repo"] == "acme/notes" and task["status"] == "queued"
    assert task["description"].startswith("Заметки с тегами и поиском") and "CLAUDE.md" in task["description"]


async def test_create_project_from_scratch_without_brief(client, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod

    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: FakeRepoGitHub())
    body = {"id": "notes", "name": "Notes", "repos": [{"name": "acme/notes"}], "new_repo": {}}
    r = await client.post("/api/projects/", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["task_counts"] == {}


async def test_create_project_from_scratch_repo_exists(client, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod

    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: FakeRepoGitHub(exists=True))
    body = {"id": "notes", "name": "Notes", "repos": [{"name": "acme/notes"}], "new_repo": {}}
    r = await client.post("/api/projects/", json=body)
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert (await client.get("/api/projects/notes")).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"id": "Bad Slug", "name": "x", "repos": [{"name": "a/b"}]},
        {"id": "ok", "name": "x", "repos": []},
        {"id": "ok", "name": "x", "repos": [{"name": "no-owner"}]},
        {"id": "ok", "name": "x", "repos": [{"name": "a/b"}, {"name": "a/c"}]},  # one repo per project
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


async def test_telegram_webhook_requires_secret(client, session_factory) -> None:
    from autodev.core.models import Setting

    update = {"message": {"chat": {"id": 1}, "text": "hi"}}
    assert (await client.post("/api/webhooks/telegram", json=update)).status_code == 403  # no secret configured
    async with session_factory() as s:
        s.add_all([Setting(key="telegram_webhook_secret", value="s3cret"), Setting(key="telegram_bot_token", value="")])
        await s.commit()
    bad = {"X-Telegram-Bot-Api-Secret-Token": "nope"}
    assert (await client.post("/api/webhooks/telegram", json=update, headers=bad)).status_code == 403
    good = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}
    assert (await client.post("/api/webhooks/telegram", json=update, headers=good)).json() == {
        "status": "not_configured"
    }


async def test_status_reports_worker_liveness_and_slots(client, session_factory, project) -> None:
    from datetime import UTC, datetime, timedelta

    from autodev.core.models import Agent, Setting

    r = (await client.get("/api/status/")).json()
    assert r["worker_online"] is False and r["slots"] == [] and r["developers_enabled"] is True

    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    async with session_factory() as s:
        import uuid

        s.add_all(
            [
                Agent(id="delivery", role="delivery", last_run_at=datetime.now(UTC)),
                Agent(id="developer", role="developer", enabled=False),
                Agent(id="developer-1", role="developer", status="working", current_task_id=uuid.UUID(t["id"])),
                Setting(key="worker_paused_until", value=(datetime.now(UTC) + timedelta(hours=1)).isoformat()),
            ]
        )
        await s.commit()
    r = (await client.get("/api/status/")).json()
    assert r["worker_online"] is True and r["developers_enabled"] is False and r["paused_until"]
    assert r["slots"] == [
        {
            "id": "developer-1",
            "status": "working",
            "task_id": t["id"],
            "task_ticket": t["ticket_number"],
            "task_title": "x",
        }
    ]


async def test_telegram_settings_never_expose_secrets(client, session_factory) -> None:
    from autodev.core.models import Setting

    async with session_factory() as s:
        s.add_all(
            [Setting(key="telegram_bot_token", value="123:abc"), Setting(key="telegram_webhook_secret", value="s3cret")]
        )
        await s.commit()
    r = (await client.get("/api/settings/telegram")).json()
    assert "abc" not in r["bot_token"] and r["webhook_secret"] != "s3cret"

    # round-tripping the masked values must not overwrite the real ones
    r["owner_chat_id"] = "42"
    assert (await client.put("/api/settings/telegram", json=r)).status_code == 200
    async with session_factory() as s:
        assert (await s.get(Setting, "telegram_bot_token")).value == "123:abc"
        assert (await s.get(Setting, "telegram_webhook_secret")).value == "s3cret"
        assert (await s.get(Setting, "telegram_owner_chat_id")).value == "42"


async def test_toggle_developer_switch(client, session_factory) -> None:
    from autodev.core.models import Agent

    async with session_factory() as s:
        s.add(Agent(id="developer", role="developer"))
        await s.commit()
    assert (await client.post("/api/agents/developer/toggle")).json()["enabled"] is False
    assert (await client.post("/api/agents/developer/toggle")).json()["enabled"] is True


async def test_artifacts_endpoints(client, project, session_factory) -> None:
    import uuid

    from autodev.core.models import TaskArtifact

    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    other = (await client.post("/api/tasks/", json={"title": "y"})).json()
    async with session_factory() as s:
        a = TaskArtifact(task_id=uuid.UUID(t["id"]), kind="screenshot", name="https://stage/", content=b"\x89PNG")
        s.add(a)
        await s.commit()
    listed = (await client.get(f"/api/tasks/{t['id']}/artifacts")).json()
    assert [x["name"] for x in listed] == ["https://stage/"]
    r = await client.get(listed[0]["url"])
    assert r.status_code == 200 and r.content == b"\x89PNG" and r.headers["content-type"] == "image/png"
    assert (await client.get(f"/api/tasks/{other['id']}/artifacts/{a.id}")).status_code == 404


async def test_test_plan_checklist_and_verify(client, project, session_factory) -> None:
    t = (await client.post("/api/tasks/", json={"title": "x"})).json()
    plan = {"test_plan": ["Открой /users", "Найди Ann"]}
    assert (await client.post(f"/api/tasks/{t['id']}/verify", json={"verified": True})).status_code == 409

    await set_status(session_factory, t["id"], TaskStatus.ON_STAGE, metadata_=plan)
    r = (await client.post(f"/api/tasks/{t['id']}/plan/1", json={"done": True})).json()
    assert r["plan_checked"] == [1] and r["verified_at"] is None
    r = (await client.post(f"/api/tasks/{t['id']}/plan/0", json={"done": True})).json()
    assert r["plan_checked"] == [0, 1] and r["verified_at"]  # last step ticked → verified

    r = (await client.post(f"/api/tasks/{t['id']}/plan/0", json={"done": False})).json()
    assert r["plan_checked"] == [1] and r["verified_at"] is None
    assert (await client.post(f"/api/tasks/{t['id']}/plan/2", json={"done": True})).status_code == 409

    r = (await client.post(f"/api/tasks/{t['id']}/verify", json={"verified": True})).json()
    assert r["verified_at"] and r["plan_checked"] == [1]
    assert (await client.get(f"/api/tasks/{t['id']}")).json()["verified_at"] == r["verified_at"]
    r = (await client.post(f"/api/tasks/{t['id']}/verify", json={"verified": False})).json()
    assert r["verified_at"] is None


async def test_follow_up_is_checked_with_its_main_task(client, project, session_factory) -> None:
    from autodev.worker.store import Store

    main = (await client.post("/api/tasks/", json={"title": "Экран"})).json()
    plan = {"test_plan": ["Открой stage", "Нажми «Экран»"]}
    await set_status(session_factory, main["id"], TaskStatus.ON_STAGE, metadata_=plan)
    assert (await client.post(f"/api/tasks/{main['id']}/verify", json={"verified": True})).json()["verified_at"]

    # Feedback → a follow-up in the queue; the main task is no longer verified and can't be until it lands.
    child = (await client.post(f"/api/tasks/{main['id']}/feedback", json={"text": "ещё фильтр"})).json()
    got = (await client.get(f"/api/tasks/{main['id']}")).json()
    assert got["verified_at"] is None and [w["id"] for w in got["waiting_for"]] == [child["id"]]
    r = await client.post(f"/api/tasks/{main['id']}/verify", json={"verified": True})
    assert r.status_code == 409 and f"#{child['ticket_number']}" in r.json()["detail"]
    for step in (0, 1):
        r = (await client.post(f"/api/tasks/{main['id']}/plan/{step}", json={"done": True})).json()
    assert r["plan_checked"] == [0, 1] and r["verified_at"] is None  # all ticked, still waiting

    # The follow-up has no plan of its own; its agent proposed the main task's whole plan.
    proposal = {"root_plan": {"base": plan["test_plan"], "plan": ["Открой stage", "Нажми «Экран»", "Фильтр"]}}
    await set_status(session_factory, child["id"], TaskStatus.ON_STAGE, metadata_=proposal)
    got_child = (await client.get(f"/api/tasks/{child['id']}")).json()
    assert got_child["test_plan"] == [] and got_child["parent"]["id"] == main["id"]
    assert (await client.post(f"/api/tasks/{child['id']}/verify", json={"verified": True})).status_code == 409

    async with session_factory() as s:
        child_task = await s.get(Task, uuid.UUID(child["id"]))
    await Store(session_factory).adopt_child_plan(child_task)

    got = (await client.get(f"/api/tasks/{main['id']}")).json()
    assert got["test_plan"] == ["Открой stage", "Нажми «Экран»", "Фильтр"]
    assert got["plan_checked"] == [] and got["waiting_for"] == []  # one check of everything, from the start
    assert (await client.post(f"/api/tasks/{main['id']}/verify", json={"verified": True})).json()["verified_at"]
    assert (await client.get(f"/api/tasks/{child['id']}")).json()["verified_at"]  # shows the main task's mark


async def test_older_follow_up_plan_is_ignored(client, project, session_factory) -> None:
    """A follow-up from before one-plan-per-task still holds a plan: it's checked with the main task anyway."""
    main = (await client.post("/api/tasks/", json={"title": "Экран"})).json()
    await set_status(session_factory, main["id"], TaskStatus.ON_STAGE)
    child = (await client.post(f"/api/tasks/{main['id']}/feedback", json={"text": "ещё"})).json()
    await set_status(
        session_factory, child["id"], TaskStatus.ON_STAGE, metadata_={"test_plan": ["свой шаг"], "plan_checked": [0]}
    )
    got = (await client.get(f"/api/tasks/{child['id']}")).json()
    assert got["test_plan"] == [] and got["plan_checked"] == []
    assert (await client.post(f"/api/tasks/{child['id']}/plan/0", json={"done": True})).status_code == 409
    assert (await client.post(f"/api/tasks/{child['id']}/verify", json={"verified": True})).status_code == 409


async def test_plan_refresh_request(client, project, session_factory) -> None:
    main = (await client.post("/api/tasks/", json={"title": "Экран"})).json()
    assert (await client.post(f"/api/tasks/{main['id']}/plan/refresh")).status_code == 409  # not on stage yet

    await set_status(session_factory, main["id"], TaskStatus.ON_STAGE, metadata_={"test_plan": ["шаг"]})
    r = await client.post(f"/api/tasks/{main['id']}/plan/refresh")
    assert r.status_code == 200 and r.json()["plan_refreshing"] is True
    assert r.json()["test_plan"] == ["шаг"]  # the old plan stays until the new one is written
    assert (await client.post(f"/api/tasks/{main['id']}/plan/refresh")).status_code == 409  # already queued

    child = (await client.post(f"/api/tasks/{main['id']}/feedback", json={"text": "ещё"})).json()
    await set_status(session_factory, child["id"], TaskStatus.ON_STAGE)
    r = await client.post(f"/api/tasks/{child['id']}/plan/refresh")
    assert r.status_code == 409 and "основной" in r.json()["detail"]
    assert (await client.get(f"/api/tasks/{child['id']}")).json()["plan_refreshing"] is False


async def test_cross_origin_writes_are_rejected(client, project) -> None:
    # A project app on a sibling subdomain is same-site: its requests carry the session cookie.
    evil = {"origin": "https://notes.stage.example.com"}
    assert (await client.post("/api/tasks/", json={"title": "x"}, headers=evil)).status_code == 403
    assert (await client.get("/api/tasks/", headers=evil)).status_code == 200  # reads are guarded by CORS
    assert "access-control-allow-origin" not in (await client.get("/api/tasks/", headers=evil)).headers

    for ok in ({"origin": "http://test"}, {"origin": "http://localhost:3000"}, {}):
        assert (await client.post("/api/tasks/", json={"title": "x"}, headers=ok)).status_code == 201
    proxied = {"origin": "https://autodev.example.com", "x-forwarded-host": "autodev.example.com"}
    assert (await client.post("/api/tasks/", json={"title": "x"}, headers=proxied)).status_code == 201


async def test_cors_only_for_local_dev(client) -> None:
    r = await client.get("/health", headers={"origin": "http://localhost:3000", "cookie": "a=b"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    r = await client.get("/health", headers={"origin": "https://evil.example.com", "cookie": "a=b"})
    assert "access-control-allow-origin" not in r.headers
