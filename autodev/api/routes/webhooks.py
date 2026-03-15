"""Webhook receiver endpoints.

Handles incoming webhooks from GitHub and other external services.
Events are validated, parsed, and published to the internal EventBus.

TODO: Add Telegram webhook receiver.
TODO: Add idempotency key handling to prevent duplicate processing.
TODO: Add webhook delivery log for debugging.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from autodev.core.events import EventBus
from autodev.integrations.github import verify_webhook_signature

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Dependency — provide a shared EventBus instance
# ---------------------------------------------------------------------------

# Module-level default bus (used when no app-state bus is wired up).
_default_bus: EventBus = EventBus()


def get_event_bus(request: Request) -> EventBus:
    """FastAPI dependency that returns the application EventBus.

    Looks for ``app.state.event_bus`` first; falls back to the module-level
    default so the endpoint works even without a fully configured app.
    """
    return getattr(getattr(request, "app", None), "state", _default_bus) and getattr(
        getattr(request.app, "state", None), "event_bus", _default_bus
    ) or _default_bus


# ---------------------------------------------------------------------------
# GitHub webhook endpoint
# ---------------------------------------------------------------------------


@router.post("/github", summary="Receive GitHub webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict[str, str]:
    """Receive and process a GitHub webhook event.

    Verifies the HMAC-SHA256 signature when ``GITHUB_WEBHOOK_SECRET`` is set,
    then routes the event to the internal EventBus.

    Args:
        request: Raw HTTP request (body read for signature verification).
        x_github_event: GitHub event type header.
        x_hub_signature_256: HMAC-SHA256 signature header.
        event_bus: Application event bus (injected via Depends).

    Returns:
        JSON dict with ``status`` and ``event`` fields.

    Raises:
        HTTPException 400: If signature verification fails.
    """
    body = await request.body()
    logger.info("GitHub webhook received: event=%s bytes=%d", x_github_event, len(body))

    # ---- Signature verification ----------------------------------------
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        if not x_hub_signature_256:
            logger.warning("GitHub webhook received without signature")
            raise HTTPException(status_code=400, detail="Missing X-Hub-Signature-256 header")
        if not verify_webhook_signature(body, secret, x_hub_signature_256):
            logger.warning("GitHub webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
    else:
        if not x_hub_signature_256:
            logger.warning(
                "GitHub webhook received without signature — skipping verification "
                "(no secret configured)"
            )

    # ---- Parse payload --------------------------------------------------
    try:
        payload: dict = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    # ---- Route events ---------------------------------------------------
    action: str = payload.get("action", "")

    if x_github_event == "push":
        await event_bus.emit("push", payload=payload, source="github.webhook")

    elif x_github_event == "pull_request":
        if action == "opened":
            await event_bus.emit(
                "pr.created",
                payload={
                    "pr_number": payload.get("number"),
                    "title": payload.get("pull_request", {}).get("title"),
                    "head": payload.get("pull_request", {}).get("head", {}).get("ref"),
                    "base": payload.get("pull_request", {}).get("base", {}).get("ref"),
                    "repo": payload.get("repository", {}).get("full_name"),
                    "raw": payload,
                },
                source="github.webhook",
            )
        elif action == "closed" and payload.get("pull_request", {}).get("merged"):
            await event_bus.emit(
                "pr.merged",
                payload={
                    "pr_number": payload.get("number"),
                    "title": payload.get("pull_request", {}).get("title"),
                    "merged_by": payload.get("pull_request", {}).get("merged_by", {}).get("login"),
                    "repo": payload.get("repository", {}).get("full_name"),
                    "raw": payload,
                },
                source="github.webhook",
            )

    elif x_github_event == "issues":
        if action == "opened":
            issue = payload.get("issue", {})
            issue_labels: list[str] = [lbl.get("name", "") for lbl in issue.get("labels", [])]
            if "autodev" in issue_labels:
                await event_bus.emit(
                    "task.created",
                    payload={
                        "issue_number": issue.get("number"),
                        "title": issue.get("title"),
                        "body": issue.get("body"),
                        "labels": issue_labels,
                        "repo": payload.get("repository", {}).get("full_name"),
                        "raw": payload,
                    },
                    source="github.webhook",
                )

    elif x_github_event == "check_suite":
        if action == "completed":
            conclusion: str = payload.get("check_suite", {}).get("conclusion", "")
            event_type = "pr.ci.passed" if conclusion == "success" else "pr.ci.failed"
            await event_bus.emit(
                event_type,
                payload={
                    "conclusion": conclusion,
                    "head_sha": payload.get("check_suite", {}).get("head_sha"),
                    "head_branch": payload.get("check_suite", {}).get("head_branch"),
                    "repo": payload.get("repository", {}).get("full_name"),
                    "raw": payload,
                },
                source="github.webhook",
            )

    else:
        logger.debug("Unhandled GitHub event type: %s (action=%s)", x_github_event, action)

    return {"status": "received", "event": x_github_event}


# ---------------------------------------------------------------------------
# Telegram webhook (stub)
# ---------------------------------------------------------------------------


@router.post("/telegram", summary="Receive Telegram webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    """Receive and process a Telegram bot update.

    TODO: Validate Telegram secret token header.
    TODO: Parse Update object and dispatch to Telegram integration.
    """
    body = await request.body()
    logger.info("Telegram webhook received: bytes=%d", len(body))
    # TODO: Parse and dispatch update
    return {"status": "received"}
