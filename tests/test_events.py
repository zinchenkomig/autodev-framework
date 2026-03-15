"""Tests for the EventBus implementation.

Covers: emit, subscribe, unsubscribe, wildcard routing, prefix routing,
DB persistence, get_events pagination/filtering.

Uses an in-memory SQLite database (via aiosqlite) so no external Postgres
instance is required.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from autodev.core.events import EventBus, EventTypes, _matches
from autodev.core.models import Base, Event

# ---------------------------------------------------------------------------
# In-memory DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_session_factory():
    """Create an in-memory SQLite engine and yield an async_sessionmaker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture()
def bus():
    """EventBus without DB persistence."""
    return EventBus()


@pytest.fixture()
async def db_bus(db_session_factory):
    """EventBus with in-memory SQLite DB."""
    return EventBus(session_factory=db_session_factory)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_handler(calls: list):
    """Return a coroutine handler that appends received events to *calls*."""

    async def handler(event: Event) -> None:
        calls.append(event)

    return handler


# ---------------------------------------------------------------------------
# Pattern matching unit tests
# ---------------------------------------------------------------------------


class TestMatchesHelper:
    def test_exact_match(self):
        assert _matches("task.created", "task.created") is True

    def test_exact_no_match(self):
        assert _matches("task.created", "task.assigned") is False

    def test_wildcard_star_matches_all(self):
        assert _matches("*", "task.created") is True
        assert _matches("*", "pr.merged") is True
        assert _matches("*", "agent.idle") is True

    def test_prefix_matches_sub_events(self):
        assert _matches("task.*", "task.created") is True
        assert _matches("task.*", "task.assigned") is True
        assert _matches("task.*", "task.completed") is True
        assert _matches("task.*", "task.failed") is True

    def test_prefix_no_match_different_namespace(self):
        assert _matches("task.*", "pr.created") is False
        assert _matches("pr.*", "task.created") is False

    def test_prefix_no_match_partial(self):
        # "taskx.created" should NOT match "task.*"
        assert _matches("task.*", "taskx.created") is False


# ---------------------------------------------------------------------------
# Subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribeUnsubscribe:
    async def test_subscribe_registers_handler(self, bus: EventBus):
        calls: list = []
        bus.subscribe("task.created", make_handler(calls))
        assert len(bus._handlers["task.created"]) == 1

    async def test_unsubscribe_removes_handler(self, bus: EventBus):
        calls: list = []
        handler = make_handler(calls)
        bus.subscribe("task.created", handler)
        bus.unsubscribe("task.created", handler)
        assert bus._handlers["task.created"] == []

    async def test_unsubscribe_nonexistent_is_noop(self, bus: EventBus):
        """Unsubscribing a handler that was never registered should not raise."""
        calls: list = []
        handler = make_handler(calls)
        bus.unsubscribe("task.created", handler)  # should not raise

    async def test_multiple_handlers_for_same_type(self, bus: EventBus):
        calls_a: list = []
        calls_b: list = []
        bus.subscribe("task.created", make_handler(calls_a))
        bus.subscribe("task.created", make_handler(calls_b))
        await bus.emit("task.created", payload={"id": 1})
        assert len(calls_a) == 1
        assert len(calls_b) == 1


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


class TestEmit:
    async def test_emit_returns_event_object(self, bus: EventBus):
        event = await bus.emit("task.created", payload={"id": 42})
        assert isinstance(event, Event)
        assert event.type == "task.created"
        assert event.payload == {"id": 42}

    async def test_emit_with_source(self, bus: EventBus):
        event = await bus.emit("task.created", payload={}, source="pm-agent")
        assert event.source == "pm-agent"

    async def test_emit_delivers_to_handler(self, bus: EventBus):
        calls: list = []
        bus.subscribe("task.created", make_handler(calls))
        await bus.emit("task.created", payload={"title": "New feature"})
        assert len(calls) == 1
        assert calls[0].payload == {"title": "New feature"}

    async def test_emit_no_handlers_no_error(self, bus: EventBus):
        """Emitting with no handlers registered should not raise."""
        event = await bus.emit("unknown.event", payload={})
        assert event.type == "unknown.event"

    async def test_emit_handler_exception_does_not_propagate(self, bus: EventBus):
        """A failing handler must not prevent emit from returning normally."""

        async def bad_handler(event: Event) -> None:
            raise ValueError("boom")

        bus.subscribe("task.failed", bad_handler)
        # Should not raise — exception is swallowed and logged
        event = await bus.emit("task.failed", payload={})
        assert event.type == "task.failed"


# ---------------------------------------------------------------------------
# Wildcard and prefix routing
# ---------------------------------------------------------------------------


