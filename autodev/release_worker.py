"""Release Manager Worker — forms releases based on story points.

Checks every 30 minutes. Collects tasks from ready_to_release,
sorts by priority + age, and forms releases within SP bounds.

Release sizing:
- MIN_SP: minimum story points to form a release (default 5)
- MAX_SP: soft upper limit (default 15)
- If a single task exceeds MAX_SP, it can still go in a release alone
- Tasks sorted by: priority (critical first), then created_at (oldest first)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from autodev.core.models import (
    Priority,
    Release,
    ReleaseStatus,
    Task,
    TaskStatus,
)

logger = logging.getLogger(__name__)

RELEASE_CHECK_INTERVAL = int(os.environ.get("RELEASE_CHECK_INTERVAL", "1800"))  # 30 min
MIN_RELEASE_SP = int(os.environ.get("MIN_RELEASE_SP", "10"))
MAX_RELEASE_SP = int(os.environ.get("MAX_RELEASE_SP", "20"))

# Priority ordering for sorting
PRIORITY_ORDER = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.NORMAL: 2,
    Priority.LOW: 3,
}


def select_tasks_for_release(tasks: list[Task]) -> list[Task]:
    """Select optimal set of tasks for a release.

    Strategy:
    - Sort by priority (critical first), then by created_at (oldest first)
    - Add tasks until we reach MIN_SP
    - Keep adding if we haven't hit MAX_SP (soft limit)
    - A single task can exceed MAX_SP (no task left behind)
    - Stop adding when next task would push us significantly over MAX_SP
    """
    # Sort: priority first, then age
    sorted_tasks = sorted(
        tasks,
        key=lambda t: (
            PRIORITY_ORDER.get(t.priority, 2),
            t.created_at or datetime.min,
        ),
    )

    selected = []
    total_sp = 0

    for task in sorted_tasks:
        sp = task.story_points or 1

        # Always include first task (handles single large task)
        if not selected:
            selected.append(task)
            total_sp += sp
            continue

        # Check if adding this task keeps us within soft limit
        if total_sp + sp <= MAX_RELEASE_SP:
            selected.append(task)
            total_sp += sp
        elif total_sp < MIN_RELEASE_SP:
            # Below minimum — keep adding even if we go over MAX
            selected.append(task)
            total_sp += sp
        else:
            # We're between MIN and MAX, and adding would go over MAX
            # Still add if it's only slightly over (within 50% margin)
            if total_sp + sp <= MAX_RELEASE_SP * 1.5:
                selected.append(task)
                total_sp += sp
            break

    return selected


async def check_and_create_release(session_factory: async_sessionmaker) -> dict | None:
    """Check for ready tasks and create a release if conditions are met."""

    async with session_factory() as session:
        # 1. Get all ready_to_release tasks
        result = await session.execute(
            select(Task).where(Task.status == TaskStatus.READY_TO_RELEASE).order_by(Task.created_at)
        )
        ready_tasks = list(result.scalars().all())

        if not ready_tasks:
            return None

        # 2. Calculate total SP
        total_sp = sum(t.story_points or 1 for t in ready_tasks)

        # Only release when we have enough SP (or manual trigger via API)
        if total_sp < MIN_RELEASE_SP:
            logger.info(f"Release Manager: {len(ready_tasks)} tasks ({total_sp}/{MIN_RELEASE_SP} SP). Waiting.")
            return None

        # 3. Select tasks for this release
        selected = select_tasks_for_release(ready_tasks)
        selected_sp = sum(t.story_points or 1 for t in selected)
        remaining = len(ready_tasks) - len(selected)

        logger.info(
            f"Release Manager: forming release with {len(selected)} tasks "
            f"({selected_sp} SP), {remaining} tasks remain for next release"
        )

        # 4. Generate version
        version = datetime.now(UTC).strftime("v%Y-%m-%d-%H%M")

        # 5. Generate release notes
        release_notes = f"# Release {version}\n\n"
        release_notes += f"**{len(selected)} задач ({selected_sp} SP)**\n\n"

        backend_tasks = [t for t in selected if "backend" in (t.repo or "")]
        frontend_tasks = [t for t in selected if "frontend" in (t.repo or "")]

        for label, group in [("Backend", backend_tasks), ("Frontend", frontend_tasks)]:
            if group:
                release_notes += f"### {label}\n"
                for t in group:
                    sp_badge = f"[{t.story_points}SP]" if t.story_points else ""
                    pr_link = f" ([PR]({t.pr_url}))" if t.pr_url else ""
                    release_notes += f"- {sp_badge} {t.title}{pr_link}\n"
                release_notes += "\n"

        # 6. Create release
        task_ids = [t.id for t in selected]
        release = Release(
            id=uuid4(),
            version=version,
            status=ReleaseStatus.DRAFT,
            tasks=task_ids,
            release_notes=release_notes,
            created_at=datetime.now(UTC),
        )
        session.add(release)
        await session.flush()

        # 7. Merge PRs into stage
        merge_results = []
        merged_count = 0
        failed_count = 0

        from autodev.core.github_ops import extract_pr_info, merge_pr

        for task in selected:
            if not task.pr_url:
                continue

            info = extract_pr_info(task.pr_url)
            if not info:
                continue

            repo, pr_number = info
            try:
                success = await merge_pr(repo, pr_number)
                if success:
                    merged_count += 1
                    logger.info(f"Merged PR #{pr_number} for '{task.title}'")
                    merge_results.append({"task": task.title, "pr": task.pr_url, "success": True})
                else:
                    failed_count += 1
                    logger.warning(f"Failed to merge PR #{pr_number} for '{task.title}' — likely conflict")
                    merge_results.append(
                        {
                            "task": task.title,
                            "pr": task.pr_url,
                            "success": False,
                            "reason": "merge_conflict",
                        }
                    )

                    # Remove from release, return to ready_to_release
                    task.status = TaskStatus.READY_TO_RELEASE
                    selected.remove(task)

                    # Create conflict resolution task for developer
                    conflict_task = Task(
                        id=uuid4(),
                        title=f"Resolve merge conflict: {task.title[:60]}",
                        description=(
                            f"PR #{pr_number} не удалось замержить в stage (конфликт).\n\n"
                            f"Оригинальная задача: {task.title}\n"
                            f"PR: {task.pr_url}\n"
                            f"Repo: {repo}\n\n"
                            f"Нужно обновить ветку из stage и разрешить конфликты."
                        ),
                        status=TaskStatus.QUEUED,
                        priority="high",
                        story_points=1,
                        task_type="hotfix",
                        repo=repo,
                        branch=task.branch,  # existing branch to reuse
                        pr_number=task.pr_number,
                        pr_url=task.pr_url,
                        created_by="conflict-resolution",
                    )
                    session.add(conflict_task)
                    logger.info(f"Created conflict resolution task for PR #{pr_number}")

            except Exception as e:
                failed_count += 1
                logger.error(f"Error merging PR #{pr_number}: {e}")
                merge_results.append({"task": task.title, "pr": task.pr_url, "success": False, "error": str(e)})

        # 7b. Create release PR (stage → main) for visibility
        release_pr_urls = {}
        try:
            from autodev.integrations.github import GitHubClient

            github_token = os.environ.get("GITHUB_TOKEN", "")
            if github_token:
                repos_in_release = set()
                for task in selected:
                    if task.repo:
                        repos_in_release.add(task.repo)

                for repo in repos_in_release:
                    full_repo = repo if "/" in repo else f"zinchenkomig/{repo}"
                    client = GitHubClient(token=github_token, default_repo=full_repo)
                    try:
                        pr_body = (
                            f"## Release {version}\n\n{release_notes}\n\n---\n*Created by AutoDev Release Manager*"
                        )
                        pr = await client.create_pr(
                            title=f"Release {version}",
                            body=pr_body,
                            head="stage",
                            base="main",
                        )
                        pr_url = pr.get("html_url", "")
                        pr_num = pr.get("number")
                        release_pr_urls[repo] = pr_url
                        logger.info(f"Created release PR #{pr_num} for {repo}: {pr_url}")
                    except Exception as e:
                        # PR may already exist if stage has diverged from main before
                        logger.warning(f"Failed to create release PR for {repo}: {e}")
        except Exception as e:
            logger.warning(f"Failed to create release PRs: {e}")

        # 8. Deploy to staging server
        logger.info("Deploying to staging server...")
        deploy_results = {}
        try:
            from autodev.deploy import deploy_staging

            # Determine which repos need deploying
            repos_to_deploy = set()
            for task in selected:
                if task.repo:
                    repos_to_deploy.add(task.repo)

            deploy_results = await deploy_staging(
                repos=list(repos_to_deploy) if repos_to_deploy else None,
                release_version=version,
            )
            deploy_success = all(r.get("success") for r in deploy_results.values())

            if deploy_success:
                logger.info(f"Staging deploy successful: {deploy_results}")
            else:
                logger.warning(f"Staging deploy partial failure: {deploy_results}")
        except Exception as e:
            logger.error(f"Staging deploy failed: {e}")
            deploy_results = {"error": str(e)}

        # 9. Update release status to staging
        release.status = ReleaseStatus.STAGING
        release.staging_deployed_at = datetime.now(UTC)

        # 10. Move selected tasks to staging
        for task in selected:
            task.status = TaskStatus.STAGING
            task.release_id = release.id

        await session.commit()

        logger.info(
            f"Release {version}: {len(selected)} tasks ({selected_sp} SP), {merged_count} merged, {failed_count} failed"
        )

        return {
            "version": version,
            "release_id": str(release.id),
            "task_count": len(selected),
            "total_sp": selected_sp,
            "tasks": [{"title": t.title, "pr_url": t.pr_url, "sp": t.story_points} for t in selected],
            "merged": merged_count,
            "failed": failed_count,
            "remaining": remaining,
            "deploy": deploy_results,
            "release_prs": release_pr_urls,
        }


async def notify_release(release_info: dict) -> None:
    """Notify user about new release via Telegram."""
    if not release_info:
        return

    try:
        from autodev.integrations.telegram_pm import get_telegram_bot

        bot = await get_telegram_bot()

        v = release_info["version"]
        tc = release_info["task_count"]
        sp = release_info["total_sp"]
        merged = release_info["merged"]
        failed = release_info["failed"]
        remaining = release_info["remaining"]

        text = f"🚀 <b>Release {v}</b>\n\n"
        text += f"<b>{tc} задач ({sp} SP)</b>\n"
        text += f"✅ {merged} PR замержено"
        if failed:
            text += f" | ⚠️ {failed} не замержено"
        text += "\n\n"

        for t in release_info["tasks"]:
            sp_str = f"[{t['sp']}SP] " if t.get("sp") else ""
            pr_link = f' <a href="{t["pr_url"]}">PR</a>' if t.get("pr_url") else ""
            text += f"• {sp_str}{t['title']}{pr_link}\n"

        if remaining:
            text += f"\n📦 {remaining} задач осталось в очереди на следующий релиз"

        deploy = release_info.get("deploy", {})
        if deploy:
            deploy_ok = all(r.get("success") for r in deploy.values() if isinstance(r, dict))
            if deploy_ok:
                text += "\n\n✅ Задеплоено на staging"
                text += "\nhttps://staging.alerter.zinchenkomig.com"
            else:
                text += "\n\n⚠️ Деплой на staging частично не удался"

        release_prs = release_info.get("release_prs", {})
        if release_prs:
            text += "\n\n🔗 <b>Release PRs (stage → main):</b>"
            for repo, pr_url in release_prs.items():
                repo_short = repo.split("/")[-1] if "/" in repo else repo
                text += f'\n• {repo_short}: <a href="{pr_url}">PR</a>'

        text += "\n\n📋 Посмотри staging и дай фидбек через /feedback"

        await bot.send_message(bot.owner_chat_id, text)
    except Exception as e:
        logger.warning(f"Release Manager: failed to notify: {e}")


async def release_worker_loop(session_factory: async_sessionmaker) -> None:
    """Endless loop: check for ready tasks and form releases."""
    import asyncio

    logger.info(
        f"Release Manager started — checking every {RELEASE_CHECK_INTERVAL}s, SP range {MIN_RELEASE_SP}-{MAX_RELEASE_SP}"
    )

    # Wait 5 minutes on startup
    await asyncio.sleep(300)

    while True:
        try:
            # Check for stuck autoreview tasks first
            await check_stuck_autoreview(session_factory)

            # Then check if we can form a release
            release_info = await check_and_create_release(session_factory)
            if release_info:
                await notify_release(release_info)
        except Exception:
            logger.exception("Release Manager: unhandled error")

        await asyncio.sleep(RELEASE_CHECK_INTERVAL)


async def check_stuck_autoreview(session_factory: async_sessionmaker) -> None:
    """Check for autoreview tasks with merge conflicts and handle them."""

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        return

    async with session_factory() as session:
        result = await session.execute(select(Task).where(Task.status == TaskStatus.AUTOREVIEW))
        tasks = result.scalars().all()

        for task in tasks:
            if not task.pr_url:
                continue

            # Check PR mergeable status
            try:
                # Extract repo and PR number from URL
                parts = task.pr_url.rstrip("/").split("/")
                pr_number = parts[-1]
                repo = f"{parts[-4]}/{parts[-3]}"

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                        headers={"Authorization": f"token {github_token}"},
                        timeout=10.0,
                    )
                    if resp.status_code != 200:
                        continue

                    pr_data = resp.json()
                    mergeable_state = pr_data.get("mergeable_state", "")

                    if mergeable_state == "dirty":
                        logger.warning(f"Task '{task.title}' has merge conflict — creating resolution task")

                        # Move back to ready_to_release
                        task.status = TaskStatus.READY_TO_RELEASE

                        # Create conflict resolution task
                        conflict_task = Task(
                            id=uuid4(),
                            title=f"Resolve conflict: {task.title[:60]}",
                            description=(
                                f"PR {task.pr_url} имеет конфликт с develop.\n\n"
                                f"Нужно обновить ветку из stage и разрешить конфликты."
                            ),
                            status=TaskStatus.QUEUED,
                            priority="high",
                            story_points=1,
                            task_type="hotfix",
                            repo=task.repo or repo,
                            branch=task.branch,
                            pr_number=task.pr_number,
                            pr_url=task.pr_url,
                            created_by="conflict-resolution",
                        )
                        session.add(conflict_task)

                    elif mergeable_state == "clean":
                        # CI might have passed but webhook missed it
                        # Check if checks passed
                        check_resp = await client.get(
                            f"https://api.github.com/repos/{repo}/commits/{pr_data['head']['sha']}/check-runs",
                            headers={"Authorization": f"token {github_token}"},
                            timeout=10.0,
                        )
                        if check_resp.status_code == 200:
                            checks = check_resp.json().get("check_runs", [])
                            all_passed = checks and all(c.get("conclusion") == "success" for c in checks)
                            if all_passed:
                                logger.info(f"Task '{task.title}' checks passed, promoting to ready_to_release")
                                task.status = TaskStatus.READY_TO_RELEASE

            except Exception as e:
                logger.warning(f"Error checking PR for task '{task.title}': {e}")

        await session.commit()
