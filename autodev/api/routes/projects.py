"""Project registry and production releases."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.api.routes.releases import ReleaseResponse, release_to_response
from autodev.core.config import RepoSpec, get_settings
from autodev.core.models import Project, Task, TaskStatus
from autodev.integrations.github import GitHubClient
from autodev.release import ReleaseError, start_release

router = APIRouter()

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class ProjectBody(BaseModel):
    name: str = Field(min_length=1)
    # One repo per project — keep several apps in a monorepo. A list for API compatibility.
    repos: list[RepoSpec] = Field(min_length=1, max_length=1)
    base_branch: str = "stage"
    prod_branch: str = "main"
    stage_url: str | None = None
    smoke_paths: list[str] = Field(default_factory=list)
    instructions: str | None = None
    model: str | None = None
    max_parallel: int = Field(default=1, ge=1, le=10)
    enabled: bool = True

    @field_validator("repos")
    @classmethod
    def _repo_names(cls, repos: list[RepoSpec]) -> list[RepoSpec]:
        for repo in repos:
            if repo.name.count("/") != 1:
                raise ValueError(f"repo name must be owner/name, got {repo.name!r}")
        return repos


class NewRepo(BaseModel):
    """Create the project's repo on GitHub instead of connecting an existing one."""

    private: bool = True
    # What to build. Becomes the project's first task: the agent lays the groundwork.
    brief: str = ""


class ProjectCreate(ProjectBody):
    id: str
    new_repo: NewRepo | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _SLUG.match(value):
            raise ValueError("id must be a lowercase slug (a-z, 0-9, -)")
        return value


class ProjectResponse(ProjectBody):
    id: str
    task_counts: dict[str, int]
    created_at: datetime
    updated_at: datetime


async def _counts(session: AsyncSession) -> dict[str, dict[str, int]]:
    rows = await session.execute(
        select(Task.project_id, Task.status, func.count()).group_by(Task.project_id, Task.status)
    )
    counts: dict[str, dict[str, int]] = {}
    for project_id, status, n in rows.all():
        counts.setdefault(project_id or "", {})[status] = n
    return counts


def to_response(project: Project, counts: dict[str, int] | None = None) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        repos=[RepoSpec(**r) for r in project.repos],
        base_branch=project.base_branch,
        prod_branch=project.prod_branch,
        stage_url=project.stage_url,
        smoke_paths=project.smoke_paths or [],
        instructions=project.instructions,
        model=project.model,
        max_parallel=project.max_parallel,
        enabled=project.enabled,
        task_counts=counts or {},
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _apply(project: Project, body: ProjectBody) -> None:
    data = body.model_dump(exclude={"repos", "new_repo"})
    for key, value in data.items():
        setattr(project, key, value)
    project.repos = [r.model_dump(exclude_none=True) for r in body.repos]


async def _load(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/", summary="List projects")
async def list_projects(session: Annotated[AsyncSession, Depends(get_session)]) -> list[ProjectResponse]:
    counts = await _counts(session)
    projects = (await session.execute(select(Project).order_by(Project.name))).scalars()
    return [to_response(p, counts.get(p.id)) for p in projects]


@router.post("/", summary="Add a project", status_code=201)
async def create_project(
    body: ProjectCreate, session: Annotated[AsyncSession, Depends(get_session)]
) -> ProjectResponse:
    if await session.get(Project, body.id) is not None:
        raise HTTPException(409, f"Project {body.id} already exists")
    if body.new_repo is not None:
        await _create_repo(body, body.new_repo)
    project = Project(id=body.id)
    _apply(project, body)
    session.add(project)
    await session.flush()
    if body.new_repo is not None and body.new_repo.brief.strip():
        session.add(
            Task(
                title="Каркас проекта",
                description=_scaffold_description(body.new_repo.brief),
                project_id=project.id,
                repo=body.repos[0].name,
                created_by="dashboard",
                status=TaskStatus.QUEUED,
                metadata_={},
            )
        )
        await session.flush()
    await session.refresh(project)
    return to_response(project, (await _counts(session)).get(project.id))


async def _create_repo(body: ProjectBody, spec: NewRepo) -> None:
    """Create the repo with its stage and prod branches, all at the initial commit."""
    name = body.repos[0].name
    async with GitHubClient(token=get_settings().github_token) as gh:
        try:
            repo = await gh.create_repo(name, private=spec.private, description=body.name)
            default = repo.get("default_branch") or "main"
            sha = await _branch_sha(gh, name, default)
            for branch in sorted({body.base_branch, body.prod_branch} - {default}):
                await gh.create_ref(f"refs/heads/{branch}", sha, name)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422 and "already exists" in exc.response.text:
                raise HTTPException(409, f"{name} already exists on GitHub — connect it as an existing repo") from exc
            raise HTTPException(502, f"GitHub: {exc.response.status_code} {exc.response.text[:300]}") from exc


async def _branch_sha(gh: GitHubClient, repo: str, branch: str) -> str:
    # The initial commit of a just-created repo can take a moment to show up.
    for _ in range(4):
        try:
            return await gh.get_branch_sha(branch, repo)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (404, 409):
                raise
        await asyncio.sleep(1)
    return await gh.get_branch_sha(branch, repo)


def _scaffold_description(brief: str) -> str:
    return (
        brief.strip()
        + "\n\n---\n"
        + "Репозиторий только что создан и пуст (в нём только README). Это первая задача проекта — заложи основу:\n"
        + "- выбери стек (если в описании его нет — простой и распространённый) и сделай рабочую первую версию "
        + "описанного;\n"
        + "- README: что это и как запустить локально;\n"
        + "- CLAUDE.md: стек, структура, команды запуска, тестов и линтеров, соглашения — по нему будут работать "
        + "следующие задачи;\n"
        + "- тесты и линтер, и чтобы они проходили;\n"
        + "- GitHub Actions workflow, который запускает их на pull_request: CI проверяет каждый PR перед авто-merge;\n"
        + "- .gitignore.\n"
        + "Если приложение ставит cookie — только host-only, без атрибута Domain, а сессионные — с префиксом "
        + "__Host- (Secure, Path=/): stage и прод живут на соседних поддоменах одного домена. Запиши это правило "
        + "в CLAUDE.md.\n"
        + "Деплой на stage не настраивай, если об этом не сказано выше."
    )


@router.get("/{project_id}", summary="Get a project")
async def get_project(project_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> ProjectResponse:
    project = await _load(session, project_id)
    return to_response(project, (await _counts(session)).get(project.id))


@router.put("/{project_id}", summary="Update a project")
async def update_project(
    project_id: str, body: ProjectBody, session: Annotated[AsyncSession, Depends(get_session)]
) -> ProjectResponse:
    project = await _load(session, project_id)
    _apply(project, body)
    await session.flush()
    await session.refresh(project)
    return to_response(project, (await _counts(session)).get(project.id))


@router.delete("/{project_id}", summary="Delete a project", status_code=204)
async def delete_project(project_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> None:
    project = await _load(session, project_id)
    if await session.scalar(select(func.count()).select_from(Task).where(Task.project_id == project_id)):
        raise HTTPException(409, "Project has tasks — disable it instead")
    await session.delete(project)


@router.post("/{project_id}/release", summary="Ship stage to production", status_code=201)
async def release_project(project_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> ReleaseResponse:
    project = await _load(session, project_id)
    async with GitHubClient(token=get_settings().github_token) as gh:
        try:
            release = await start_release(session, gh, project)
        except ReleaseError as exc:
            raise HTTPException(409, str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"GitHub: {exc.response.status_code} {exc.response.text[:300]}") from exc
    return release_to_response(release)
