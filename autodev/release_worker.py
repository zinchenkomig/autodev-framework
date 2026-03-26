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
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select, case
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.models import (
    Release, ReleaseStatus, Task, TaskStatus, Priority,
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
    sorted_tasks = sorted(tasks, key=lambda t: (
        PRIORITY_ORDER.get(t.priority, 2),
        t.created_at or datetime.min,
    ))
    
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
            select(Task)
            .where(Task.status == TaskStatus.READY_TO_RELEASE)
            .order_by(Task.created_at)
        )
        ready_tasks = list(result.scalars().all())
        
        if not ready_tasks:
            return None
        
        # 2. Calculate total SP
        total_sp = sum(t.story_points or 1 for t in ready_tasks)
        
        # Only release when we have enough SP (or manual trigger via API)
        if total_sp < MIN_RELEASE_SP:
            logger.info(
                f"Release Manager: {len(ready_tasks)} tasks ({total_sp}/{MIN_RELEASE_SP} SP). Waiting."
            )
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
        
        # 7. Merge PRs into develop
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
                else:
                    failed_count += 1
                    logger.warning(f"Failed to merge PR #{pr_number} for '{task.title}'")
                merge_results.append({"task": task.title, "pr": task.pr_url, "success": success})
            except Exception as e:
                failed_count += 1
                logger.error(f"Error merging PR #{pr_number}: {e}")
                merge_results.append({"task": task.title, "pr": task.pr_url, "success": False, "error": str(e)})
        
        # 8. Update release status to staging
        release.status = ReleaseStatus.STAGING
        release.staging_deployed_at = datetime.now(UTC)
        
        # 9. Move selected tasks to staging
        for task in selected:
            task.status = TaskStatus.STAGING
            task.release_id = release.id
        
        await session.commit()
        
        logger.info(
            f"Release {version}: {len(selected)} tasks ({selected_sp} SP), "
            f"{merged_count} merged, {failed_count} failed"
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
            sp_str = f"[{t['sp']}SP] " if t.get('sp') else ""
            pr_link = f' <a href="{t["pr_url"]}">PR</a>' if t.get("pr_url") else ""
            text += f"• {sp_str}{t['title']}{pr_link}\n"
        
        if remaining:
            text += f"\n📦 {remaining} задач осталось в очереди на следующий релиз"
        
        text += "\n\n📋 Посмотри staging и дай фидбек."
        
        await bot.send_message(bot.owner_chat_id, text)
    except Exception as e:
        logger.warning(f"Release Manager: failed to notify: {e}")


async def release_worker_loop(session_factory: async_sessionmaker) -> None:
    """Endless loop: check for ready tasks and form releases."""
    import asyncio
    
    logger.info(f"Release Manager started — checking every {RELEASE_CHECK_INTERVAL}s, SP range {MIN_RELEASE_SP}-{MAX_RELEASE_SP}")
    
    # Wait 5 minutes on startup
    await asyncio.sleep(300)
    
    while True:
        try:
            release_info = await check_and_create_release(session_factory)
            if release_info:
                await notify_release(release_info)
        except Exception:
            logger.exception("Release Manager: unhandled error")
        
        await asyncio.sleep(RELEASE_CHECK_INTERVAL)
