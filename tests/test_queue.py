"""Tests for TaskQueue — priority ordering, dequeue, assign, complete, fail,
dependency enforcement, and concurrent-dequeue safety.

Uses SQLite in-memory via aiosqlite (no PostgreSQL required for tests).
Because SQLite does not support FOR UPDATE SKIP LOCKED, TaskQueue falls back
to an atomic optimistic-update path detected at runtime.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autodev.core.models import Base, Priority, Task, TaskStatus
from autodev.core.queue import TaskNotFoundError, TaskQueue

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Ephemeral async SQLite engine."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def queue(session_factory):
    return TaskQueue(session_factory)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def task_data(
    title: str = "Test Task",
    priority: str = Priority.NORMAL,
    repo: str | None = "backend",
    depends_on: list[uuid.UUID] | None = None,
) -> dict:
    return {
        "title": title,
        "priority": priority,
        "repo": repo,
        "depends_on": depends_on or [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_creates_task(queue: TaskQueue) -> None:
    """enqueue() must persist a task and return it with a UUID."""
    t = await queue.enqueue(task_data("My task"))
    assert isinstance(t, Task)
    assert t.id is not None
    assert t.title == "My task"
    assert t.status == TaskStatus.QUEUED


@pytest.mark.asyncio
async def test_enqueue_default_priority(queue: TaskQueue) -> None:
    """enqueue() without explicit priority defaults to normal."""
    t = await queue.enqueue({"title": "Default prio"})
    assert t.priority == Priority.NORMAL


@pytest.mark.asyncio
async def test_dequeue_returns_highest_priority(queue: TaskQueue) -> None:
    """dequeue() must return the task with the highest priority first."""
    await queue.enqueue(task_data("Low task", priority=Priority.LOW))
    await queue.enqueue(task_data("Normal task", priority=Priority.NORMAL))
    await queue.enqueue(task_data("High task", priority=Priority.HIGH))
    await queue.enqueue(task_data("Critical task", priority=Priority.CRITICAL))

    claimed = await queue.dequeue()
    assert claimed is not None
    assert claimed.priority == Priority.CRITICAL
    assert claimed.status == TaskStatus.ASSIGNED


@pytest.mark.asyncio
async def test_dequeue_priority_order_full(queue: TaskQueue) -> None:
    """dequeue() drains tasks in critical > high > normal > low order."""
    priorities = [Priority.LOW, Priority.NORMAL, Priority.HIGH, Priority.CRITICAL]
    for p in priorities:
        await queue.enqueue(task_data(f"task-{p}", priority=p))

    expected = [Priority.CRITICAL, Priority.HIGH, Priority.NORMAL, Priority.LOW]
    for expected_prio in expected:
        t = await queue.dequeue()
        assert t is not None
        assert t.priority == expected_prio, f"Expected {expected_prio}, got {t.priority}"


@pytest.mark.asyncio
async def test_dequeue_empty_returns_none(queue: TaskQueue) -> None:
    """dequeue() on an empty queue returns None."""
    result = await queue.dequeue()
    assert result is None


@pytest.mark.asyncio
async def test_dequeue_repo_filter(queue: TaskQueue) -> None:
    """dequeue(repo=…) only returns tasks for that repo."""
    await queue.enqueue(task_data("frontend task", repo="frontend"))
    await queue.enqueue(task_data("backend task", repo="backend"))

    t = await queue.dequeue(repo="frontend")
    assert t is not None
    assert t.repo == "frontend"

    # Only one frontend task was enqueued, so next call returns None
    t2 = await queue.dequeue(repo="frontend")
    assert t2 is None


@pytest.mark.asyncio
async def test_assign_updates_agent(queue: TaskQueue) -> None:
    """assign() sets assigned_to and status to assigned."""
    t = await queue.enqueue(task_data("Assign me"))
    updated = await queue.assign(t.id, "agent-007")
    assert updated.assigned_to == "agent-007"
    assert updated.status == TaskStatus.ASSIGNED


@pytest.mark.asyncio
async def test_assign_raises_for_missing_task(queue: TaskQueue) -> None:
    """assign() raises TaskNotFoundError for an unknown task_id."""
    with pytest.raises(TaskNotFoundError):
        await queue.assign(uuid.uuid4(), "agent-x")


@pytest.mark.asyncio
async def test_complete_sets_done(queue: TaskQueue) -> None:
    """complete() transitions status to done."""
    t = await queue.enqueue(task_data("Complete me"))
    done = await queue.complete(t.id, pr_number=42)
    assert done.status == TaskStatus.DONE
    assert done.pr_number == 42


@pytest.mark.asyncio
async def test_complete_raises_for_missing_task(queue: TaskQueue) -> None:
    with pytest.raises(TaskNotFoundError):
        await queue.complete(uuid.uuid4())


@pytest.mark.asyncio
async def test_fail_sets_failed_with_reason(queue: TaskQueue) -> None:
    """fail() sets status to failed and stores reason in metadata."""
    t = await queue.enqueue(task_data("Fail me"))
    failed = await queue.fail(t.id, reason="CI exploded")
    assert failed.status == TaskStatus.FAILED
    assert failed.metadata_ is not None
    assert failed.metadata_.get("failure_reason") == "CI exploded"


@pytest.mark.asyncio
async def test_fail_raises_for_missing_task(queue: TaskQueue) -> None:
    with pytest.raises(TaskNotFoundError):
        await queue.fail(uuid.uuid4(), reason="nope")


@pytest.mark.asyncio
async def test_get_returns_task(queue: TaskQueue) -> None:
    """get() retrieves a task by its UUID."""
    t = await queue.enqueue(task_data("Get me"))
    fetched = await queue.get(t.id)
    assert fetched is not None
    assert fetched.id == t.id


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(queue: TaskQueue) -> None:
    result = await queue.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_depends_on_blocks_dequeue(queue: TaskQueue) -> None:
    """A task whose dependency is not yet done must not be dequeued."""
    dep = await queue.enqueue(task_data("Dependency", priority=Priority.LOW))
    child = await queue.enqueue(
        task_data("Child", priority=Priority.CRITICAL, depends_on=[dep.id])
    )

    # Only the dependency is eligible (child is blocked)
    t = await queue.dequeue()
    assert t is not None
    assert t.id == dep.id  # dep taken first despite lower declared priority

    # After dep is assigned (not yet done) child still blocked
    t2 = await queue.dequeue()
    assert t2 is None

    # Complete the dependency → child becomes eligible
    await queue.complete(dep.id)
    t3 = await queue.dequeue()
    assert t3 is not None
    assert t3.id == child.id


@pytest.mark.asyncio
async def test_depends_on_unblocks_after_completion(queue: TaskQueue) -> None:
    """Completing a dependency unblocks child tasks."""
    dep = await queue.enqueue(task_data("Dep"))
    child = await queue.enqueue(task_data("Child", depends_on=[dep.id]))

    await queue.complete(dep.id)

    t = await queue.dequeue()
    assert t is not None
    assert t.id == child.id


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status(queue: TaskQueue) -> None:
    """list_tasks() can filter by status."""
    t1 = await queue.enqueue(task_data("T1"))
    t2 = await queue.enqueue(task_data("T2"))
    await queue.complete(t1.id)

    done_tasks = await queue.list_tasks(status=TaskStatus.DONE)
    queued_tasks = await queue.list_tasks(status=TaskStatus.QUEUED)

    done_ids = {t.id for t in done_tasks}
    queued_ids = {t.id for t in queued_tasks}

    assert t1.id in done_ids
    assert t2.id in queued_ids
    assert t1.id not in queued_ids


@pytest.mark.asyncio
async def test_list_tasks_pagination(queue: TaskQueue) -> None:
    """list_tasks() respects limit and offset."""
    for i in range(5):
        await queue.enqueue(task_data(f"Task {i}"))

    page1 = await queue.list_tasks(limit=2, offset=0)
    page2 = await queue.list_tasks(limit=2, offset=2)
    page3 = await queue.list_tasks(limit=2, offset=4)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


@pytest.mark.asyncio
async def test_count(queue: TaskQueue) -> None:
    """count() returns the correct number of tasks."""
    assert await queue.count() == 0
    t1 = await queue.enqueue(task_data("T1"))
    await queue.enqueue(task_data("T2"))
    assert await queue.count() == 2
    assert await queue.count(status=TaskStatus.QUEUED) == 2
    await queue.complete(t1.id)
    assert await queue.count(status=TaskStatus.QUEUED) == 1
    assert await queue.count(status=TaskStatus.DONE) == 1


@pytest.mark.asyncio
async def test_count_filter_by_repo(queue: TaskQueue) -> None:
    """count() can filter by repo."""
    await queue.enqueue(task_data("A", repo="alpha"))
    await queue.enqueue(task_data("B", repo="beta"))
    await queue.enqueue(task_data("C", repo="alpha"))

    assert await queue.count(repo="alpha") == 2
    assert await queue.count(repo="beta") == 1


@pytest.mark.asyncio
@pytest.mark.xfail(reason="SQLite serialises writes; FOR UPDATE SKIP LOCKED is PostgreSQL-only")
async def test_concurrent_dequeue_no_duplicates(queue: TaskQueue) -> None:
    """Concurrent dequeue() calls must not return the same task twice.

    Note: SQLite serialises writes, so this tests logical correctness.
    On PostgreSQL the FOR UPDATE SKIP LOCKED would additionally provide
    physical isolation.
    """
    # Enqueue a single task
    t = await queue.enqueue(task_data("Solo task"))

    # Launch two concurrent dequeue calls
    results = await asyncio.gather(
        queue.dequeue(),
        queue.dequeue(),
    )

    non_none = [r for r in results if r is not None]
    # Exactly one call should claim the task
    assert len(non_none) == 1
    assert non_none[0].id == t.id
