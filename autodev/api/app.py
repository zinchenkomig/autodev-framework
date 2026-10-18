"""FastAPI application factory for the AutoDev Framework API.

This module creates and configures the main FastAPI application, including:
- API routers for status, projects, tasks, agents, releases, settings, webhooks
- Health check endpoint
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autodev.api.middleware import LOCAL_ORIGIN, ErrorAlertMiddleware, SameOriginMiddleware
from autodev.api.routes import agents, auth, projects, releases, status, tasks, webhooks

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AutoDev Framework API",
        description="API for the AI-powered software development framework",
        version="2.0.0",
    )

    # The dashboard calls the API from its own origin; CORS is only for local
    # development (next dev on another port). Project apps on sibling subdomains
    # are same-site, so they must not get credentialed cross-origin access.
    app.add_middleware(SameOriginMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOCAL_ORIGIN.pattern,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error alert middleware
    app.add_middleware(ErrorAlertMiddleware)

    # Routers
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(status.router, prefix="/api/status", tags=["status"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(releases.router, prefix="/api/releases", tags=["releases"])
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])

    from autodev.api.routes import alerts as alerts_router
    from autodev.api.routes import settings as settings_router

    app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
    app.include_router(alerts_router.router, prefix="/api/alerts", tags=["alerts"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint."""
        return {"status": "ok"}

    logger.info("AutoDev API application created")
    return app


app = create_app()
