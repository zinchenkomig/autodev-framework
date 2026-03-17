"""Tests for GitHub Issues import endpoint.

Uses an in-memory SQLite database and mocks httpx calls — no live GitHub API needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autodev.core.models import Base

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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Sample GitHub Issues fixture
# ---------------------------------------------------------------------------

SAMPLE_ISSUES: list[dict[str, Any]] = [
    {
        "number": 1,
        "title": "Fix login crash",
        "body": "App crashes on login page.",
        "html_url": "https://github.com/owner/repo/issues/1",
        "labels": [{"name": "bug"}],
        "pull_request": None,  # not a PR
    },
    {
        "number": 2,
        "title": "Add dark mode",
        "body": "Users want dark mode support.",
        "html_url": "https://github.com/owner/repo/issues/2",
        "labels": [{"name": "enhancement"}],
        "pull_request": None,
    },
    {
        "number": 3,
        "title": "Refactor DB layer",
        "body": None,  # body can be null
        "html_url": "https://github.com/owner/repo/issues/3",
        "labels": [],
        "pull_request": None,
    },
]

PR_ISSUE = {
    "number": 10,
    "title": "PR: bump deps",
    "body": "Updating dependencies.",
    "html_url": "https://github.com/owner/repo/pull/10",
    "labels": [],
    "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
}


def _mock_github_response(issues: list[dict], status_code: int = 200):
    """Build a mock httpx response for GitHub API."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = issues
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_tasks(client):
    """Happy path: 3 issues are imported, PR issue skipped."""
    issues_with_pr = SAMPLE_ISSUES + [PR_ISSUE]

    mock_get = AsyncMock(return_value=_mock_github_response(issues_with_pr))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_cls.return_value = mock_http

        resp = await client.post(
            "/pm/import-from-github",
            json={"repo": "owner/repo", "token": "ghp_test", "state": "open"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 3  # 3 real issues, PR skipped
    assert data["skipped"] == 0
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_import_priority_bug_label(client):
    """Issues with 'bug' label should get 'high' priority."""
    mock_get = AsyncMock(return_value=_mock_github_response(SAMPLE_ISSUES))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_cls.return_value = mock_http

        resp = await client.post(
            "/pm/import-from-github",
            json={"repo": "owner/repo", "token": "ghp_test", "state": "open"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 3

    # Verify tasks in DB via tasks API
    tasks_resp = await client.get("/tasks/")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()

    bug_task = next((t for t in tasks if "login crash" in t["title"].lower()), None)
    assert bug_task is not None
    assert bug_task["priority"] == "high"

    normal_task = next((t for t in tasks if "dark mode" in t["title"].lower()), None)
    assert normal_task is not None
    assert normal_task["priority"] == "normal"


@pytest.mark.asyncio
async def test_import_deduplication(client):
    """Re-importing the same issues should skip already-existing ones."""
    mock_get = AsyncMock(return_value=_mock_github_response(SAMPLE_ISSUES))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_cls.return_value = mock_http

        # First import
        resp1 = await client.post(
            "/pm/import-from-github",
            json={"repo": "owner/repo", "token": "ghp_test", "state": "open"},
        )
        assert resp1.json()["imported"] == 3

    mock_get2 = AsyncMock(return_value=_mock_github_response(SAMPLE_ISSUES))
    with patch("httpx.AsyncClient") as mock_cls2:
        mock_http2 = AsyncMock()
        mock_http2.__aenter__ = AsyncMock(return_value=mock_http2)
        mock_http2.__aexit__ = AsyncMock(return_value=False)
        mock_http2.get = mock_get2
        mock_cls2.return_value = mock_http2

        # Second import — all should be skipped
        resp2 = await client.post(
            "/pm/import-from-github",
            json={"repo": "owner/repo", "token": "ghp_test", "state": "open"},
        )

    data2 = resp2.json()
    assert data2["imported"] == 0
    assert data2["skipped"] == 3


@pytest.mark.asyncio
async def test_import_invalid_token_returns_401(client):
    """GitHub 401 should propagate as 401 response."""
    mock_get = AsyncMock(return_value=_mock_github_response([], status_code=401))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_cls.return_value = mock_http

        resp = await client.post(
            "/pm/import-from-github",
            json={"repo": "owner/repo", "token": "bad_token", "state": "open"},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_import_repo_not_found_returns_404(client):
    """GitHub 404 should propagate as 404 response."""
    mock_get = AsyncMock(return_value=_mock_github_response([], status_code=404))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_cls.return_value = mock_http

        resp = await client.post(
            "/pm/import-from-github",
            json={"repo": "owner/nonexistent", "token": "ghp_test", "state": "open"},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_invalid_repo_format(client):
    """Repo without slash should return 400."""
    resp = await client.post(
        "/pm/import-from-github",
        json={"repo": "noslash", "token": "ghp_test", "state": "open"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_import_label_filter_passed_to_github(client):
    """Labels filter should be passed as query param to GitHub API."""
    mock_get = AsyncMock(return_value=_mock_github_response([SAMPLE_ISSUES[0]]))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_cls.return_value = mock_http

        resp = await client.post(
            "/pm/import-from-github",
            json={
                "repo": "owner/repo",
                "token": "ghp_test",
                "state": "open",
                "labels": ["bug"],
            },
        )

    assert resp.status_code == 200
    # Verify labels were passed in params
    call_kwargs = mock_get.call_args
    params = call_kwargs.kwargs.get(
        "params", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
    )
    assert "bug" in params.get("labels", "")


@pytest.mark.asyncio
async def test_pm_chat_github_keyword_suggests_import(client):
    """Mentioning 'github' or 'import' in chat should trigger import suggestion."""
    for keyword in ("импорт", "import", "github"):
        resp = await client.post(
            "/pm/chat",
            json={"message": f"Хочу {keyword} задачи"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "github" in data["response"].lower() or "импорт" in data["response"].lower()
