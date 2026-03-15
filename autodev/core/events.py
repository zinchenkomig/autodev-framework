"""Event bus for inter-agent communication and domain event broadcasting.

Implements a simple publish-subscribe pattern using asyncio.
Consumers register handlers for specific event types; the bus delivers
events to all matching handlers concurrently.

TODO: Persist events to the `events` table for audit log.
TODO: Add support for external brokers (Redis Pub/Sub, NATS).
TODO: Add event schema validation via Pydantic.
TODO: Add dead-letter queue for handler failures.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for async event handlers.
EventHandler = Callable[["DomainEvent"], Awaitable[None]]


@dataclass
class DomainEvent:
    """A domain event emitted by an agent or system component.

    TODO: Add correlation_id and causation_id for tracing.
    TODO: Add schema_version for forward compatibility.
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    """Async pub-sub event bus.

    Handlers registered for a specific event type are invoked concurrently
    when an event of that type is published.

    Example::

        bus = EventBus()

        async def on_task_created(event: DomainEvent) -> None:
            print(f"New task: {event.payload}")

        bus.subscribe("task.created", on_task_created)
        await bus.publish(DomainEvent(event_type="task.created", payload={"id": 1}))
    """

    def __init__(self) -> None:
        """Initialize the event bus with an empty handler registry."""
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for the given event type.

        Args:
            event_type: The event type string to listen for.
            handler: An async callable that receives the DomainEvent.
        """
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Subscribed handler %s to %s", handler.__name__, event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a previously registered handler.

        Args:
            event_type: The event type the handler was registered for.
            handler: The handler to remove.
        """
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Publish an event to all registered handlers.

        Handlers are invoked concurrently. Exceptions are logged but do not
        interrupt delivery to other handlers.

        Args:
            event: The domain event to publish.
        """
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug("No handlers for event type %s", event.event_type)
            return

        logger.info("Publishing event %s to %d handler(s)", event.event_type, len(handlers))

        results = await asyncio.gather(
            *(h(event) for h in handlers),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Handler %s failed for event %s: %s",
                    handlers[i].__name__,
                    event.event_type,
                    result,
                )
