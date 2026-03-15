"""Slack integration — send messages via Incoming Webhooks.

Uses Slack Incoming Webhooks API via httpx. No OAuth token required —
just a webhook URL generated from the Slack app configuration.

TODO: Add support for Slack Web API (chat.postMessage) for richer features.
TODO: Add attachment support (legacy formatting).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Async Slack notifier via Incoming Webhook.

    Args:
        webhook_url: Slack Incoming Webhook URL obtained from app configuration.
    """

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self._client = httpx.AsyncClient()

    async def send(self, text: str, blocks: list | None = None) -> dict:
        """Send a message to the Slack channel.

        Args:
            text: Plain text fallback message (required by Slack API).
            blocks: Optional list of Slack Block Kit block objects.

        Returns:
            Parsed JSON response from Slack, or ``{"ok": true}`` if the
            response body is the plain-text string ``"ok"``.
        """
        payload: dict = {"text": text}
        if blocks is not None:
            payload["blocks"] = blocks

        response = await self._client.post(self.webhook_url, json=payload)
        response.raise_for_status()

        # Slack webhooks respond with plain "ok" on success
        body = response.text.strip()
        if body == "ok":
            return {"ok": True}
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
