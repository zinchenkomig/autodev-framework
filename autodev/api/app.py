"""FastAPI application factory for the AutoDev Framework API.

This module creates and configures the main FastAPI application, including:
- API routers for tasks, agents, events, releases, webhooks, metrics, PM, tester
- WebSocket router for real-time updates
- Database setup via lifespan context manager
- Health check endpoint
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autodev.api.database import SessionLocal, engine
from autodev.api.routes import agents, events, releases, tasks, webhooks
from autodev.api.routes import metrics as metrics_router
from autodev.api.routes import pm as pm_router
from autodev.api.routes import tester as tester_router
from autodev.api.ws import router as ws_router
from autodev.core.models import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: create tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")
    
    # Sync project contexts from config
    await sync_project_contexts_from_config()
    
    yield


async def sync_project_contexts_from_config():
    """Sync project contexts from autodev.yaml on startup."""
    import yaml
    from pathlib import Path
    from uuid import uuid4
    from sqlalchemy import select
    from autodev.core.models import ProjectContext
    
    config_path = Path(os.environ.get("AUTODEV_CONFIG", "/app/autodev.yaml"))
    if not config_path.exists():
        logger.info("No autodev.yaml found, skipping context sync")
        return
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        repos_config = config.get("repos", [])
        repos = []
        for repo_config in repos_config:
            repo_url = repo_config.get("url", "")
            if "github.com/" in repo_url:
                repo = repo_url.split("github.com/")[-1]
            else:
                repo = repo_url
            if "/" in repo:
                repos.append(repo)
        
        if not repos:
            logger.info("No repos in config")
            return
        
        async with SessionLocal() as session:
            for repo in repos:
                existing = await session.scalar(
                    select(ProjectContext).where(ProjectContext.repo == repo)
                )
                if not existing:
                    ctx = ProjectContext(
                        id=uuid4(),
                        repo=repo,
                        name=repo.split("/")[-1],
                        description=f"Project from {repo} (pending analysis)",
                    )
                    session.add(ctx)
                    logger.info(f"Added project context placeholder: {repo}")
            
            await session.commit()
        
        logger.info(f"Synced {len(repos)} project contexts from config")
    except Exception as e:
        logger.warning(f"Failed to sync project contexts: {e}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AutoDev Framework API",
        description="API for the AI-powered software development framework",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(releases.router, prefix="/api/releases", tags=["releases"])
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
    app.include_router(metrics_router.router, prefix="/api/metrics", tags=["metrics"])
    app.include_router(pm_router.router, prefix="/api/pm", tags=["pm"])
    app.include_router(tester_router.router, prefix="/api/tester", tags=["tester"])

    # WebSocket
    app.include_router(ws_router, prefix="/ws", tags=["websocket"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint."""
        return {"status": "ok"}

    logger.info("AutoDev API application created")
    return app


app = create_app()
