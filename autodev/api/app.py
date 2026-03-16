"""FastAPI application factory.

Creates and configures the main ASGI application, registers routers,
sets up middleware, and wires lifecycle events.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autodev.api.database import engine
from autodev.api.routes import agents, events, releases, tasks, webhooks
from autodev.api.routes import metrics as metrics_router
from autodev.api.routes import pm as pm_router
from autodev.api.websocket import router as ws_router
from autodev.core.models import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup, clean up engine on shutdown."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")
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

    # WebSocket
    app.include_router(ws_router, prefix="/ws", tags=["websocket"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint."""
        return {"status": "ok"}

    logger.info("AutoDev API application created")
    return app


app = create_app()
