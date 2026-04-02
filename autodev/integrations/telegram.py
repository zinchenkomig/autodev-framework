"""Telegram bot integration — send messages and receive updates.

Uses the Telegram Bot API directly via httpx (no third-party library
dependency to keep the footprint small).

TODO: Add Telegram webhook setup / polling mode toggle.
TODO: Add inline keyboard support for interactive agent commands.
TODO: Add file/photo sending for release artifacts.
TODO: Add command handler registry (/start, /status, /task, etc.).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramBot:
    """Async Telegram Bot API client.

    Args:
        token: Bot token from @BotFather.
        default_chat_id: Default chat / channel to send messages to.

    TODO: Add message rate limiting (Telegram allows ~30 msg/s to different chats).
    TODO: Add HTML/MarkdownV2 parse mode toggle.
    """

    def __init__(self, token: str, default_chat_id: str = "") -> None:
        self.default_chat_id = default_chat_id
        self._client = httpx.AsyncClient(base_url=f"{TELEGRAM_API_BASE}/bot{token}")

    async def send_message(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: str = "HTML",
    ) -> dict:
        """Send a text message.

        Args:
            text: Message text (HTML formatted by default).
            chat_id: Target chat; falls back to default_chat_id.
            parse_mode: ``HTML`` or ``MarkdownV2``.

        TODO: Add reply_to_message_id support.
        TODO: Add silent notification flag.
        """
        payload = {
            "chat_id": chat_id or self.default_chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        response = await self._client.post("/sendMessage", json=payload)
        response.raise_for_status()
        return response.json()

    async def set_webhook(self, url: str, secret_token: str = "") -> dict:
        """Register the webhook URL with Telegram.

        Args:
            url: Publicly accessible HTTPS URL for the webhook endpoint.
            secret_token: Optional secret for ``X-Telegram-Bot-Api-Secret-Token`` header.

        TODO: Add allowed_updates filter.
        """
        payload: dict = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        response = await self._client.post("/setWebhook", json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


class TelegramNotifier:
    """High-level Telegram notifier for the notification system.

    Args:
        bot_token: Telegram Bot API token from @BotFather.
        chat_id: Target chat or channel ID.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.chat_id = chat_id
        self._client = httpx.AsyncClient(base_url=f"{TELEGRAM_API_BASE}/bot{bot_token}")

    async def send(self, text: str, parse_mode: str = "HTML") -> dict:
        """Send a text message with the given parse mode.

        Args:
            text: Message text.
            parse_mode: ``HTML`` (default) or ``MarkdownV2``.

        Returns:
            Telegram API response as a dict.
        """
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        response = await self._client.post("/sendMessage", json=payload)
        response.raise_for_status()
        return response.json()

    async def send_markdown(self, text: str) -> dict:
        """Send a message using MarkdownV2 parse mode.

        Args:
            text: MarkdownV2-formatted text.

        Returns:
            Telegram API response as a dict.
        """
        return await self.send(text, parse_mode="MarkdownV2")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
