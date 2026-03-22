"""Telegram PM Bot — chat with PM agent via Telegram."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def get_telegram_settings() -> dict:
    """Get Telegram settings from database."""
    from autodev.api.database import SessionLocal
    from autodev.core.models import Setting
    from sqlalchemy import select
    
    async with SessionLocal() as session:
        result = await session.execute(select(Setting))
        settings = {s.key: s.value for s in result.scalars().all()}
    
    return {
        "token": settings.get("telegram_bot_token", ""),
        "chat_id": settings.get("telegram_owner_chat_id", ""),
        "secret": settings.get("telegram_webhook_secret", ""),
    }


class TelegramPMBot:
    """Telegram bot for PM agent interaction."""

    def __init__(self, token: str = "", owner_chat_id: str = "") -> None:
        self.token = token
        self.owner_chat_id = owner_chat_id
        self.pm_api_url = "http://localhost:8000/api/pm"
        self._client: httpx.AsyncClient | None = None

    @classmethod
    async def from_settings(cls) -> "TelegramPMBot":
        """Create bot from database settings."""
        settings = await get_telegram_settings()
        return cls(token=settings["token"], owner_chat_id=settings["chat_id"])

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=f"{TELEGRAM_API}/bot{self.token}",
                timeout=30.0
            )
        return self._client

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> dict:
        """Send message to Telegram."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        
        try:
            resp = await self.client.post("/sendMessage", data=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {}

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str = "",
        show_alert: bool = False,
    ) -> dict:
        """Answer inline button callback."""
        payload = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        }
        try:
            resp = await self.client.post("/answerCallbackQuery", data=payload)
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to answer callback: {e}")
            return {}

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> dict:
        """Edit existing message."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        
        try:
            resp = await self.client.post("/editMessageText", data=payload)
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            return {}

    async def handle_update(self, update: dict) -> None:
        """Process incoming Telegram update."""
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        
        if not chat_id or not text:
            return

        if chat_id != self.owner_chat_id:
            await self.send_message(chat_id, "⛔ Доступ только для владельца")
            return

        if text.startswith("/"):
            await self._handle_command(chat_id, text)
            return

        await self._chat_with_pm(chat_id, text)

    async def _handle_command(self, chat_id: str, text: str) -> None:
        """Handle bot commands."""
        cmd = text.split()[0].lower()
        
        if cmd == "/start":
            await self.send_message(
                chat_id,
                "👋 <b>PM Agent</b>\n\n"
                "Просто напиши описание фичи — я создам задачи.\n\n"
                "<b>Команды:</b>\n"
                "/tasks — список задач\n"
                "/status — статус системы"
            )
        elif cmd == "/tasks":
            await self._show_tasks(chat_id)
        elif cmd == "/status":
            await self._show_status(chat_id)
        else:
            await self.send_message(chat_id, f"❓ Неизвестная команда: {cmd}")

    async def _chat_with_pm(self, chat_id: str, message: str) -> None:
        """Send message to PM agent and show response."""
        await self.send_message(chat_id, "🤔 Думаю...")
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.pm_api_url}/chat",
                    json={"message": message}
                )
                data = resp.json()
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
            return

        pm_response = data.get("response", "")
        if pm_response:
            pm_response = pm_response.replace("<", "&lt;").replace(">", "&gt;")
            await self.send_message(chat_id, pm_response)

        proposals = data.get("proposals", [])
        session_id = data.get("session_id", "")
        
        for i, p in enumerate(proposals):
            title = p.get("title", "")
            repo = p.get("repo", "")
            priority = p.get("priority", "normal")
            description = p.get("description", "")[:300]
            
            text = (
                f"📋 <b>{title}</b>\n"
                f"📁 {repo}\n"
                f"🔹 {priority}\n\n"
                f"{description}..."
            )
            
            callback_data = f"approve:{session_id}:{i}:{title[:30]}:{repo}:{priority}"
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "❌ Отклонить", "callback_data": f"reject:{i}"},
                    {"text": "✅ В бэклог", "callback_data": callback_data},
                ]]
            }
            
            await self.send_message(chat_id, text, reply_markup=reply_markup)

    async def _handle_callback(self, callback: dict) -> None:
        """Handle inline button press."""
        callback_id = callback.get("id", "")
        data = callback.get("data", "")
        message = callback.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        message_id = message.get("message_id", 0)
        original_text = message.get("text", "")
        
        parts = data.split(":")
        action = parts[0]
        
        if action == "reject":
            await self.answer_callback_query(callback_id, "❌ Отклонено")
            await self.edit_message_text(
                chat_id, message_id,
                original_text + "\n\n❌ <i>Отклонено</i>"
            )
        
        elif action == "approve" and len(parts) >= 6:
            _, session_id, idx, title, repo, priority = parts[:6]
            
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.pm_api_url}/approve",
                        json={
                            "session_id": session_id,
                            "proposals": [{
                                "title": title,
                                "repo": repo,
                                "priority": priority,
                                "description": "",
                            }]
                        }
                    )
                    result = resp.json()
                    created = result.get("created_tasks", [])
                    
                    if created:
                        task = created[0]
                        await self.answer_callback_query(callback_id, "✅ Создано!")
                        await self.edit_message_text(
                            chat_id, message_id,
                            original_text + f"\n\n✅ <a href=\"{task['url']}\">Создано</a>"
                        )
                    else:
                        await self.answer_callback_query(callback_id, "❌ Ошибка")
            except Exception as e:
                logger.error(f"Failed to approve: {e}")
                await self.answer_callback_query(callback_id, f"❌ {str(e)[:50]}")

    async def _show_tasks(self, chat_id: str) -> None:
        """Show recent tasks."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:8000/api/tasks?limit=5")
                tasks = resp.json()
                
            if not tasks:
                await self.send_message(chat_id, "📋 Нет задач")
                return
            
            text = "📋 <b>Последние задачи:</b>\n\n"
            for t in tasks:
                status_emoji = {"queued": "⏳", "in_progress": "🔄", "review": "👀", "failed": "❌"}.get(t["status"], "📋")
                text += f"{status_emoji} {t['title'][:40]}\n"
            
            await self.send_message(chat_id, text)
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")

    async def _show_status(self, chat_id: str) -> None:
        """Show system status."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:8000/api/agents")
                agents = resp.json()
            
            text = "📊 <b>Статус системы:</b>\n\n"
            for a in agents:
                status_emoji = {"idle": "😴", "busy": "🔄", "disabled": "⛔"}.get(a.get("status", ""), "❓")
                enabled = "✅" if a.get("enabled", True) else "⛔"
                text += f"{enabled} {a['name']}: {status_emoji}\n"
            
            await self.send_message(chat_id, text)
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")

    # ========== Notifications ==========

    async def notify_task_failed(self, task_id: str, title: str, error: str) -> None:
        """Notify owner about failed task."""
        if not self.owner_chat_id:
            return
        
        text = (
            f"❌ <b>Задача провалилась</b>\n\n"
            f"📋 {title}\n\n"
            f"Ошибка: <code>{error[:200]}</code>"
        )
        await self.send_message(self.owner_chat_id, text)

    async def notify_task_ready_for_review(self, task_id: str, title: str, pr_url: str = "") -> None:
        """Notify owner about task ready for review."""
        if not self.owner_chat_id:
            return
        
        text = f"👀 <b>Готово к ревью</b>\n\n📋 {title}\n"
        if pr_url:
            text += f"🔗 <a href=\"{pr_url}\">Pull Request</a>"
        
        await self.send_message(self.owner_chat_id, text)

    async def notify_release_pending(self, release_id: str, version: str) -> None:
        """Notify owner about pending release."""
        if not self.owner_chat_id:
            return
        
        text = (
            f"🚀 <b>Релиз ждёт подтверждения</b>\n\n"
            f"Версия: {version}"
        )
        
        reply_markup = {
            "inline_keyboard": [[
                {"text": "❌ Отмена", "callback_data": f"release_cancel:{release_id}"},
                {"text": "✅ Деплой", "callback_data": f"release_deploy:{release_id}"},
            ]]
        }
        
        await self.send_message(self.owner_chat_id, text, reply_markup=reply_markup)

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()


async def get_telegram_bot() -> TelegramPMBot:
    """Get Telegram bot from settings."""
    return await TelegramPMBot.from_settings()
