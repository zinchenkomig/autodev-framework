"""Integration tests for the AutoDev Framework REST API.

Uses httpx.AsyncClient with ASGITransport and an in-memory SQLite database
so no running PostgreSQL is required.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autodev.core.models import Agent, AgentStatus, Base

# ---------------------------------------------------------------------------
# Test database setup — SQLite in-memory
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def app():
    """Create a fresh app instance wired to an in-memory SQLite database."""
    import autodev.api.database as db_module

    # Swap out the engine and session factory for in-memory SQLite
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)

    original_engine = db_module.engine
    original_session = db_module.SessionLocal

    db_module.engine = test_engine
    db_module.SessionLocal = test_session

    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from autodev.api.app import create_app

    application = create_app()

    yield application

    # Teardown
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
# Helper: seed an agent directly via session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def seeded_agent(app):
    """Seed a test agent in the database and return its id."""
    import autodev.api.database as db_module

    agent = Agent(id="test-developer", role="developer", status=AgentStatus.IDLE)
    async with db_module.SessionLocal() as session:
        session.add(agent)
        await session.commit()
    return "test-developer"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tasks endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_empty(client: AsyncClient):
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_task(client: AsyncClient):
    payload = {"title": "Test task", "description": "A test", "priority": "high"}
    response = await client.post("/api/v1/tasks/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test task"
    assert data["priority"] == "high"
    assert data["status"] == "queued"
    assert "id" in data
    # id should be a valid UUID
    uuid.UUID(data["id"])


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient):
    response = await client.get(f"/api/v1/tasks/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_task(client: AsyncClient):
    # Create first
    create_resp = await client.post("/api/v1/tasks/", json={"title": "Find me"})
    task_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Find me"


@pytest.mark.asyncio
async def test_update_task(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks/", json={"title": "Original"})
    task_id = create_resp.json()["id"]

    patch_resp = await client.patch(f"/api/v1/tasks/{task_id}", json={"status": "in_progress"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks/", json={"title": "Delete me"})
    task_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks_with_filters(client: AsyncClient):
    await client.post("/api/v1/tasks/", json={"title": "High prio", "priority": "high"})
    await client.post("/api/v1/tasks/", json={"title": "Low prio", "priority": "low"})

    response = await client.get("/api/v1/tasks/?priority=high")
    assert response.status_code == 200
    data = response.json()
    assert all(t["priority"] == "high" for t in data)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Agents endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_empty(client: AsyncClient):
    response = await client.get("/api/v1/agents/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient, seeded_agent: str):
    response = await client.get("/api/v1/agents/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    ids = [a["id"] for a in data]
    assert seeded_agent in ids


@pytest.mark.asyncio
async def test_trigger_agent(client: AsyncClient, seeded_agent: str):
    response = await client.post(f"/api/v1/agents/{seeded_agent}/trigger")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == seeded_agent
    assert "event_id" in data


@pytest.mark.asyncio
async def test_trigger_agent_not_found(client: AsyncClient):
    response = await client.post("/api/v1/agents/nonexistent/trigger")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Events endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_empty(client: AsyncClient):
    response = await client.get("/api/v1/events/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_trigger_creates_event(client: AsyncClient, seeded_agent: str):
    await client.post(f"/api/v1/agents/{seeded_agent}/trigger")
    response = await client.get("/api/v1/events/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(e["type"] == "agent.triggered" for e in data)


@pytest.mark.asyncio
async def test_list_events_filter_by_type(client: AsyncClient, seeded_agent: str):
    await client.post(f"/api/v1/agents/{seeded_agent}/trigger")
    response = await client.get("/api/v1/events/?type=agent.triggered")
    assert response.status_code == 200
    data = response.json()
    assert all(e["type"] == "agent.triggered" for e in data)


# ---------------------------------------------------------------------------
# Releases endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_releases_empty(client: AsyncClient):
    response = await client.get("/api/v1/releases/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_release(client: AsyncClient):
    payload = {"version": "v1.0.0", "release_notes": "Initial release"}
    response = await client.post("/api/v1/releases/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["version"] == "v1.0.0"
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_get_release(client: AsyncClient):
    create_resp = await client.post("/api/v1/releases/", json={"version": "v2.0.0"})
    release_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/v1/releases/{release_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["version"] == "v2.0.0"


@pytest.mark.asyncio
async def test_approve_release(client: AsyncClient):
    create_resp = await client.post("/api/v1/releases/", json={"version": "v3.0.0"})
    release_id = create_resp.json()["id"]

    approve_resp = await client.post(
        f"/api/v1/releases/{release_id}/approve",
        json={"approved_by": "admin"},
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["status"] == "approved"
    assert data["approved_by"] == "admin"
    assert data["approved_at"] is not None


@pytest.mark.asyncio
async def test_get_release_not_found(client: AsyncClient):
    response = await client.get(f"/api/v1/releases/{uuid.uuid4()}")
    assert response.status_code == 404
