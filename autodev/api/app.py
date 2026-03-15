"""FastAPI application factory.

Creates and configures the main ASGI application, registers routers,
sets up middleware, and wires lifecycle events.

TODO: Add authentication middleware (JWT or API key).
TODO: Add request ID / tracing middleware.
TODO: Add rate limiting middleware.
TODO: Add OpenTelemetry instrumentation.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autodev.api.routes import agents, events, releases, tasks, webhooks
from autodev.api.routes import metrics as metrics_router
from autodev.api.websocket import router as ws_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance ready to serve.

    TODO: Load config from ProjectConfig and apply to app settings.
    TODO: Register database startup/shutdown lifecycle hooks.
    TODO: Register EventBus and TaskQueue as app state.
    """
    app = FastAPI(
        title="AutoDev Framework API",
        description="REST API for the autonomous multi-agent development platform.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — tighten in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: restrict to known origins
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
    app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
    app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
    app.include_router(releases.router, prefix="/api/v1/releases", tags=["releases"])
    app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
    app.include_router(metrics_router.router, prefix="/api/metrics", tags=["metrics"])

    # WebSocket
    app.include_router(ws_router, prefix="/ws", tags=["websocket"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint."""
        return {"status": "ok"}

    logger.info("AutoDev API application created")
    return app


app = create_app()
