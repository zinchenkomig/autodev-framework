"""Placeholder tests to verify CI pipeline wiring.

TODO: Replace with real unit and integration tests.
TODO: Add fixtures for database sessions, event bus, and task queue.
TODO: Add factories for test data (Faker or factory-boy).
"""

from __future__ import annotations

import pytest


def test_import_autodev() -> None:
    """Smoke test: verify the autodev package imports without error."""
    import autodev

    assert autodev.__version__ == "0.1.0"


def test_task_queue_enqueue_dequeue() -> None:
    """Smoke test: verify basic TaskQueue round-trip."""
    import asyncio

    from autodev.core.queue import QueuedTask, TaskQueue

    async def _run() -> None:
        queue = TaskQueue()
        task = QueuedTask(task_id="t1", payload={"action": "test"})
        await queue.enqueue(task)
        assert queue.size() == 1
        received = await queue.dequeue(timeout=1.0)
        assert received is not None
        assert received.task_id == "t1"
        queue.complete(received)

    asyncio.run(_run())


def test_event_bus_publish_subscribe() -> None:
    """Smoke test: verify EventBus delivers events to subscribers."""
    import asyncio

    from autodev.core.events import DomainEvent, EventBus

    received: list[DomainEvent] = []

    async def _run() -> None:
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        bus.subscribe("test.event", handler)
        await bus.publish(DomainEvent(event_type="test.event", payload={"x": 1}))

    asyncio.run(_run())
    assert len(received) == 1
    assert received[0].payload["x"] == 1


@pytest.mark.asyncio
async def test_state_manager_set_get() -> None:
    """Verify StateManager stores and retrieves values correctly."""
    from autodev.core.state import StateManager

    state = StateManager()
    await state.set("system.phase", "running")
    value = await state.get("system.phase")
    assert value == "running"

    missing = await state.get("no.such.key", default="fallback")
    assert missing == "fallback"
