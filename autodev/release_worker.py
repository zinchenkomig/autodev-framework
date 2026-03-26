"""Release Manager Worker — periodically checks for ready tasks and forms releases.

Every 30 minutes:
1. Check if there are tasks in ready_to_release
2. If enough tasks accumulated (or oldest is >2h old), form a release
3. Merge PRs into develop
4. Deploy to staging
5. Move tasks to staging status
6. Notify user
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.models import (
    Release, ReleaseStatus, Task, TaskStatus,
)

logger = logging.getLogger(__name__)

RELEASE_CHECK_INTERVAL = int(os.environ.get("RELEASE_CHECK_INTERVAL", "1800"))  # 30 min
MIN_TASKS_FOR_RELEASE = int(os.environ.get("MIN_TASKS_FOR_RELEASE", "1"))
MAX_TASK_AGE_HOURS = float(os.environ.get("MAX_TASK_WAIT_HOURS", "2"))  # auto-release if any task is older


async def check_and_create_release(session_factory: async_sessionmaker) -> dict | None:
    """Check for ready tasks and create a release if conditions are met."""
    
    async with session_factory() as session:
        # 1. Get all ready_to_release tasks
        result = await session.execute(
            select(Task)
            .where(Task.status == TaskStatus.READY_TO_RELEASE)
            .order_by(Task.updated_at)
        )
        ready_tasks = result.scalars().all()
        
        if not ready_tasks:
            return None
        
        # 2. Check conditions
        task_count = len(ready_tasks)
        oldest_task_age = datetime.now(UTC) - ready_tasks[0].updated_at
        
        should_release = (
            task_count >= MIN_TASKS_FOR_RELEASE
            or oldest_task_age > timedelta(hours=MAX_TASK_AGE_HOURS)
        )
        
        if not should_release:
            logger.info(f"Release Manager: {task_count} tasks ready, oldest {oldest_task_age}. Waiting.")
            return None
        
        logger.info(f"Release Manager: forming release with {task_count} tasks")
        
        # 3. Generate version
        version = datetime.now(UTC).strftime("v%Y-%m-%d-%H%M")
        
        # 4. Generate release notes
        release_notes = f"# Release {version}\n\n"
        release_notes += f"**Задачи ({task_count}):**\n\n"
        
        backend_tasks = [t for t in ready_tasks if "backend" in (t.repo or "")]
        frontend_tasks = [t for t in ready_tasks if "frontend" in (t.repo or "")]
        other_tasks = [t for t in ready_tasks if t not in backend_tasks and t not in frontend_tasks]
        
        if backend_tasks:
            release_notes += "### Backend\n"
            for t in backend_tasks:
                pr_link = f" ([PR]({t.pr_url}))" if t.pr_url else ""
                release_notes += f"- {t.title}{pr_link}\n"
            release_notes += "\n"
        
        if frontend_tasks:
            release_notes += "### Frontend\n"
            for t in frontend_tasks:
                pr_link = f" ([PR]({t.pr_url}))" if t.pr_url else ""
                release_notes += f"- {t.title}{pr_link}\n"
            release_notes += "\n"
        
        if other_tasks:
            release_notes += "### Other\n"
            for t in other_tasks:
                release_notes += f"- {t.title}\n"
            release_notes += "\n"
        
        # 5. Create release
        task_ids = [t.id for t in ready_tasks]
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
        
        # 6. Merge PRs into develop
        merge_results = []
        from autodev.core.github_ops import extract_pr_info, merge_pr
        
        for task in ready_tasks:
            if not task.pr_url:
                continue
            
            info = extract_pr_info(task.pr_url)
            if not info:
                continue
            
            repo, pr_number = info
            try:
                success = await merge_pr(repo, pr_number)
                merge_results.append({
                    "task": task.title,
                    "pr": task.pr_url,
                    "success": success,
                })
                if success:
                    logger.info(f"Merged PR #{pr_number} for '{task.title}'")
                else:
                    logger.warning(f"Failed to merge PR #{pr_number} for '{task.title}'")
            except Exception as e:
                logger.error(f"Error merging PR #{pr_number}: {e}")
                merge_results.append({
                    "task": task.title,
                    "pr": task.pr_url,
                    "success": False,
                    "error": str(e),
                })
        
        # 7. Update release status to staging
        release.status = ReleaseStatus.STAGING
        release.staging_deployed_at = datetime.now(UTC)
        
        # 8. Move tasks to staging
        for task in ready_tasks:
            task.status = TaskStatus.STAGING
            task.release_id = release.id
        
        await session.commit()
        
        logger.info(f"Release {version} created with {task_count} tasks, deployed to staging")
        
        return {
            "version": version,
            "release_id": str(release.id),
            "task_count": task_count,
            "tasks": [{"title": t.title, "pr_url": t.pr_url} for t in ready_tasks],
            "merge_results": merge_results,
            "release_notes": release_notes,
        }


async def notify_release(release_info: dict) -> None:
    """Notify user about new release via Telegram."""
    if not release_info:
        return
    
    try:
        from autodev.integrations.telegram_pm import get_telegram_bot
        bot = await get_telegram_bot()
        
        version = release_info["version"]
        task_count = release_info["task_count"]
        
        text = f"🚀 <b>Release {version}</b>\n\n"
        text += f"<b>{task_count} задач(и) на staging:</b>\n\n"
        
        for t in release_info["tasks"]:
            pr_link = f' <a href="{t["pr_url"]}">PR</a>' if t.get("pr_url") else ""
            text += f"• {t['title']}{pr_link}\n"
        
        text += "\n📋 Посмотри на staging и дай фидбек в Dashboard."
        
        await bot.send_message(bot.owner_chat_id, text)
    except Exception as e:
        logger.warning(f"Release Manager: failed to notify: {e}")


async def release_worker_loop(session_factory: async_sessionmaker) -> None:
    """Endless loop: check for ready tasks and form releases."""
    import asyncio
    
    logger.info(f"Release Manager started — checking every {RELEASE_CHECK_INTERVAL}s")
    
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
