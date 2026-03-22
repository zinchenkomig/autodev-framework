"""Settings API routes."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from autodev.api.database import get_session
from autodev.core.models import Setting

router = APIRouter(tags=["settings"])


class SettingValue(BaseModel):
    value: str


class TelegramSettings(BaseModel):
    bot_token: str
    owner_chat_id: str
    webhook_secret: str
    webhook_url: str


class TelegramTestResult(BaseModel):
    success: bool
    message: str
    bot_username: str | None = None


async def get_setting(session: AsyncSession, key: str) -> str:
    """Get setting value."""
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting and setting.value else ""


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    """Set setting value."""
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        session.add(Setting(key=key, value=value))


@router.get("/telegram", summary="Get Telegram settings")
async def get_telegram_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TelegramSettings:
    """Get Telegram bot settings."""
    token = await get_setting(session, "telegram_bot_token")
    chat_id = await get_setting(session, "telegram_owner_chat_id")
    secret = await get_setting(session, "telegram_webhook_secret")
    
    # Build webhook URL
    webhook_url = os.environ.get("AUTODEV_WEBHOOK_URL", "https://autodev.zinchenkomig.com/api/webhooks/telegram")
    
    return TelegramSettings(
        bot_token="*" * 10 if token else "",  # Mask token
        owner_chat_id=chat_id,
        webhook_secret=secret,
        webhook_url=webhook_url,
    )


@router.put("/telegram", summary="Update Telegram settings")
async def update_telegram_settings(
    settings: TelegramSettings,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Update Telegram bot settings."""
    # Only update token if not masked
    if settings.bot_token and not settings.bot_token.startswith("*"):
        await set_setting(session, "telegram_bot_token", settings.bot_token)
    
    await set_setting(session, "telegram_owner_chat_id", settings.owner_chat_id)
    await set_setting(session, "telegram_webhook_secret", settings.webhook_secret)
    
    return {"status": "updated"}


@router.post("/telegram/test", summary="Test Telegram connection")
async def test_telegram(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TelegramTestResult:
    """Test Telegram bot connection and send test message."""
    token = await get_setting(session, "telegram_bot_token")
    chat_id = await get_setting(session, "telegram_owner_chat_id")
    
    if not token:
        return TelegramTestResult(success=False, message="Bot token not set")
    
    if not chat_id:
        return TelegramTestResult(success=False, message="Owner chat ID not set")
    
    try:
        async with httpx.AsyncClient() as client:
            # Get bot info
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            if resp.status_code != 200:
                return TelegramTestResult(success=False, message="Invalid bot token")
            
            bot_info = resp.json()
            bot_username = bot_info.get("result", {}).get("username", "")
            
            # Send test message
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "✅ AutoDev Telegram integration test successful!",
                }
            )
            
            if resp.status_code != 200:
                error = resp.json().get("description", "Unknown error")
                return TelegramTestResult(
                    success=False, 
                    message=f"Failed to send message: {error}",
                    bot_username=bot_username
                )
            
            return TelegramTestResult(
                success=True,
                message="Test message sent successfully",
                bot_username=bot_username
            )
    
    except Exception as e:
        return TelegramTestResult(success=False, message=str(e))


@router.post("/telegram/webhook", summary="Setup Telegram webhook")
async def setup_telegram_webhook(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Register webhook URL with Telegram."""
    token = await get_setting(session, "telegram_bot_token")
    secret = await get_setting(session, "telegram_webhook_secret")
    webhook_url = os.environ.get("AUTODEV_WEBHOOK_URL", "https://autodev.zinchenkomig.com/api/webhooks/telegram")
    
    if not token:
        raise HTTPException(400, "Bot token not set")
    
    try:
        async with httpx.AsyncClient() as client:
            payload = {"url": webhook_url}
            if secret:
                payload["secret_token"] = secret
            
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json=payload
            )
            
            result = resp.json()
            if not result.get("ok"):
                raise HTTPException(400, result.get("description", "Failed"))
            
            return {"status": "ok", "webhook_url": webhook_url}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/telegram/webhook", summary="Remove Telegram webhook")
async def remove_telegram_webhook(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Remove webhook from Telegram."""
    token = await get_setting(session, "telegram_bot_token")
    
    if not token:
        raise HTTPException(400, "Bot token not set")
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/deleteWebhook"
            )
            result = resp.json()
            return {"status": "ok" if result.get("ok") else "error"}
    except Exception as e:
        raise HTTPException(500, str(e))
