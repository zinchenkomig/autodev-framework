"""Event bus for inter-agent communication and domain event broadcasting.

Implements a publish-subscribe pattern with wildcard and prefix routing,
optional DB persistence via async SQLAlchemy session factory.

Supports:
- Exact subscriptions: subscribe("task.created", handler)
- Wildcard subscriptions: subscribe("*", handler)  — receives all events
- Prefix subscriptions: subscribe("task.*", handler)  — receives task.* events
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.models import Event

logger = logging.getLogger(__name__)

# Type alias for async event handlers.
EventHandler = Callable[[Event], "Awaitable[None]"]


# ---------------------------------------------------------------------------
# Predefined event type constants
# ---------------------------------------------------------------------------


class EventTypes:
    """Predefined event type strings used across the AutoDev Framework."""

    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Pull request lifecycle
    PR_CREATED = "pr.created"
    PR_MERGED = "pr.merged"
    PR_CI_PASSED = "pr.ci.passed"
    PR_CI_FAILED = "pr.ci.failed"

    # Deployments
    DEPLOY_STAGING = "deploy.staging"
    DEPLOY_PRODUCTION = "deploy.production"

    # Quality / review
    BUG_FOUND = "bug.found"
    REVIEW_PASSED = "review.passed"
    REVIEW_FAILED = "review.failed"

    # Release
    RELEASE_READY = "release.ready"
    RELEASE_APPROVED = "release.approved"

    # Agent lifecycle
    AGENT_IDLE = "agent.idle"
    AGENT_FAILED = "agent.failed"


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


def _matches(pattern: str, event_type: str) -> bool:
    """Return True if *event_type* matches *pattern*.

    Matching rules:
    - ``"*"``  — matches every event.
    - ``"task.*"`` — matches any event whose type starts with ``"task."``.
    - Otherwise exact string equality is required.
    """
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-1]  # keep the trailing dot, e.g. "task."
        return event_type.startswith(prefix)
    return pattern == event_type


class EventBus:
    """Async pub-sub event bus with wildcard/prefix routing and optional DB logging.

    Args:
        session_factory: An async SQLAlchemy ``AsyncSession`` callable
            (e.g. ``async_sessionmaker``).  When provided, every emitted
            event is persisted to the ``events`` table.

    Example::

        bus = EventBus()

        async def on_task_created(event: Event) -> None:
            print(f"New task: {event.payload}")

        bus.subscribe("task.created", on_task_created)
        bus.subscribe("task.*", on_any_task)
        bus.subscribe("*", on_everything)

        event = await bus.emit("task.created", payload={"id": 1}, source="pm-agent")
    """

    def __init__(self, session_factory: Callable[[], AsyncSession] | None = None) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register *handler* for events matching *event_type*.

        Args:
            event_type: Exact type, prefix pattern (``"task.*"``), or ``"*"``.
            handler: Async callable that accepts a single :class:`Event` ORM object.
        """
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Subscribed %s to pattern %r", getattr(handler, "__name__", handler), event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a previously registered handler.

        Args:
            event_type: The pattern the handler was registered under.
            handler: The handler to remove.  No-op if not found.
        """
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug(
                "Unsubscribed %s from pattern %r",
                getattr(handler, "__name__", handler),
                event_type,
            )

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def emit(
        self,
        event_type: str,
        payload: dict,
        source: str = "",
    ) -> Event:
        """Publish an event, invoke all matching handlers, and optionally log to DB.

        Handlers are invoked concurrently via :func:`asyncio.gather`.
        Handler exceptions are logged but do not prevent delivery to other handlers.

        Args:
            event_type: The type string for this event.
            payload: Arbitrary JSON-serialisable data.
            source: Identifier of the emitting component (optional).

        Returns:
            The :class:`Event` ORM instance (persisted if *session_factory* was set).
        """
        event = Event(type=event_type, payload=payload, source=source or None)

        # Persist to DB if a session factory is available
        if self._session_factory is not None:
            async with self._session_factory() as session:
                session.add(event)
                await session.commit()
                await session.refresh(event)

        # Collect all handlers whose pattern matches this event_type
        matched: list[EventHandler] = []
        for pattern, handlers in self._handlers.items():
            if _matches(pattern, event_type):
                matched.extend(handlers)

        if matched:
            logger.info("Emitting %r to %d handler(s)", event_type, len(matched))
            results = await asyncio.gather(*(h(event) for h in matched), return_exceptions=True)
            for handler, result in zip(matched, results):
                if isinstance(result, Exception):
                    logger.error(
                        "Handler %s failed for event %r: %s",
                        getattr(handler, "__name__", handler),
                        event_type,
                        result,
                    )
        else:
            logger.debug("No handlers matched event type %r", event_type)

        return event

    # ------------------------------------------------------------------
    # Querying persisted events
    # ------------------------------------------------------------------

    async def get_events(
        self,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Event]:
        """Fetch persisted events from the database.

        Requires *session_factory* to have been provided at construction time.

        Args:
            event_type: Filter by exact event type; ``None`` returns all types.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip (pagination).

        Returns:
            List of :class:`Event` ORM objects ordered by ``created_at`` descending.

        Raises:
            RuntimeError: If no *session_factory* was configured.
        """
        if self._session_factory is None:
            raise RuntimeError("EventBus was created without a session_factory; cannot query DB.")

        async with self._session_factory() as session:
            stmt = select(Event).order_by(Event.created_at.desc()).limit(limit).offset(offset)
            if event_type is not None:
                stmt = stmt.where(Event.type == event_type)
            result = await session.execute(stmt)
            return list(result.scalars().all())
