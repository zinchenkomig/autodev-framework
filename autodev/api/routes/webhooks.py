"""Webhook receiver endpoints."""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request

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