class TestRouting:
    async def test_wildcard_receives_all_events(self, bus: EventBus):
        calls: list = []
        bus.subscribe("*", make_handler(calls))
        await bus.emit("task.created", payload={})
        await bus.emit("pr.merged", payload={})
        await bus.emit("agent.idle", payload={})
        assert len(calls) == 3

    async def test_prefix_receives_matching_events(self, bus: EventBus):
        calls: list = []
        bus.subscribe("task.*", make_handler(calls))
        await bus.emit("task.created", payload={})
        await bus.emit("task.assigned", payload={})
        await bus.emit("task.completed", payload={})
        await bus.emit("pr.created", payload={})  # should NOT match
        assert len(calls) == 3

    async def test_exact_and_wildcard_both_receive(self, bus: EventBus):
        exact_calls: list = []
        wildcard_calls: list = []
        bus.subscribe("task.created", make_handler(exact_calls))
        bus.subscribe("*", make_handler(wildcard_calls))
        await bus.emit("task.created", payload={"id": 1})
        assert len(exact_calls) == 1
        assert len(wildcard_calls) == 1

    async def test_prefix_and_exact_both_receive(self, bus: EventBus):
        prefix_calls: list = []
        exact_calls: list = []
        bus.subscribe("pr.*", make_handler(prefix_calls))
        bus.subscribe("pr.created", make_handler(exact_calls))
        await bus.emit("pr.created", payload={})
        assert len(prefix_calls) == 1
        assert len(exact_calls) == 1


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


class TestDBPersistence:
    async def test_emit_persists_event_to_db(self, db_bus: EventBus, db_session_factory):
        await db_bus.emit("task.created", payload={"title": "Issue 20"}, source="pm")
        async with db_session_factory() as session:
            from sqlalchemy import select

            result = await session.execute(select(Event))
            events = result.scalars().all()
        assert len(events) == 1
        assert events[0].type == "task.created"
        assert events[0].payload == {"title": "Issue 20"}
        assert events[0].source == "pm"

    async def test_emit_assigns_uuid_id_when_persisted(self, db_bus: EventBus):
        event = await db_bus.emit("pr.created", payload={})
        assert event.id is not None

    async def test_emit_without_session_factory_does_not_persist(self, bus: EventBus):
        """Bus without session_factory should still work (no DB write)."""
        event = await bus.emit("task.created", payload={})
        assert event.type == "task.created"
        # id is set by ORM default regardless of DB flush
        # We just verify no exception and event is returned

    async def test_get_events_returns_all(self, db_bus: EventBus):
        await db_bus.emit("task.created", payload={"n": 1})
        await db_bus.emit("task.assigned", payload={"n": 2})
        await db_bus.emit("pr.created", payload={"n": 3})
        events = await db_bus.get_events()
        assert len(events) == 3

    async def test_get_events_filter_by_type(self, db_bus: EventBus):
        await db_bus.emit("task.created", payload={})
        await db_bus.emit("task.created", payload={})
        await db_bus.emit("pr.merged", payload={})
        events = await db_bus.get_events(event_type="task.created")
        assert len(events) == 2
        assert all(e.type == "task.created" for e in events)

    async def test_get_events_pagination(self, db_bus: EventBus):
        for i in range(5):
            await db_bus.emit("agent.idle", payload={"i": i})
        page1 = await db_bus.get_events(limit=3, offset=0)
        page2 = await db_bus.get_events(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

    async def test_get_events_raises_without_session_factory(self, bus: EventBus):
        with pytest.raises(RuntimeError, match="session_factory"):
            await bus.get_events()

    async def test_handler_receives_persisted_event(self, db_bus: EventBus):
        """Handler should receive the same Event ORM object that was persisted."""
        received: list = []
        db_bus.subscribe("task.completed", make_handler(received))
        await db_bus.emit("task.completed", payload={"task_id": "xyz"})
        assert len(received) == 1
        assert received[0].type == "task.completed"
        assert received[0].payload == {"task_id": "xyz"}


# ---------------------------------------------------------------------------
# EventTypes constants
# ---------------------------------------------------------------------------


class TestEventTypes:
    def test_task_event_types(self):
        assert EventTypes.TASK_CREATED == "task.created"
        assert EventTypes.TASK_ASSIGNED == "task.assigned"
        assert EventTypes.TASK_COMPLETED == "task.completed"
        assert EventTypes.TASK_FAILED == "task.failed"

    def test_pr_event_types(self):
        assert EventTypes.PR_CREATED == "pr.created"
        assert EventTypes.PR_MERGED == "pr.merged"
        assert EventTypes.PR_CI_PASSED == "pr.ci.passed"
        assert EventTypes.PR_CI_FAILED == "pr.ci.failed"

    def test_deploy_event_types(self):
        assert EventTypes.DEPLOY_STAGING == "deploy.staging"
        assert EventTypes.DEPLOY_PRODUCTION == "deploy.production"

    def test_review_and_release_event_types(self):
        assert EventTypes.BUG_FOUND == "bug.found"
        assert EventTypes.REVIEW_PASSED == "review.passed"
        assert EventTypes.REVIEW_FAILED == "review.failed"
        assert EventTypes.RELEASE_READY == "release.ready"
        assert EventTypes.RELEASE_APPROVED == "release.approved"

    def test_agent_event_types(self):
        assert EventTypes.AGENT_IDLE == "agent.idle"
        assert EventTypes.AGENT_FAILED == "agent.failed"

    async def test_event_types_used_in_emit(self):
        """EventTypes constants can be used directly with EventBus."""
        bus = EventBus()
        calls: list = []
        bus.subscribe(EventTypes.TASK_CREATED, make_handler(calls))
        await bus.emit(EventTypes.TASK_CREATED, payload={"via": "constant"})
        assert len(calls) == 1
