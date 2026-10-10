"""Webhook receiver endpoints.

GitHub state is polled by the worker, so only Telegram pushes to us.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()


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
