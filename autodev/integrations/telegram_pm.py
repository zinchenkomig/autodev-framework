"""Telegram PM Bot — chat with PM agent via Telegram.

Handles:
- Incoming messages → PM agent
- Notifications for task events
- Inline buttons for approve/reject
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramPMBot:
    """Telegram bot for PM agent interaction."""

    def __init__(self) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.owner_chat_id = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
        self.pm_api_url = os.environ.get("PM_API_URL", "http://localhost:8000/api/pm")
        self._client: httpx.AsyncClient | None = None

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
        # Handle callback query (button press)
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return

        # Handle text message
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        
        if not chat_id or not text:
            return

        # Check if from owner
        if chat_id != self.owner_chat_id:
            await self.send_message(chat_id, "⛔ Доступ только для владельца")
            return

        # Commands
        if text.startswith("/"):
            await self._handle_command(chat_id, text)
            return

        # Regular message → PM agent
        await self._chat_with_pm(chat_id, text)

    async def _handle_command(self, chat_id: str, text: str) -> None:
        """Handle bot commands."""
        cmd = text.split()[0].lower()
        
        if cmd == "/start":
            await self.send_message(
                chat_id,
                "👋 PM Agent\n\n"
                "Просто напиши описание фичи — я создам задачи.\n\n"
                "Команды:\n"
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

        # Send PM response
        pm_response = data.get("response", "")
        if pm_response:
            # Escape HTML
            pm_response = pm_response.replace("<", "&lt;").replace(">", "&gt;")
            await self.send_message(chat_id, pm_response)

        # Send task proposals as cards with buttons
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
            
            # Inline buttons
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "❌ Отклонить", "callback_data": f"reject:{session_id}:{i}"},
                    {"text": "✅ В бэклог", "callback_data": f"approve:{session_id}:{i}:{title}:{repo}:{priority}"},
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
        
        parts = data.split(":")
        action = parts[0]
        
        if action == "reject":
            await self.answer_callback_query(callback_id, "❌ Отклонено")
            await self.edit_message_text(
                chat_id, message_id,
                message.get("text", "") + "\n\n❌ <i>Отклонено</i>"
            )
        
        elif action == "approve":
            # approve:session_id:idx:title:repo:priority
            if len(parts) >= 6:
                _, session_id, idx, title, repo, priority = parts[:6]
                
                # Create task via API
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
                                    "description": "",  # Already in DB from proposal
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
                                message.get("text", "") + f"\n\n✅ <i>Создано</i>\n<a href=\"{task['url']}\">Открыть</a>"
                            )
                        else:
                            await self.answer_callback_query(callback_id, "❌ Ошибка")
                except Exception as e:
                    logger.error(f"Failed to approve: {e}")
                    await self.answer_callback_query(callback_id, f"❌ {e}")

    async def _show_tasks(self, chat_id: str) -> None:
        """Show recent tasks."""
        # TODO: Implement
        await self.send_message(chat_id, "📋 /tasks — в разработке")

    async def _show_status(self, chat_id: str) -> None:
        """Show system status."""
        # TODO: Implement
        await self.send_message(chat_id, "📊 /status — в разработке")

    # ========== Notifications ==========

    async def notify_task_failed(self, task_id: str, title: str, error: str) -> None:
        """Notify owner about failed task."""
        if not self.owner_chat_id:
            return
        
        text = (
            f"❌ <b>Задача провалилась</b>\n\n"
            f"📋 {title}\n"
            f"🔗 <code>{task_id}</code>\n\n"
            f"Ошибка: {error[:200]}"
        )
        await self.send_message(self.owner_chat_id, text)

    async def notify_task_ready_for_review(self, task_id: str, title: str, pr_url: str = "") -> None:
        """Notify owner about task ready for review."""
        if not self.owner_chat_id:
            return
        
        text = (
            f"👀 <b>Готово к ревью</b>\n\n"
            f"📋 {title}\n"
        )
        if pr_url:
            text += f"🔗 <a href=\"{pr_url}\">Pull Request</a>"
        
        await self.send_message(self.owner_chat_id, text)

    async def notify_release_pending(self, release_id: str, version: str) -> None:
        """Notify owner about pending release."""
        if not self.owner_chat_id:
            return
        
        text = (
            f"🚀 <b>Релиз ждёт подтверждения</b>\n\n"
            f"Версия: {version}\n"
            f"ID: <code>{release_id}</code>"
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


# Global instance
_bot: TelegramPMBot | None = None


def get_telegram_bot() -> TelegramPMBot:
    """Get or create global Telegram bot instance."""
    global _bot
    if _bot is None:
        _bot = TelegramPMBot()
    return _bot
