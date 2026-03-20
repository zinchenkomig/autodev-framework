"""FastAPI application factory.

Creates and configures the main ASGI application, registers routers,
sets up middleware, and wires lifecycle events.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autodev.api.database import SessionLocal, engine
from autodev.api.routes import agents, events, releases, tasks, webhooks
from autodev.api.routes import metrics as metrics_router
from autodev.api.routes import pm as pm_router
from autodev.api.routes import tester as tester_router
from autodev.api.websocket import router as ws_router
from autodev.core.models import Agent, AgentStatus, Base

logger = logging.getLogger(__name__)


async def register_agents_from_config(config_path: str) -> None:
    """Upsert agents defined in *config_path* into the database."""
    try:
        from autodev.core.config import load_config

        cfg = load_config(config_path)
        async with SessionLocal() as session:
            for agent_cfg in cfg.agents:
                agent_id = agent_cfg.role
                existing = await session.get(Agent, agent_id)
                if existing is None:
                    agent = Agent(
                        id=agent_id,
                        role=agent_cfg.role,
                        status=AgentStatus.IDLE,
                    )
                    session.add(agent)
                    logger.info("Auto-registered agent: %s", agent_id)
                else:
                    logger.debug("Agent already registered: %s", agent_id)
            await session.commit()
    except Exception as exc:
        logger.warning("Could not auto-register agents from %s: %s", config_path, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup, clean up engine on shutdown."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")

    # Auto-register agents from config if available
    config_path = os.environ.get("AUTODEV_CONFIG", "autodev.yaml")
    if Path(config_path).exists():
        await register_agents_from_config(config_path)

    yield
    await engine.dispose()
    logger.info("Database engine disposed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AutoDev Framework API",
        description="REST API for the autonomous multi-agent development platform.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — allow dashboard origin and localhost dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "*",  # TODO: restrict to known origins in production
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
    app.include_router(agents.router, prefix="/agents", tags=["agents"])
    app.include_router(events.router, prefix="/events", tags=["events"])
    app.include_router(releases.router, prefix="/releases", tags=["releases"])
    app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(metrics_router.router, prefix="/metrics", tags=["metrics"])
    app.include_router(pm_router.router, prefix="/pm", tags=["pm"])
    app.include_router(tester_router.router, prefix="/tester", tags=["tester"])

    # WebSocket
    app.include_router(ws_router, prefix="/ws", tags=["websocket"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint."""
        return {"status": "ok"}

    logger.info("AutoDev API application created")
    return app


app = create_app()
