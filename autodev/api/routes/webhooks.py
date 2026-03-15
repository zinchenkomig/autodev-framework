"""Webhook receiver endpoints.

Handles incoming webhooks from GitHub and other external services.
Events are validated, parsed, and published to the internal EventBus.

TODO: Implement GitHub webhook signature verification (HMAC-SHA256).
TODO: Add Telegram webhook receiver.
TODO: Add idempotency key handling to prevent duplicate processing.
TODO: Add webhook delivery log for debugging.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/github", summary="Receive GitHub webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> dict[str, str]:
    """Receive and process a GitHub webhook event.

    Args:
        request: Raw HTTP request (body read for signature verification).
        x_github_event: GitHub event type header.
        x_hub_signature_256: HMAC-SHA256 signature header.

    TODO: Verify HMAC signature against configured webhook secret.
    TODO: Parse event payload and publish to EventBus.
    TODO: Return 200 quickly; process async in background.
    """
    body = await request.body()
    logger.info("GitHub webhook received: event=%s bytes=%d", x_github_event, len(body))

    if not x_hub_signature_256:
        # TODO: Enforce signature verification in production
        logger.warning("GitHub webhook received without signature — skipping verification")

    # TODO: Parse and dispatch event
    return {"status": "received", "event": x_github_event}


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
