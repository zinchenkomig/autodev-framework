"""Starting a production release: open the project's stage→prod PR.

The worker's delivery loop then merges them once checks pass
(:func:`autodev.worker.delivery.advance_release`).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.models import Project, Release, ReleaseStatus, Task, TaskStatus
from autodev.integrations.github import GitHubClient


class ReleaseError(Exception):
    pass


async def start_release(session: AsyncSession, gh: GitHubClient, project: Project, by: str = "dashboard") -> Release:
    active = await session.scalar(
        select(Release).where(Release.project_id == project.id, Release.status == ReleaseStatus.PENDING)
    )
    if active is not None:
        raise ReleaseError(f"Release {active.version} is still in progress")

    tasks = list(
        (
            await session.execute(
                select(Task)
                .where(Task.project_id == project.id, Task.status == TaskStatus.ON_STAGE)
                .order_by(Task.ticket_number)
            )
        ).scalars()
    )

    today = datetime.now(UTC).strftime("%Y.%m.%d")
    same_day = await session.scalar(
        select(func.count())
        .select_from(Release)
        .where(Release.project_id == project.id, Release.version.like(f"{today}%"))
    )
    version = f"{today}-{(same_day or 0) + 1}"
    notes = "\n".join(f"- #{t.ticket_number} {t.title}" for t in tasks) or "- maintenance"

    name = project.repo()["name"]
    diff = await gh.compare(project.prod_branch, project.base_branch, repo=name)
    if not diff.get("ahead_by"):
        raise ReleaseError(f"{project.base_branch} has nothing new compared to {project.prod_branch}")
    title = f"Release {version}: {project.base_branch} → {project.prod_branch}"
    try:
        pr = await gh.create_pr(title=title, head=project.base_branch, base=project.prod_branch, body=notes, repo=name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 422:
            raise
        pr = await gh.find_open_pr(project.base_branch, project.prod_branch, name)
        if pr is None:
            raise ReleaseError(f"{name}: cannot open release PR: {exc.response.text[:300]}") from exc
    prs = [{"repo": name, "pr_number": pr["number"], "pr_url": pr["html_url"], "merged": False}]

    release = Release(
        project_id=project.id,
        version=version,
        status=ReleaseStatus.PENDING,
        tasks=[t.id for t in tasks],
        release_notes=notes,
        release_prs=prs,
        created_by=by,
    )
    session.add(release)
    await session.commit()
    return release
