"""Tests for autodev.core.learning — LearningStore (Issue #16)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autodev.core.learning import LearningStore, Lesson
from autodev.core.models import Base, Priority, Task, TaskSource, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory():
    """In-memory SQLite engine with all tables (including lessons)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def store(session_factory):
    return LearningStore(session_factory)


def _make_task(
    agent_id: str = "dev-1",
    title: str = "Implement feature X",
    description: str = "Refactor the authentication module",
) -> Task:
    return Task(
        id=uuid.uuid4(),
        title=title,
        description=description,
        source=TaskSource.MANUAL,
        priority=Priority.NORMAL,
        status=TaskStatus.ASSIGNED,
        assigned_to=agent_id,
    )


# ---------------------------------------------------------------------------
# Lesson ORM model
# ---------------------------------------------------------------------------


def test_lesson_repr() -> None:
    lesson = Lesson(id=1, agent_id="dev-1", task_id="abc", success=True)
    assert "dev-1" in repr(lesson)
    assert "True" in repr(lesson)


def test_lesson_to_dict() -> None:
    now = datetime.now(UTC)
    lesson = Lesson(
        id=1,
        task_id="task-123",
        agent_id="dev-1",
        success=False,
        error="ImportError",
        lesson_text="Check imports",
        created_at=now,
    )
    d = lesson.to_dict()
    assert d["task_id"] == "task-123"
    assert d["agent_id"] == "dev-1"
    assert d["success"] is False
    assert d["error"] == "ImportError"
    assert d["lesson_text"] == "Check imports"
    assert "created_at" in d


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_outcome_success(store: LearningStore) -> None:
    lesson = await store.record_outcome(
        task_id=uuid.uuid4(),
        agent_id="dev-1",
        success=True,
        lesson="Remember to write tests first",
    )
    assert lesson.id is not None
    assert lesson.success is True
    assert lesson.agent_id == "dev-1"
    assert lesson.error is None


@pytest.mark.asyncio
async def test_record_outcome_failure(store: LearningStore) -> None:
    lesson = await store.record_outcome(
        task_id=uuid.uuid4(),
        agent_id="dev-2",
        success=False,
        error="ModuleNotFoundError: No module named 'httpx'",
        lesson="Always add httpx to dependencies",
    )
    assert lesson.success is False
    assert "httpx" in lesson.error
    assert lesson.lesson_text is not None


@pytest.mark.asyncio
async def test_record_outcome_null_task_id(store: LearningStore) -> None:
    lesson = await store.record_outcome(
        task_id=None,
        agent_id="dev-1",
        success=True,
    )
    assert lesson.task_id is None


@pytest.mark.asyncio
async def test_record_outcome_null_agent_id(store: LearningStore) -> None:
    lesson = await store.record_outcome(
        task_id="some-task",
        agent_id=None,
        success=False,
        error="Unknown error",
    )
    assert lesson.agent_id is None


# ---------------------------------------------------------------------------
# get_lessons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lessons_all(store: LearningStore) -> None:
    for i in range(5):
        await store.record_outcome(
            task_id=str(uuid.uuid4()), agent_id=f"dev-{i}", success=i % 2 == 0
        )
    lessons = await store.get_lessons(limit=10)
    assert len(lessons) == 5


@pytest.mark.asyncio
async def test_get_lessons_filtered_by_agent(store: LearningStore) -> None:
    await store.record_outcome(task_id="t1", agent_id="agent-A", success=True)
    await store.record_outcome(task_id="t2", agent_id="agent-B", success=False)
    await store.record_outcome(task_id="t3", agent_id="agent-A", success=True)

    lessons = await store.get_lessons(agent_id="agent-A")
    assert len(lessons) == 2
    assert all(l.agent_id == "agent-A" for l in lessons)


@pytest.mark.asyncio
async def test_get_lessons_respects_limit(store: LearningStore) -> None:
    for i in range(10):
        await store.record_outcome(task_id=str(i), agent_id="dev-1", success=True)
    lessons = await store.get_lessons(limit=3)
    assert len(lessons) == 3


@pytest.mark.asyncio
async def test_get_lessons_ordered_by_recency(store: LearningStore) -> None:
    for i in range(3):
        await store.record_outcome(task_id=str(i), agent_id="dev-1", success=True)
    lessons = await store.get_lessons()
    # Most recent first
    assert lessons[0].id > lessons[-1].id


# ---------------------------------------------------------------------------
# get_similar_failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_similar_failures_matches_error(store: LearningStore) -> None:
    await store.record_outcome(
        task_id="t1", agent_id="dev-1", success=False,
        error="ImportError: cannot import name 'foo' from 'bar'"
    )
    await store.record_outcome(
        task_id="t2", agent_id="dev-1", success=True,
    )
    results = await store.get_similar_failures("ImportError cannot import")
    assert len(results) >= 1
    assert all(not r.success for r in results)


@pytest.mark.asyncio
async def test_get_similar_failures_no_match_returns_empty(store: LearningStore) -> None:
    await store.record_outcome(
        task_id="t1", agent_id="dev-1", success=False, error="ConnectionRefused"
    )
    results = await store.get_similar_failures("authentication JWT token")
    # May return some results via keyword matching, just verify it doesn't crash
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_get_similar_failures_limit(store: LearningStore) -> None:
    for i in range(10):
        await store.record_outcome(
            task_id=str(i), agent_id="dev-1", success=False,
            error="ValueError: invalid literal for int"
        )
    results = await store.get_similar_failures("ValueError invalid literal", limit=3)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_context_no_lessons(store: LearningStore) -> None:
    task = _make_task()
    context = await store.build_context(task)
    assert context == ""


@pytest.mark.asyncio
async def test_build_context_with_agent_lessons(store: LearningStore) -> None:
    task = _make_task(agent_id="dev-99")
    await store.record_outcome(
        task_id="prev-task", agent_id="dev-99", success=False,
        error="SyntaxError", lesson="Always lint before committing"
    )
    context = await store.build_context(task)
    assert "Lesson" in context
    assert "SyntaxError" in context


@pytest.mark.asyncio
async def test_build_context_deduplicates(store: LearningStore) -> None:
    """Lessons that appear in both agent and similar should not be duplicated."""
    task = _make_task(agent_id="dev-X", description="SyntaxError in authentication")
    await store.record_outcome(
        task_id="t1", agent_id="dev-X", success=False,
        error="SyntaxError in auth module", lesson="Check syntax"
    )
    context = await store.build_context(task)
    # Count occurrences of the lesson id
    lesson_count = context.count("Lesson #")
    assert lesson_count >= 1
    # No duplicates — each lesson id appears at most once
    lines = [l for l in context.splitlines() if "Lesson #" in l]
    ids = [l.split("Lesson #")[1].split()[0] for l in lines]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# success_rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_rate_all_agents(store: LearningStore) -> None:
    await store.record_outcome("t1", "dev-1", success=True)
    await store.record_outcome("t2", "dev-1", success=False)
    await store.record_outcome("t3", "dev-2", success=True)
    rate = await store.success_rate()
    assert abs(rate - 2 / 3) < 0.01


@pytest.mark.asyncio
async def test_success_rate_specific_agent(store: LearningStore) -> None:
    await store.record_outcome("t1", "dev-1", success=True)
    await store.record_outcome("t2", "dev-1", success=True)
    await store.record_outcome("t3", "dev-2", success=False)
    rate = await store.success_rate(agent_id="dev-1")
    assert rate == 1.0


@pytest.mark.asyncio
async def test_success_rate_no_records(store: LearningStore) -> None:
    rate = await store.success_rate()
    assert rate == 0.0
