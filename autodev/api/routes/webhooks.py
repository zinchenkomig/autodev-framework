"""Webhook receiver endpoints."""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.events import EventBus
from autodev.integrations.github import verify_webhook_signature

logger = logging.getLogger(__name__)
router = APIRouter()

_default_bus: EventBus = EventBus()


def get_event_bus(request: Request) -> EventBus:
    return getattr(getattr(request.app, "state", None), "event_bus", _default_bus) or _default_bus


@router.post("/github", summary="Receive GitHub webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict[str, str]:
    """Receive GitHub webhook."""
    body = await request.body()
    logger.info("GitHub webhook: event=%s", x_github_event)

    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        if not x_hub_signature_256:
            raise HTTPException(400, "Missing signature")
        if not verify_webhook_signature(body, x_hub_signature_256, secret):
            raise HTTPException(400, "Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}") from e

    await event_bus.publish(f"github.{x_github_event}", payload)
    return {"status": "ok", "event": x_github_event}


@router.post("/telegram", summary="Receive Telegram webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    """Receive Telegram bot update."""
    from autodev.integrations.telegram_pm import get_telegram_bot, get_telegram_settings

    body = await request.body()
    logger.info("Telegram webhook: bytes=%d", len(body))

    # Verify secret token if set
    settings = await get_telegram_settings()
    secret = settings.get("secret", "")
    if secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != secret:
            raise HTTPException(403, "Invalid secret")

    try:
        update = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    # Process update
    bot = await get_telegram_bot()
    if not bot.token:
        logger.warning("Telegram bot token not configured")
        return {"status": "not_configured"}

    try:
        await bot.handle_update(update)
    except Exception as e:
        logger.error(f"Telegram handler error: {e}")

    return {"status": "ok"}


@router.post("/github/ci", summary="GitHub CI webhook")
async def github_ci_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Handle GitHub check_suite / check_run webhooks.

    When CI passes on an autodev branch, auto-promote task to ready_to_release.
    """
    import uuid as _uuid

    from sqlalchemy import or_, select

    from autodev.core.models import Task, TaskStatus

    body = await request.json()
    event = request.headers.get("x-github-event", "")

    # Extract branch from either check_suite or check_run
    branch = ""
    conclusion = ""

    if event == "check_suite":
        suite = body.get("check_suite", {})
        conclusion = suite.get("conclusion", "")
        branch = suite.get("head_branch", "")
    elif event == "check_run":
        check = body.get("check_run", {})
        conclusion = check.get("conclusion", "")
        branch = check.get("check_suite", {}).get("head_branch", "")
    else:
        return {"status": "unhandled_event", "event": event}

    if conclusion != "success" or not branch.startswith("autodev-"):
        return {"status": "ignored", "conclusion": conclusion, "branch": branch}

    # Extract task ID from branch name: autodev-{uuid}
    task_id_str = branch.replace("autodev-", "")

    # Find task by branch OR by ID
    try:
        tid = _uuid.UUID(task_id_str)
    except ValueError:
        tid = None

    result = await session.execute(
        select(Task)
        .where(Task.status == TaskStatus.AUTOREVIEW)
        .where(
            or_(
                Task.branch == branch,
                Task.id == tid if tid else Task.branch == branch,
            )
        )
    )
    task = result.scalar_one_or_none()

    if task:
        if not task.branch:
            task.branch = branch

        # Hotfix: bypass release manager, go straight to current staging release
        if getattr(task, "task_type", "feature") == "hotfix":
            from autodev.core.github_ops import extract_pr_info, merge_pr
            from autodev.core.models import Release, ReleaseStatus

            # Find active staging release
            rel_result = await session.execute(
                select(Release)
                .where(Release.status == ReleaseStatus.STAGING)
                .order_by(Release.created_at.desc())
                .limit(1)
            )
            release = rel_result.scalar_one_or_none()

            if release:
                # Merge PR immediately
                if task.pr_url:
                    info = extract_pr_info(task.pr_url)
                    if info:
                        repo, pr_number = info
                        try:
                            await merge_pr(repo, pr_number)
                        except Exception as e:
                            logger.warning(f"Hotfix merge failed: {e}")

                # Add to release and move to staging
                if task.id not in (release.tasks or []):
                    release.tasks = (release.tasks or []) + [task.id]
                task.status = TaskStatus.STAGING
                task.release_id = release.id
                logger.info(f"CI webhook: hotfix {task.id} merged into staging release {release.version}")
                return {
                    "status": "hotfix_merged",
                    "task_id": str(task.id),
                    "release": release.version,
                }
            else:
                # No staging release — treat as regular
                task.status = TaskStatus.QA_TESTING
        else:
            task.status = TaskStatus.QA_TESTING

        logger.info(f"CI webhook: promoted task {task.id} to {task.status}")
        return {"status": "promoted", "task_id": str(task.id), "task": task.title}

    return {"status": "no_matching_task", "branch": branch, "task_id": task_id_str}
