"""FastAPI application factory for the AutoDev Framework API.

This module creates and configures the main FastAPI application, including:
- API routers for tasks, agents, events, releases, webhooks, PM
- WebSocket router for real-time updates
- Health check endpoint
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autodev.api.middleware import ErrorAlertMiddleware
from autodev.api.routes import agents, events, projects, releases, tasks, webhooks
from autodev.api.routes import pm as pm_router
from autodev.api.websocket import router as ws_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AutoDev Framework API",
        description="API for the AI-powered software development framework",
        version="2.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error alert middleware
    app.add_middleware(ErrorAlertMiddleware)

    # Routers
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(releases.router, prefix="/api/releases", tags=["releases"])
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
    app.include_router(pm_router.router, prefix="/api/pm", tags=["pm"])

    from autodev.api.routes import alerts as alerts_router
    from autodev.api.routes import settings as settings_router

    app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
    app.include_router(alerts_router.router, prefix="/api/alerts", tags=["alerts"])

    # WebSocket
    app.include_router(ws_router, prefix="/ws", tags=["websocket"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint."""
        return {"status": "ok"}

    logger.info("AutoDev API application created")
    return app


app = create_app()
