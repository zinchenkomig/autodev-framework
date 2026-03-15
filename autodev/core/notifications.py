"""Notification manager — routes events to the appropriate notifiers.

Supports multiple notification backends (Telegram, Slack, Webhook) and
routes events to the configured destinations based on :class:`NotificationConfig`.

Usage::

    from autodev.core.config import NotificationConfig, NotificationTarget, NotificationType
    from autodev.core.notifications import NotificationManager
    from autodev.integrations.telegram import TelegramNotifier

    config = NotificationConfig(
        targets=[
            NotificationTarget(
                type=NotificationType.telegram,
                config={"bot_token": "...", "chat_id": "..."},
                events=["release.ready", "bug.found"],
            )
        ]
    )
    manager = NotificationManager(config)
    await manager.notify("release.ready", "Release v1.2.0 is ready!")
"""

from __future__ import annotations

import logging
from typing import Any

from autodev.core.config import NotificationConfig, NotificationType

logger = logging.getLogger(__name__)


class NotificationManager:
    """Routes notification events to registered notifier backends.

    Notifiers can be pre-registered manually via :meth:`register_notifier`,
    or they are created automatically from *config* on first use (lazy init).

    Args:
        config: :class:`~autodev.core.config.NotificationConfig` describing
            notification targets and global event filters.
    """

    def __init__(self, config: NotificationConfig) -> None:
        self._config = config
        # event_type -> list of notifier objects
        self._routes: dict[str, list[Any]] = {}
        self._initialized = False

    def register_notifier(self, event_type: str, notifier: Any) -> None:
        """Register a notifier for a specific event type.

        Multiple notifiers can be registered for the same event type — they
        will all be called when :meth:`notify` is invoked with that event.

        Args:
            event_type: Event name (e.g. ``"pr.created"``).  Use ``"*"`` to
                receive every event.
            notifier: An object with an async ``send`` method.  Typically a
                :class:`~autodev.integrations.telegram.TelegramNotifier`,
                :class:`~autodev.integrations.slack.SlackNotifier`, or
                :class:`~autodev.integrations.webhook.WebhookNotifier`.
        """
        self._routes.setdefault(event_type, []).append(notifier)

    def _build_from_config(self) -> None:
        """Lazily build notifiers from config targets."""
        if self._initialized:
            return

        for target in self._config.targets:
            cfg = target.config
            target_events: list[str] = cfg.get("events") or self._config.events or ["*"]

            try:
                notifier = self._create_notifier(target.type, cfg)
            except Exception as exc:
                logger.warning(
                    "Failed to create notifier for type %s: %s", target.type, exc
                )
                continue

            for event in target_events:
                self.register_notifier(event, notifier)

        self._initialized = True

    @staticmethod
    def _create_notifier(ntype: NotificationType, cfg: dict) -> Any:
        """Instantiate the correct notifier class for *ntype*.

        Args:
            ntype: Notification target type.
            cfg: Target-specific configuration dict.

        Returns:
            A ready-to-use notifier instance.

        Raises:
            ValueError: If required config keys are missing.
            KeyError: If an unknown type is supplied.
        """
        if ntype == NotificationType.telegram:
            from autodev.integrations.telegram import TelegramNotifier

            return TelegramNotifier(
                bot_token=cfg["bot_token"],
                chat_id=cfg["chat_id"],
            )

        if ntype == NotificationType.slack:
            from autodev.integrations.slack import SlackNotifier

            return SlackNotifier(webhook_url=cfg["webhook_url"])

        if ntype == NotificationType.webhook:
            from autodev.integrations.webhook import WebhookNotifier

            return WebhookNotifier(
                url=cfg["url"],
                headers=cfg.get("headers"),
            )

        raise ValueError(f"Unknown notification type: {ntype!r}")

    async def notify(
        self,
        event_type: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        """Send a notification to all notifiers registered for *event_type*.

        Looks up exact-match routes first, then falls back to wildcard ``"*"``
        routes.  Errors from individual notifiers are logged but do not abort
        delivery to other notifiers.

        Args:
            event_type: The event that occurred (e.g. ``"bug.found"``).
            message: Human-readable notification text.
            payload: Optional extra structured data passed to webhook notifiers.
        """
        if payload is None:
            payload = {}

        # Ensure config-based notifiers are wired up
        self._build_from_config()

        targets = list(self._routes.get(event_type, []))
        targets += [n for n in self._routes.get("*", []) if n not in targets]

        if not targets:
            logger.debug("No notifiers registered for event %r", event_type)
            return

        for notifier in targets:
            try:
                await _dispatch(notifier, event_type, message, payload)
            except Exception as exc:
                logger.error(
                    "Notifier %s failed for event %r: %s",
                    type(notifier).__name__,
                    event_type,
                    exc,
                )


async def _dispatch(notifier: Any, event_type: str, message: str, payload: dict) -> None:
    """Call the appropriate ``send`` method depending on notifier type.

    Args:
        notifier: A notifier instance.
        event_type: The event name.
        message: Human-readable text.
        payload: Structured event data.
    """
    from autodev.integrations.webhook import WebhookNotifier

    if isinstance(notifier, WebhookNotifier):
        await notifier.send(event_type=event_type, payload={"message": message, **payload})
    else:
        # TelegramNotifier, SlackNotifier — both accept (text: str)
        await notifier.send(message)
