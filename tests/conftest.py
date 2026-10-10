"""Shared test configuration.

Tests that touch the database run against a real PostgreSQL instance
(the models use PG-only features such as sequences). Point
``TEST_DATABASE_URL`` at a disposable database; CI provides one as a
service container.
"""

from __future__ import annotations

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from autodev.core.models import Base, Project

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://autodev:autodev@localhost:5432/autodev_test",
)


def make_test_engine() -> AsyncEngine:
    """Engine without pooling so connections never outlive an event loop."""
    return create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)


@pytest_asyncio.fixture
async def session_factory():
    """Fresh schema per test; also patched into autodev.api.database."""
    import autodev.api.database as db_module

    engine = make_test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    original = db_module.engine, db_module.SessionLocal
    db_module.engine, db_module.SessionLocal = engine, factory
    try:
        yield factory
    finally:
        db_module.engine, db_module.SessionLocal = original
        await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    from autodev.api.app import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_project(slug: str = "shop", repos: list[dict] | None = None, **kwargs) -> Project:
    return Project(
        id=slug,
        name=slug.title(),
        repos=repos if repos is not None else [{"name": f"acme/{slug}", "role": "app"}],
        stage_url=f"https://stage.{slug}.test",
        **kwargs,
    )


@pytest_asyncio.fixture
async def project(session_factory) -> Project:
    p = make_project()
    async with session_factory() as session:
        session.add(p)
        await session.commit()
    return p
