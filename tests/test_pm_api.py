"""Tests for the PM chat API endpoints.

Uses an in-memory SQLite database — no running PostgreSQL required.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autodev.core.models import Base, Task, TaskStatus

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def app():
    """Create a fresh app instance wired to an in-memory SQLite database."""
    import autodev.api.database as db_module

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)

    original_engine = db_module.engine
    original_session = db_module.SessionLocal

    db_module.engine = test_engine
    db_module.SessionLocal = test_session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from autodev.api.app import create_app

    application = create_app()

    yield application

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()

    db_module.engine = original_engine
    db_module.SessionLocal = original_session


@pytest_asyncio.fixture(scope="function")
async def client(app):
    """Return an AsyncClient for the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Test 1: chat endpoint returns 200 for a generic task message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_creates_task(client: AsyncClient):
    """A generic message should create a task and return a 200 response."""
    resp = await client.post("/pm/chat", json={"message": "Fix the homepage crash"})
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert "tasks_created" in data
    assert len(data["tasks_created"]) >= 1
    assert data["tasks_created"][0]["title"] == "Fix the homepage crash"


# ---------------------------------------------------------------------------
# Test 2: chat endpoint returns status info when asked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_status_response(client: AsyncClient):
    """A message containing 'статус' should return a status report."""
    resp = await client.post("/pm/chat", json={"message": "Какой статус проекта?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Статус" in data["response"] or "статус" in data["response"].lower()
    assert data["tasks_created"] == []


# ---------------------------------------------------------------------------
# Test 3: 'status' keyword in English also triggers status report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_status_english(client: AsyncClient):
    """English 'status' keyword should also return a project status report."""
    resp = await client.post("/pm/chat", json={"message": "show me the status"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks_created"] == []
    assert len(data["response"]) > 0


# ---------------------------------------------------------------------------
# Test 4: 'что делать' returns task suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_suggest_tasks(client: AsyncClient):
    """Asking 'что делать дальше' should return task suggestions."""
    resp = await client.post("/pm/chat", json={"message": "что делать дальше?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks_created"] == []
    # Should mention either empty queue or suggest tasks
    assert len(data["response"]) > 0


# ---------------------------------------------------------------------------
# Test 5: suggest with pre-seeded tasks returns them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_suggest_shows_queued_tasks(app, client: AsyncClient):
    """Suggest should list queued tasks when they exist."""
    import uuid
    from datetime import UTC, datetime

    import autodev.api.database as db_module

    task = Task(
        id=uuid.uuid4(),
        title="Implement search feature",
        status=TaskStatus.QUEUED,
        priority="high",
        source="manual",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with db_module.SessionLocal() as session:
        session.add(task)
        await session.commit()

    resp = await client.post("/pm/chat", json={"message": "что делать дальше?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Implement search feature" in data["response"]


# ---------------------------------------------------------------------------
# Test 6: auth keyword triggers multi-subtask decomposition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_auth_creates_subtasks(client: AsyncClient):
    """A message with 'авторизацию' should create multiple subtasks."""
    resp = await client.post("/pm/chat", json={"message": "Добавь авторизацию в приложение"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks_created"]) >= 3
    titles = [t["title"] for t in data["tasks_created"]]
    assert any("JWT" in t or "аутентификаци" in t for t in titles)


# ---------------------------------------------------------------------------
# Test 7: GET /pm/status returns structured project status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pm_status(client: AsyncClient):
    """GET /pm/status should return a structured project status object."""
    resp = await client.get("/pm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "in_progress" in data
    assert "queued" in data
    assert "done_this_week" in data
    assert "open_bugs" in data


# ---------------------------------------------------------------------------
# Test 8: GET /pm/history returns chat history after conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_history_persisted(client: AsyncClient):
    """After sending a message, /pm/history should return the conversation."""
    await client.post("/pm/chat", json={"message": "Создай тест задачу"})
    await client.post("/pm/chat", json={"message": "Какой статус?"})

    resp = await client.get("/pm/history")
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) >= 4  # 2 user + 2 pm messages
    roles = [m["role"] for m in history]
    assert "user" in roles
    assert "pm" in roles


# ---------------------------------------------------------------------------
# Test 9: chat returns non-empty response for any input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_always_responds(client: AsyncClient):
    """Any non-empty message should always receive a non-empty response."""
    for msg in ["Hello", "?", "do something", "привет"]:
        resp = await client.post("/pm/chat", json={"message": msg})
        assert resp.status_code == 200
        assert len(resp.json()["response"]) > 0


# ---------------------------------------------------------------------------
# Test 10: chat response is valid JSON with correct shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_response_schema(client: AsyncClient):
    """Response must have 'response' (str) and 'tasks_created' (list) keys."""
    resp = await client.post("/pm/chat", json={"message": "test schema"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["response"], str)
    assert isinstance(data["tasks_created"], list)
    for task in data["tasks_created"]:
        assert "id" in task
        assert "title" in task
        assert "priority" in task
