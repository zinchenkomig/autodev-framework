"""Shared test configuration.

Tests that touch the database run against a real PostgreSQL instance
(the models use PG-only features such as sequences). Point
``TEST_DATABASE_URL`` at a disposable database; CI provides one as a
service container.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://autodev:autodev@localhost:5432/autodev_test",
)


def make_test_engine() -> AsyncEngine:
    """Engine without pooling so connections never outlive an event loop."""
    return create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
