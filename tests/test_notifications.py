"""Tests for the notification system.

Covers TelegramNotifier, SlackNotifier, WebhookNotifier, and NotificationManager.
All HTTP calls are mocked via pytest-mock / unittest.mock so no network
requests are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autodev.core.config import NotificationConfig, NotificationTarget, NotificationType
from autodev.core.notifications import NotificationManager
from autodev.integrations.slack import SlackNotifier
from autodev.integrations.telegram import TelegramNotifier
from autodev.integrations.webhook import WebhookNotifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(json_data: dict | None = None, text: str = "ok") -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = text
    resp.json = MagicMock(return_value=json_data or {})
    return resp


# ---------------------------------------------------------------------------
# TelegramNotifier
# ---------------------------------------------------------------------------


class TestTelegramNotifier:
    @pytest.mark.asyncio
    async def test_send_html(self):
        """send() posts correct payload with HTML parse mode."""
        notifier = TelegramNotifier(bot_token="TOKEN", chat_id="123")
        mock_resp = _make_response({"ok": True, "result": {}})

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await notifier.send("Hello <b>world</b>")

        mock_post.assert_called_once_with(
            "/sendMessage",
            json={"chat_id": "123", "text": "Hello <b>world</b>", "parse_mode": "HTML"},
        )
        assert result == {"ok": True, "result": {}}

    @pytest.mark.asyncio
    async def test_send_custom_parse_mode(self):
        """send() respects a custom parse_mode argument."""
        notifier = TelegramNotifier(bot_token="TOKEN", chat_id="456")
        mock_resp = _make_response({"ok": True})

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await notifier.send("text", parse_mode="MarkdownV2")

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_send_markdown(self):
        """send_markdown() calls send() with MarkdownV2."""
        notifier = TelegramNotifier(bot_token="TOKEN", chat_id="789")
        mock_resp = _make_response({"ok": True})

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await notifier.send_markdown("*bold*")

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["parse_mode"] == "MarkdownV2"
        assert kwargs["json"]["text"] == "*bold*"

    @pytest.mark.asyncio
    async def test_send_raises_on_http_error(self):
        """send() propagates HTTP errors from raise_for_status()."""
        import httpx

        notifier = TelegramNotifier(bot_token="BAD", chat_id="0")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("400", request=MagicMock(), response=MagicMock())

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            with pytest.raises(httpx.HTTPStatusError):
                await notifier.send("oops")


# ---------------------------------------------------------------------------
# SlackNotifier
# ---------------------------------------------------------------------------


class TestSlackNotifier:
    @pytest.mark.asyncio
    async def test_send_plain_text(self):
        """send() posts text-only payload and returns {ok: True} for 'ok' body."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        mock_resp = _make_response(text="ok")

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await notifier.send("Hello Slack")

        mock_post.assert_called_once_with("https://hooks.slack.com/test", json={"text": "Hello Slack"})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_send_with_blocks(self):
        """send() includes blocks when provided."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Hi"}}]
        mock_resp = _make_response(text="ok")

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await notifier.send("fallback", blocks=blocks)

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["blocks"] == blocks

    @pytest.mark.asyncio
    async def test_send_no_blocks_key_when_none(self):
        """send() omits 'blocks' key when blocks=None."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        mock_resp = _make_response(text="ok")

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await notifier.send("text only")

        _, kwargs = mock_post.call_args
        assert "blocks" not in kwargs["json"]

    @pytest.mark.asyncio
    async def test_send_json_response(self):
        """send() returns parsed JSON when body is not plain 'ok'."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        mock_resp = _make_response(json_data={"channel": "C123"}, text='{"channel":"C123"}')

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await notifier.send("msg")

        assert result == {"channel": "C123"}


# ---------------------------------------------------------------------------
# WebhookNotifier
# ---------------------------------------------------------------------------


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_send_event(self):
        """send() POSTs event_type and payload to the configured URL."""
        notifier = WebhookNotifier(url="https://example.com/hook")
        mock_resp = _make_response({"received": True})

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await notifier.send("pr.created", {"pr": 42})

        assert result == {"received": True}
        call_kwargs = mock_post.call_args[1]
        body = call_kwargs["json"]
        assert body["event_type"] == "pr.created"
        assert body["pr"] == 42
        assert "timestamp" in body

    @pytest.mark.asyncio
    async def test_send_includes_custom_headers(self):
        """WebhookNotifier passes custom headers to the HTTP client."""
        notifier = WebhookNotifier(
            url="https://example.com/hook",
            headers={"Authorization": "Bearer secret"},
        )
        assert notifier._headers == {"Authorization": "Bearer secret"}

    @pytest.mark.asyncio
    async def test_send_returns_json(self):
        """send() returns the parsed JSON body from the server."""
        notifier = WebhookNotifier(url="https://example.com/hook")
        mock_resp = _make_response({"status": "queued"})

        with patch.object(notifier._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await notifier.send("deploy.staging", {})

        assert result["status"] == "queued"


# ---------------------------------------------------------------------------
# NotificationManager
# ---------------------------------------------------------------------------


class TestNotificationManager:
    def _make_config(self, *targets) -> NotificationConfig:
        return NotificationConfig(targets=list(targets))

    @pytest.mark.asyncio
    async def test_notify_routes_to_registered_notifier(self):
        """notify() calls send() on a manually registered notifier."""
        config = self._make_config()
        manager = NotificationManager(config)

        fake_notifier = AsyncMock()
        manager.register_notifier("pr.created", fake_notifier)

        await manager.notify("pr.created", "New PR opened")

        fake_notifier.send.assert_called_once_with("New PR opened")

    @pytest.mark.asyncio
    async def test_notify_wildcard_notifier(self):
        """Notifiers registered with '*' receive every event."""
        config = self._make_config()
        manager = NotificationManager(config)

        wildcard = AsyncMock()
        manager.register_notifier("*", wildcard)

        await manager.notify("some.event", "message")

        wildcard.send.assert_called_once_with("message")

    @pytest.mark.asyncio
    async def test_notify_no_match_is_silent(self):
        """notify() does not raise when no notifier matches the event."""
        config = self._make_config()
        manager = NotificationManager(config)
        # Should not raise
        await manager.notify("unknown.event", "quiet")

    @pytest.mark.asyncio
    async def test_notify_multiple_notifiers(self):
        """All notifiers registered for the same event are called."""
        config = self._make_config()
        manager = NotificationManager(config)

        n1, n2 = AsyncMock(), AsyncMock()
        manager.register_notifier("deploy.production", n1)
        manager.register_notifier("deploy.production", n2)

        await manager.notify("deploy.production", "Deploying!")

        n1.send.assert_called_once()
        n2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_error_in_one_notifier_does_not_abort_others(self):
        """Errors from one notifier do not prevent others from being called."""
        config = self._make_config()
        manager = NotificationManager(config)

        failing = AsyncMock()
        failing.send.side_effect = RuntimeError("boom")
        ok_notifier = AsyncMock()

        manager.register_notifier("bug.found", failing)
        manager.register_notifier("bug.found", ok_notifier)

        # Should not raise despite failing notifier
        await manager.notify("bug.found", "Bug!")

        ok_notifier.send.assert_called_once_with("Bug!")

    @pytest.mark.asyncio
    async def test_notify_builds_telegram_from_config(self):
        """NotificationManager auto-creates TelegramNotifier from config."""
        target = NotificationTarget(
            type=NotificationType.telegram,
            config={
                "bot_token": "TKN",
                "chat_id": "111",
                "events": ["release.ready"],
            },
        )
        config = NotificationConfig(targets=[target])
        manager = NotificationManager(config)

        mock_resp = _make_response({"ok": True})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await manager.notify("release.ready", "v1.0 ready")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["text"] == "v1.0 ready"

    @pytest.mark.asyncio
    async def test_notify_webhook_dispatches_with_event_type(self):
        """WebhookNotifier receives event_type and payload, not just message."""
        from autodev.integrations.webhook import WebhookNotifier

        config = self._make_config()
        manager = NotificationManager(config)

        wh = WebhookNotifier(url="https://example.com/hook")
        manager.register_notifier("pr.merged", wh)

        mock_resp = _make_response({"ok": True})
        with patch.object(wh._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await manager.notify("pr.merged", "PR #7 merged", {"pr": 7})

        body = mock_post.call_args[1]["json"]
        assert body["event_type"] == "pr.merged"
        assert body["message"] == "PR #7 merged"
        assert body["pr"] == 7
