"""Process entry point: ``python -m autodev`` / ``autodev start``.

``AUTODEV_ROLE`` picks what runs in this process:
- ``api``    — FastAPI (dashboard backend, Telegram webhook)
- ``worker`` — developer slots + delivery (needs Claude Code and git)
- ``all``    — both (local development)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import uvicorn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.config import AutodevConfig, Settings, get_settings, load_config
from autodev.core.models import Project

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def run_migrations(database_url: str) -> None:
    """Bring the schema to the latest alembic revision."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


async def seed_projects(session_factory: async_sessionmaker[AsyncSession], config: AutodevConfig) -> None:
    """Insert projects from autodev.yaml that are not in the DB yet."""
    async with session_factory() as session:
        for spec in config.projects:
            if await session.get(Project, spec.slug) is not None:
                continue
            data = spec.model_dump(exclude={"slug", "repos"})
            session.add(Project(id=spec.slug, repos=[r.model_dump(exclude_none=True) for r in spec.repos], **data))
            logger.info("seeded project %s", spec.slug)
        await session.commit()
        count = len((await session.execute(select(Project.id))).all())
    logger.info("%d project(s) configured", count)


async def serve_api(settings: Settings) -> None:
    from autodev.api.app import app
    from autodev.integrations.telegram_pm import sync_commands

    await sync_commands()
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info"))
    await server.serve()


async def run_worker(settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> None:
    from autodev.worker.context import WorkerContext
    from autodev.worker.loop import Worker

    await Worker(WorkerContext(settings=settings, session_factory=session_factory)).run()


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


async def main() -> None:
    setup_logging()
    settings = get_settings()
    if settings.role not in ("api", "worker", "all"):
        raise SystemExit(f"AUTODEV_ROLE must be api, worker or all (got {settings.role!r})")

    await asyncio.to_thread(run_migrations, settings.database_url)
    setup_logging()  # alembic's fileConfig resets the root logger

    from autodev.api.database import SessionLocal

    await seed_projects(SessionLocal, load_config(settings.config_path))

    jobs = []
    if settings.role in ("api", "all"):
        jobs.append(serve_api(settings))
    if settings.role in ("worker", "all"):
        jobs.append(run_worker(settings, SessionLocal))
    logger.info("AutoDev starting (role=%s)", settings.role)
    await asyncio.gather(*jobs)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
