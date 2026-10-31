"""Delivery: CI → merge → stage, fix rounds, releases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from autodev.core.config import Settings
from autodev.core.models import Release, ReleaseStatus, Task, TaskStatus
from autodev.worker import delivery as delivery_mod
from autodev.worker import qa
from autodev.worker.context import WorkerContext
from autodev.worker.delivery import Delivery, advance_release, extract_sha, summarize_checks
from tests.fakes import FakeGitHub, run


@pytest.fixture(autouse=True)
def stub_qa(monkeypatch):
    """Stage QA passes with one screenshot unless a test overrides it."""
    result = qa.QAResult(pages=[qa.PageResult(url="https://stage.shop.test/", status=200, screenshot=b"\x89PNGfake")])
    check = AsyncMock(return_value=result)
    monkeypatch.setattr(delivery_mod.qa, "check_stage", check)
    return check


@pytest.fixture(autouse=True)
def no_notifications(monkeypatch):
    calls = AsyncMock()
    for name in ("on_stage", "failed", "released", "release_failed"):
        monkeypatch.setattr(delivery_mod.notify, name, getattr(calls, name))
    return calls


def ctx(session_factory, **settings) -> WorkerContext:
    return WorkerContext(settings=Settings(**settings), session_factory=session_factory)


async def make_task(session_factory, **kw) -> Task:
    defaults = dict(
        title="Add search",
        project_id="shop",
        repo="acme/shop",
        status=TaskStatus.CI,
        pr_number=1,
        pr_url="https://github.com/acme/shop/pull/1",
        metadata_={},
        status_changed_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    defaults.update(kw)
    t = Task(**defaults)
    async with session_factory() as s:
        s.add(t)
        await s.commit()
    async with session_factory() as s:
        return await s.get(Task, t.id)


async def reload(session_factory, task_id) -> Task:
    async with session_factory() as s:
        return await s.get(Task, task_id)


def test_summarize_checks() -> None:
    assert summarize_checks([])[0] == "none"
    assert summarize_checks([run("a"), run("b", status="in_progress", conclusion=None)])[0] == "pending"
    state, failed = summarize_checks([run("a"), run("b", conclusion="failure")])
    assert state == "failed" and failed[0]["name"] == "b"
    # a re-run that passed supersedes the earlier failure
    rerun = [run("b", conclusion="failure", started="2026-01-01T00:00:00Z"), run("b", started="2026-01-01T01:00:00Z")]
    assert summarize_checks(rerun)[0] == "passed"
    assert summarize_checks([run("a", conclusion="skipped"), run("c", conclusion="cancelled")])[0] == "passed"


def test_extract_sha() -> None:
    assert extract_sha('{"sha": "ABCDEF1234567"}') == "abcdef1234567"
    assert extract_sha("deadbeef\n") == "deadbeef"
    assert extract_sha("<html>nothing</html>") is None


async def test_green_ci_merges_and_moves_to_deploying(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, head_sha="h1")
    gh.check_runs["h1"] = [run("test"), run("lint")]
    t = await make_task(session_factory)
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    t = await reload(session_factory, t.id)
    assert gh.merged == [(1, "squash")]
    assert t.status == TaskStatus.DEPLOYING and t.merge_sha == "merge1"
    assert t.metadata_["full_diff_pending"]  # the task's one-diff view gets rebuilt


async def test_pending_ci_waits(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, head_sha="h1")
    gh.check_runs["h1"] = [run("test", status="in_progress", conclusion=None)]
    t = await make_task(session_factory)
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.CI and not gh.merged


async def test_no_checks_waits_for_grace_period(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1)
    t = await make_task(session_factory, status_changed_at=datetime.now(UTC))
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    assert not gh.merged
    t = await make_task(session_factory, title="older", status_changed_at=datetime.now(UTC) - timedelta(hours=1))
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    assert gh.merged


async def test_red_ci_schedules_fix_then_gives_up(session_factory, project, no_notifications) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, head_sha="h1")
    gh.check_runs["h1"] = [run("test", conclusion="failure")]
    t = await make_task(session_factory)
    d = Delivery(ctx(session_factory, AUTODEV_MAX_FIX_ATTEMPTS=1))
    await d.check_pr(gh, t)
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.QUEUED and t.attempts == 1
    assert t.metadata_["fix"]["kind"] == "ci" and "test" in t.metadata_["fix"]["details"]

    async with session_factory() as s:  # developer pushed a fix
        (await s.get(Task, t.id)).status = TaskStatus.CI
        await s.commit()
    await d.check_pr(gh, await reload(session_factory, t.id))
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.FAILED and "Gave up" in t.error
    no_notifications.failed.assert_awaited()


async def test_conflict_schedules_conflict_fix(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, mergeable_state="dirty", mergeable=False)
    t = await make_task(session_factory)
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.QUEUED and t.metadata_["fix"]["kind"] == "conflict"


async def test_merge_refused_is_logged_once_and_retried(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, head_sha="h1")
    gh.check_runs["h1"] = [run("test")]
    gh.merge_error = 405
    t = await make_task(session_factory)
    d = Delivery(ctx(session_factory))
    await d.check_pr(gh, t)
    await d.check_pr(gh, await reload(session_factory, t.id))
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.CI and "405" in t.metadata_["merge_blocked"]


async def test_closed_pr_fails(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, state="closed")
    t = await make_task(session_factory)
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.FAILED


async def test_merged_outside_moves_on(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, merged=True, state="closed", merge_commit_sha="m9")
    t = await make_task(session_factory)
    await Delivery(ctx(session_factory)).check_pr(gh, t)
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.DEPLOYING and t.merge_sha == "m9"


async def test_deploy_via_own_workflows(session_factory, project, no_notifications) -> None:
    gh = FakeGitHub()
    gh.workflow_runs = [{"head_sha": "m1", "status": "completed", "conclusion": "success"}]
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory)).check_deploy(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.ON_STAGE
    no_notifications.on_stage.assert_awaited()


async def test_deploy_via_newer_commit(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.workflow_runs = [
        {"head_sha": "m2", "status": "completed", "conclusion": "success"},
        {"head_sha": "m1", "status": "completed", "conclusion": "cancelled"},
    ]
    gh.ancestry.add(("m2", "m1"))
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory)).check_deploy(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.ON_STAGE


async def test_deploy_workflow_failure_fails_task(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.workflow_runs = [{"head_sha": "m1", "status": "completed", "conclusion": "failure"}]
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory)).check_deploy(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.FAILED


async def test_later_successful_deploy_makes_up_for_failed_one(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.workflow_runs = [
        {"head_sha": "m2", "status": "completed", "conclusion": "success"},
        {"head_sha": "m1", "status": "completed", "conclusion": "failure"},
    ]
    gh.ancestry.add(("m2", "m1"))
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory)).check_deploy(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.ON_STAGE


async def test_deploy_timeout(session_factory, project) -> None:
    gh = FakeGitHub()
    gh.workflow_runs = [{"head_sha": "m1", "status": "in_progress", "conclusion": None}]
    t = await make_task(
        session_factory,
        status=TaskStatus.DEPLOYING,
        merge_sha="m1",
        status_changed_at=datetime.now(UTC) - timedelta(hours=2),
    )
    await Delivery(ctx(session_factory)).check_deploy(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.FAILED


async def test_deploy_via_version_url(session_factory, monkeypatch) -> None:
    from tests.conftest import make_project

    async with session_factory() as s:
        s.add(make_project(repos=[{"name": "acme/shop", "version_url": "https://stage/version"}]))
        await s.commit()
    gh = FakeGitHub()
    gh.ancestry.add(("abc1234", "m1"))
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    d = Delivery(ctx(session_factory))
    monkeypatch.setattr(d, "_deployed_sha", AsyncMock(return_value="abc1234"))
    await d.check_deploy(gh, t)
    assert (await reload(session_factory, t.id)).status == TaskStatus.ON_STAGE


async def test_release_merges_with_merge_commit_and_releases_tasks(session_factory, project, no_notifications) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=7, head_sha="r1")
    gh.check_runs["r1"] = [run("test")]
    t = await make_task(session_factory, status=TaskStatus.ON_STAGE)
    rel = Release(
        project_id="shop",
        version="2026.01.01-1",
        tasks=[t.id],
        release_prs=[{"repo": "acme/shop", "pr_number": 7, "pr_url": "u", "merged": False}],
    )
    async with session_factory() as s:
        s.add(rel)
        await s.commit()
    await advance_release(ctx(session_factory), gh, rel.id)
    assert gh.merged == [(7, "merge")]
    async with session_factory() as s:
        assert (await s.get(Release, rel.id)).status == ReleaseStatus.DEPLOYED
    assert (await reload(session_factory, t.id)).status == TaskStatus.RELEASED
    no_notifications.released.assert_awaited()


async def test_release_fails_on_red_checks(session_factory, project, no_notifications) -> None:
    gh = FakeGitHub()
    gh.add_pr(number=7, head_sha="r1")
    gh.check_runs["r1"] = [run("test", conclusion="failure")]
    rel = Release(
        project_id="shop", version="v", tasks=[], release_prs=[{"repo": "acme/shop", "pr_number": 7, "pr_url": "u"}]
    )
    async with session_factory() as s:
        s.add(rel)
        await s.commit()
    await advance_release(ctx(session_factory), gh, rel.id)
    async with session_factory() as s:
        r = await s.get(Release, rel.id)
        assert r.status == ReleaseStatus.FAILED and "test" in r.error
    no_notifications.release_failed.assert_awaited()


async def test_on_stage_runs_qa_saves_screenshot_and_notifies(
    session_factory, project, stub_qa, no_notifications
) -> None:
    from sqlalchemy import select

    from autodev.core.models import TaskArtifact

    t = await make_task(
        session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1", metadata_={"check_paths": ["/users"]}
    )
    await Delivery(ctx(session_factory)).on_stage(t, "test")
    urls = stub_qa.await_args.args[0]
    assert urls[0] == "https://stage.shop.test/users"
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.ON_STAGE and t.metadata_["qa"]["ok"] is True
    async with session_factory() as s:
        shots = (await s.execute(select(TaskArtifact).where(TaskArtifact.task_id == t.id))).scalars().all()
    assert [a.content for a in shots] == [b"\x89PNGfake"]
    assert no_notifications.on_stage.await_args.kwargs["screenshot"] == b"\x89PNGfake"


async def test_failed_qa_queues_one_fix_task(session_factory, project, stub_qa) -> None:
    from sqlalchemy import select

    stub_qa.return_value = qa.QAResult(
        pages=[qa.PageResult(url="https://stage.shop.test/", status=500, problems=["HTTP 500"])]
    )
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory)).on_stage(t, "test")
    async with session_factory() as s:
        fixes = (await s.execute(select(Task).where(Task.created_by == "qa"))).scalars().all()
    assert len(fixes) == 1 and "HTTP 500" in fixes[0].description and fixes[0].depends_on == [t.id]
    assert fixes[0].parent_id == t.id
    assert (await reload(session_factory, t.id)).metadata_["qa"]["ok"] is False

    # a QA follow-up that is itself broken doesn't spawn another one
    fix = fixes[0]
    async with session_factory() as s:
        f = await s.get(Task, fix.id)
        f.status, f.merge_sha = TaskStatus.DEPLOYING, "m2"
        await s.commit()
    await Delivery(ctx(session_factory)).on_stage(await reload(session_factory, fix.id), "test")
    async with session_factory() as s:
        assert len((await s.execute(select(Task).where(Task.created_by == "qa"))).scalars().all()) == 1


async def test_follow_up_on_stage_updates_main_task_plan(session_factory, project, no_notifications) -> None:
    main = await make_task(
        session_factory,
        status=TaskStatus.ON_STAGE,
        metadata_={"test_plan": ["a"], "plan_checked": [0], "verified_at": "2026-10-17T00:00:00+00:00"},
    )
    child = await make_task(
        session_factory,
        status=TaskStatus.DEPLOYING,
        merge_sha="m2",
        parent_id=main.id,
        metadata_={"root_plan": {"base": ["a"], "plan": ["a", "b"]}},
    )
    await Delivery(ctx(session_factory)).on_stage(child, "test")

    main = await reload(session_factory, main.id)
    assert main.metadata_["test_plan"] == ["a", "b"]
    assert "plan_checked" not in main.metadata_ and "verified_at" not in main.metadata_
    assert main.metadata_["plan_earlier"] == [0]  # "a" was ticked on the previous version
    assert no_notifications.on_stage.await_args.kwargs["main"].id == main.id


async def test_no_stage_url_skips_qa(session_factory, stub_qa) -> None:
    from tests.conftest import make_project

    async with session_factory() as s:
        p = make_project()
        p.stage_url = None
        s.add(p)
        await s.commit()
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory)).on_stage(t, "test")
    stub_qa.assert_not_awaited()
    assert "qa" not in (await reload(session_factory, t.id)).metadata_


async def test_image_build_started_for_deployed_repos(session_factory, project, no_notifications) -> None:
    # Repos in the projects org get their image built by AutoDev after each merge
    # (push events don't reliably start workflows there).
    settings = {"AUTODEV_PROJECTS_ORG": "ACME", "AUTODEV_APPS_DOMAIN": "example.com"}
    gh = FakeGitHub()
    gh.add_pr(number=1, head_sha="h1")
    gh.check_runs["h1"] = [run("test")]
    t = await make_task(session_factory)
    await Delivery(ctx(session_factory, **settings)).check_pr(gh, t)
    assert gh.dispatched == [("acme/shop", "image.yml", "stage")]

    gh.add_pr(number=7, head_sha="r1")
    gh.check_runs["r1"] = [run("test")]
    rel = Release(project_id="shop", version="v1", tasks=[], release_prs=[{"repo": "acme/shop", "pr_number": 7}])
    async with session_factory() as s:
        s.add(rel)
        await s.commit()
    await advance_release(ctx(session_factory, **settings), gh, rel.id)
    assert gh.dispatched[-1] == ("acme/shop", "image.yml", "main")

    other = FakeGitHub()  # outside the org: nothing to build
    other.add_pr(number=1, head_sha="h1")
    other.check_runs["h1"] = [run("test")]
    await Delivery(ctx(session_factory, AUTODEV_PROJECTS_ORG="other", AUTODEV_APPS_DOMAIN="x")).check_pr(
        other, await make_task(session_factory)
    )
    assert not hasattr(other, "dispatched")


async def test_broken_stage_deploy_becomes_a_fix_task(session_factory, project, monkeypatch, no_notifications) -> None:
    settings = {"AUTODEV_PROJECTS_ORG": "acme", "AUTODEV_APPS_DOMAIN": "example.com"}
    async with session_factory() as s:
        p = await s.get(type(project), "shop")
        p.repos = [{"name": "acme/shop", "version_url": "https://shop.stage.example.com/version"}]
        await s.commit()
    monkeypatch.setattr(Delivery, "_deployed_sha", AsyncMock(return_value="old0"))
    failure = delivery_mod.cluster.DeployFailure(sha="m1", text="Миграции упали. Лог:\nboom")
    diagnose = AsyncMock(return_value=failure)
    monkeypatch.setattr(delivery_mod.cluster, "diagnose", diagnose)
    gh = FakeGitHub()
    gh.ancestry.add(("m1", "m1"))
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    d = Delivery(ctx(session_factory, **settings))

    await d.check_deploy(gh, await reload(session_factory, t.id))
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.DEPLOYING  # waits for the fix instead of failing
    async with session_factory() as s:
        from sqlalchemy import select

        fix = (await s.execute(select(Task).where(Task.created_by == "deploy"))).scalar_one()
    assert "boom" in fix.description and fix.depends_on == [t.id] and t.metadata_["deploy_fix"] == str(fix.id)

    # Past the deploy timeout the task keeps waiting while its fix is open, and is not diagnosed again.
    diagnose.reset_mock()
    await d.check_deploy(gh, await reload(session_factory, t.id))
    assert (await reload(session_factory, t.id)).status == TaskStatus.DEPLOYING and not diagnose.called

    # The fix reached stage: its commit contains the task's change, so the task is on stage too.
    gh.ancestry.add(("fix1", "m1"))
    Delivery._deployed_sha.return_value = "fix1"
    await d.check_deploy(gh, await reload(session_factory, t.id))
    assert (await reload(session_factory, t.id)).status == TaskStatus.ON_STAGE


async def test_failed_deploy_fix_does_not_spawn_another(
    session_factory, project, monkeypatch, no_notifications
) -> None:
    settings = {"AUTODEV_PROJECTS_ORG": "acme", "AUTODEV_APPS_DOMAIN": "example.com"}
    async with session_factory() as s:
        p = await s.get(type(project), "shop")
        p.repos = [{"name": "acme/shop", "version_url": "https://shop.stage.example.com/version"}]
        await s.commit()
    monkeypatch.setattr(Delivery, "_deployed_sha", AsyncMock(return_value=None))
    failure = delivery_mod.cluster.DeployFailure(sha="m1", text="still broken")
    monkeypatch.setattr(delivery_mod.cluster, "diagnose", AsyncMock(return_value=failure))
    gh = FakeGitHub()
    gh.ancestry.add(("m1", "m1"))
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1", created_by="deploy")
    await Delivery(ctx(session_factory, **settings)).check_deploy(gh, t)
    t = await reload(session_factory, t.id)
    assert t.status == TaskStatus.FAILED and t.error == "still broken"


async def test_failed_image_build_becomes_a_fix_task(session_factory, project, monkeypatch, no_notifications) -> None:
    settings = {"AUTODEV_PROJECTS_ORG": "acme", "AUTODEV_APPS_DOMAIN": "example.com"}
    async with session_factory() as s:
        p = await s.get(type(project), "shop")
        p.repos = [{"name": "acme/shop", "version_url": "https://shop.stage.example.com/version"}]
        await s.commit()
    monkeypatch.setattr(Delivery, "_deployed_sha", AsyncMock(return_value=None))
    monkeypatch.setattr(delivery_mod.cluster, "diagnose", AsyncMock(return_value=None))
    gh = FakeGitHub()
    gh.workflow_runs = [
        {"path": ".github/workflows/image.yml", "conclusion": "success", "head_sha": "old", "created_at": "1"},
        {
            "path": ".github/workflows/image.yml",
            "conclusion": "failure",
            "head_sha": "m1",
            "created_at": "2",
            "html_url": "https://github.com/acme/shop/actions/runs/9",
            "id": 9,
        },
        {"path": ".github/workflows/ci.yml", "conclusion": "success", "head_sha": "m1", "created_at": "3"},
    ]
    t = await make_task(session_factory, status=TaskStatus.DEPLOYING, merge_sha="m1")
    await Delivery(ctx(session_factory, **settings)).check_deploy(gh, t)
    async with session_factory() as s:
        from sqlalchemy import select

        fix = (await s.execute(select(Task).where(Task.created_by == "deploy"))).scalar_one()
    assert "actions/runs/9" in fix.description and "gh run view 9 --log-failed" in fix.description
