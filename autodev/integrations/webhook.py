"""Generic webhook integration — POST JSON events to arbitrary HTTP endpoints.

Useful for integrating with custom services, CI/CD pipelines, or any HTTP
receiver that expects structured event payloads.

TODO: Add HMAC-SHA256 request signing support.
TODO: Add retry logic with exponential backoff.
TODO: Add configurable timeout per notifier.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Async generic webhook notifier.

    Sends a JSON POST request to a configurable URL whenever an event occurs.

    Args:
        url: Target HTTP(S) endpoint URL.
        headers: Optional extra HTTP headers to include in every request
            (e.g. ``{"Authorization": "Bearer <token>"}``)
    """

    def __init__(self, url: str, headers: dict | None = None) -> None:
        self.url = url
        self._headers = headers or {}
        self._client = httpx.AsyncClient(headers=self._headers)

    async def send(self, event_type: str, payload: dict) -> dict:
        """Send an event payload to the webhook endpoint.

        Args:
            event_type: Logical event name (e.g. ``"pr.created"``).
            payload: Arbitrary event data to include in the request body.

        Returns:
            Parsed JSON response from the endpoint.
        """
        body = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
        response = await self._client.post(self.url, json=body)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
