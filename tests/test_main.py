"""Startup: project seeding."""

from __future__ import annotations

from autodev.core.config import AutodevConfig, ProjectSpec, RepoSpec
from autodev.core.models import Project
from autodev.main import seed_projects


async def test_seed_inserts_missing_and_keeps_existing(session_factory) -> None:
    cfg = AutodevConfig(
        projects=[ProjectSpec(slug="shop", name="Shop", repos=[RepoSpec(name="acme/shop", setup="npm ci")])]
    )
    await seed_projects(session_factory, cfg)
    async with session_factory() as s:
        p = await s.get(Project, "shop")
        assert p.repos == [{"name": "acme/shop", "role": "app", "setup": "npm ci"}]
        p.name = "Edited in dashboard"
        await s.commit()

    await seed_projects(session_factory, cfg)
    async with session_factory() as s:
        assert (await s.get(Project, "shop")).name == "Edited in dashboard"
