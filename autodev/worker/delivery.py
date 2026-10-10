"""Delivery: PR checks → merge into stage → wait for stage → on_stage.

Polls GitHub (no inbound webhooks needed). Each step is idempotent, so a
restart simply resumes from the current task status.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from autodev import notify
from autodev.core.models import Project, Release, ReleaseStatus, Task, TaskStatus
from autodev.integrations.github import GitHubClient
from autodev.worker.context import WorkerContext

logger = logging.getLogger(__name__)

FAILED_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
OK_CONCLUSIONS = {"success", "neutral", "skipped"}
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


def _age(since: datetime) -> float:
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return (datetime.now(UTC) - since).total_seconds()


def summarize_checks(runs: list[dict]) -> tuple[str, list[dict]]:
    """Return ("pending" | "failed" | "passed" | "none", failed_runs)."""
    if not runs:
        return "none", []
    # Only the latest run per check name matters (re-runs supersede).
    latest: dict[str, dict] = {}
    for run in runs:
        name = run.get("name", "")
        if name not in latest or (run.get("started_at") or "") > (latest[name].get("started_at") or ""):
            latest[name] = run
    failed = [
        r for r in latest.values() if r.get("status") == "completed" and r.get("conclusion") in FAILED_CONCLUSIONS
    ]
    if failed:
        return "failed", failed
    if any(r.get("status") != "completed" for r in latest.values()):
        return "pending", []
    return "passed", []


def extract_sha(body: str) -> str | None:
    """Pull a commit SHA out of a version endpoint response (JSON or text)."""
    match = _SHA.search(body.lower())
    return match.group(0) if match else None


class Delivery:
    def __init__(self, ctx: WorkerContext) -> None:
        self.ctx = ctx
        self.store = ctx.store

    async def tick(self) -> None:
        async with self.ctx.session_factory() as session:
            rows = await session.execute(
                select(Task).where(Task.status.in_([TaskStatus.CI, TaskStatus.DEPLOYING])).order_by(Task.created_at)
            )
            tasks = list(rows.scalars())
            releases = list(
                (await session.execute(select(Release).where(Release.status == ReleaseStatus.PENDING))).scalars()
            )
        async with self.ctx.github() as gh:
            for task in tasks:
                try:
                    if task.status == TaskStatus.CI:
                        await self.check_pr(gh, task)
                    else:
                        await self.check_deploy(gh, task)
                except httpx.HTTPError as exc:
                    logger.warning("delivery: task #%s: GitHub error %s", task.ticket_number, exc)
                except Exception:
                    logger.exception("delivery: task #%s", task.ticket_number)
            for release in releases:
                try:
                    await advance_release(self.ctx, gh, release.id)
                except Exception:
                    logger.exception("delivery: release %s", release.version)

    # -- CI → merge ---------------------------------------------------------

    async def check_pr(self, gh: GitHubClient, task: Task) -> None:
        if not task.pr_number or not task.repo:
            await self.fail(task, "Task is in CI but has no PR")
            return
        pr = await gh.get_pr(task.pr_number, repo=task.repo)

        if pr.get("merged"):
            await self.merged(task, pr.get("merge_commit_sha"), "merged outside AutoDev")
            return
        if pr.get("state") == "closed":
            await self.fail(task, f"PR {task.pr_url} was closed without merging")
            return
        if pr.get("mergeable_state") == "dirty":
            await self.schedule_fix(task, "conflict", "")
            return

        runs = await gh.get_check_runs(pr["head"]["sha"], repo=task.repo)
        state, failed = summarize_checks(runs)
        if state == "failed":
            details = "\n".join(
                f"- {r.get('name')}: {r.get('conclusion')} — {r.get('html_url') or r.get('details_url') or ''}"
                + (
                    f"\n  {(r.get('output') or {}).get('summary', '')[:500]}"
                    if (r.get("output") or {}).get("summary")
                    else ""
                )
                for r in failed
            )
            await self.schedule_fix(task, "ci", "Failing checks:\n" + details)
            return
        if state == "pending":
            if _age(task.status_changed_at) > self.ctx.settings.ci_timeout:
                await self.fail(
                    task, f"Checks on {task.pr_url} still running after {self.ctx.settings.ci_timeout // 60} min"
                )
            return
        if state == "none" and _age(task.status_changed_at) < self.ctx.settings.checks_grace_seconds:
            return  # give CI a moment to register its checks
        if pr.get("mergeable") is None:
            return  # GitHub still computing mergeability

        try:
            result = await gh.merge_pr(
                task.pr_number,
                merge_method="squash",
                repo=task.repo,
                commit_title=f"{task.title} (#{task.pr_number})",
            )
        except httpx.HTTPStatusError as exc:
            # 405: not mergeable (branch protection, required review…); 409: head moved.
            note = f"Merge refused ({exc.response.status_code}): {exc.response.text[:300]}"
            metadata = dict(task.metadata_ or {})
            if metadata.get("merge_blocked") != note:
                metadata["merge_blocked"] = note
                await self.store.update(task.id, metadata_=metadata)
                await self.store.log(task.id, f"⛔ {note}", level="warning")
            return
        await self.merged(
            task, result.get("sha"), f"merged into {task.project.base_branch if task.project else 'base'}"
        )

    async def merged(self, task: Task, sha: str | None, reason: str) -> None:
        metadata = dict(task.metadata_ or {})
        metadata.pop("merge_blocked", None)
        await self.store.transition(
            task.id,
            TaskStatus.DEPLOYING,
            reason=reason,
            by="delivery",
            only_from={TaskStatus.CI},
            merge_sha=sha,
            metadata_=metadata,
        )

    async def schedule_fix(self, task: Task, kind: str, details: str) -> None:
        if task.attempts >= self.ctx.settings.max_fix_attempts:
            await self.fail(task, f"Gave up after {task.attempts} fix rounds ({kind}).\n{details}")
            return
        metadata = dict(task.metadata_ or {})
        metadata["fix"] = {"kind": kind, "details": details}
        await self.store.transition(
            task.id,
            TaskStatus.QUEUED,
            reason=f"{kind} fix #{task.attempts + 1}",
            by="delivery",
            only_from={TaskStatus.CI},
            attempts=task.attempts + 1,
            metadata_=metadata,
        )

    async def fail(self, task: Task, reason: str) -> None:
        moved = await self.store.transition(
            task.id,
            TaskStatus.FAILED,
            reason=reason.splitlines()[0][:120],
            by="delivery",
            only_from={TaskStatus.CI, TaskStatus.DEPLOYING},
            error=reason,
        )
        if moved:
            await notify.failed(moved, reason)

    # -- merged → on stage --------------------------------------------------

    async def check_deploy(self, gh: GitHubClient, task: Task) -> None:
        project = task.project
        repo = project.repo(task.repo) if project else None
        if project is None or repo is None or not task.merge_sha:
            await self.on_stage(task, "no deploy tracking configured")
            return

        if repo.get("version_url"):
            deployed = await self._deployed_sha(repo["version_url"])
            if deployed and await gh.contains_commit(deployed, task.merge_sha, repo=task.repo):
                await self.on_stage(task, f"stage runs {deployed[:7]}")
                return
        else:
            verdict = await self._workflows_verdict(gh, task, project.base_branch)
            if verdict == "deployed":
                await self.on_stage(task, "stage workflows passed")
                return
            if verdict == "failed":
                await self.fail(task, f"Stage deploy workflow failed for {task.merge_sha[:7]} in {task.repo}")
                return
            if verdict == "no-workflows":
                await self.on_stage(task, "repo has no deploy workflows")
                return

        if _age(task.status_changed_at) > self.ctx.settings.deploy_timeout:
            await self.fail(task, f"Change did not reach stage within {self.ctx.settings.deploy_timeout // 60} min")

    async def _deployed_sha(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers={"Cache-Control": "no-cache"})
            return extract_sha(resp.text) if resp.status_code == 200 else None
        except httpx.HTTPError:
            return None

    async def _workflows_verdict(self, gh: GitHubClient, task: Task, base: str) -> str:
        """deployed / failed / pending / no-workflows, judged by push workflows on the base branch."""
        runs = await gh.list_workflow_runs(task.repo, branch=base, event="push", per_page=50)
        if not runs:
            return "no-workflows" if _age(task.status_changed_at) > 300 else "pending"

        by_sha: dict[str, list[dict]] = {}
        for run in runs:
            by_sha.setdefault(run["head_sha"], []).append(run)

        own = by_sha.get(task.merge_sha, [])
        if any(r.get("conclusion") in FAILED_CONCLUSIONS for r in own):
            return "failed"
        if own and all(r.get("status") == "completed" and r.get("conclusion") in OK_CONCLUSIONS for r in own):
            return "deployed"
        # A newer commit whose workflows all passed also carries our change
        # (deploy workflows often cancel superseded runs).
        for sha, group in by_sha.items():
            if sha == task.merge_sha:
                continue
            if all(r.get("status") == "completed" and r.get("conclusion") in OK_CONCLUSIONS for r in group):
                if await gh.contains_commit(sha, task.merge_sha, repo=task.repo):
                    return "deployed"
        return "pending"

    async def on_stage(self, task: Task, reason: str) -> None:
        moved = await self.store.transition(
            task.id, TaskStatus.ON_STAGE, reason=reason, by="delivery", only_from={TaskStatus.DEPLOYING}
        )
        if moved:
            await notify.on_stage(moved, moved.project)


# -- releases ---------------------------------------------------------------


async def advance_release(ctx: WorkerContext, gh: GitHubClient, release_id) -> None:
    """Merge a pending release's stage→prod PRs once their checks pass."""
    async with ctx.session_factory() as session:
        release = await session.get(Release, release_id, with_for_update=True)
        if release is None or release.status != ReleaseStatus.PENDING:
            return
        project = await session.get(Project, release.project_id) if release.project_id else None
        prs = [dict(p) for p in (release.release_prs or [])]

        problem = None
        for entry in prs:
            if entry.get("merged"):
                continue
            pr = await gh.get_pr(entry["pr_number"], repo=entry["repo"])
            if pr.get("merged"):
                entry["merged"] = True
                continue
            if pr.get("state") == "closed":
                problem = f"{entry['pr_url']} was closed"
                break
            state, failed = summarize_checks(await gh.get_check_runs(pr["head"]["sha"], repo=entry["repo"]))
            if state == "failed":
                problem = f"Checks failed on {entry['pr_url']}: " + ", ".join(r.get("name", "") for r in failed)
                break
            if state == "pending" or pr.get("mergeable") is None:
                continue
            try:
                # A merge commit, not squash: squashing stage into main would make
                # every later stage→main PR conflict.
                await gh.merge_pr(entry["pr_number"], merge_method="merge", repo=entry["repo"])
                entry["merged"] = True
            except httpx.HTTPStatusError as exc:
                problem = f"Merge of {entry['pr_url']} refused: {exc.response.text[:300]}"
                break

        release.release_prs = prs
        if problem:
            release.status = ReleaseStatus.FAILED
            release.error = problem
        elif all(p.get("merged") for p in prs):
            release.status = ReleaseStatus.DEPLOYED
            release.production_deployed_at = datetime.now(UTC)
        await session.commit()
        status, version = release.status, release.version
        task_ids = list(release.tasks or [])

    if project is None:
        return
    if status == ReleaseStatus.FAILED:
        await notify.release_failed(release, project, problem or "")
    elif status == ReleaseStatus.DEPLOYED:
        released = []
        for task_id in task_ids:
            moved = await ctx.store.transition(
                task_id,
                TaskStatus.RELEASED,
                reason=f"release {version}",
                by="release",
                only_from={TaskStatus.ON_STAGE},
                release_id=release.id,
            )
            if moved:
                released.append(moved)
        await notify.released(release, project, released)
