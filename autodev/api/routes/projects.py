"""Project registry and production releases."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev import scaffold, secrets
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

    @model_validator(mode="before")
    @classmethod
    def _new_repo_in_org(cls, data: Any) -> Any:
        """A new repo given by bare name (or none: the project id) goes to the projects organization."""
        org = get_settings().projects_org
        if not (isinstance(data, dict) and data.get("new_repo") is not None and org):
            return data
        repos = data.get("repos") or [{}]
        if isinstance(repos, list) and len(repos) == 1 and isinstance(repos[0], dict):
            name = (repos[0].get("name") or "").strip() or str(data.get("id", ""))
            if "/" not in name:
                data = {**data, "repos": [{**repos[0], "name": f"{org}/{name}"}]}
        return data

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
    settings = get_settings()
    deployed = body.new_repo is not None and scaffold.deployed(body.repos[0].name, settings)
    if body.new_repo is not None:
        await _create_repo(body, body.new_repo, deployed)
    if deployed:
        # The cluster deploys the org's repos: stage is known up front, /version is in the contract.
        url = body.stage_url or scaffold.stage_url(body.repos[0].name, settings)
        repo = body.repos[0].model_copy(update={"version_url": body.repos[0].version_url or f"{url}/version"})
        body = body.model_copy(update={"stage_url": url, "repos": [repo]})
    project = Project(id=body.id)
    _apply(project, body)
    session.add(project)
    await session.flush()
    if body.new_repo is not None and body.new_repo.brief.strip():
        session.add(
            Task(
                title="Каркас проекта",
                description=scaffold.task_description(body.new_repo.brief, with_deploy=deployed),
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


async def _create_repo(body: ProjectBody, spec: NewRepo, deployed: bool) -> None:
    """Create the repo with its stage and prod branches, all at the same first commit(s)."""
    name = body.repos[0].name
    async with GitHubClient(token=get_settings().github_token) as gh:
        try:
            repo = await gh.create_repo(name, private=spec.private, description=body.name)
            default = repo.get("default_branch") or "main"
            sha = await _branch_sha(gh, name, default)
            if deployed:
                sha = await gh.put_file(
                    scaffold.IMAGE_WORKFLOW_PATH, scaffold.IMAGE_WORKFLOW, "ci: build the deploy image", default, name
                )
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


class SecretsResponse(BaseModel):
    # False: the cluster doesn't deploy this repo, there is nowhere to put secrets.
    deployed: bool
    stage: list[str] = Field(default_factory=list)
    prod: list[str] = Field(default_factory=list)


class SecretValue(BaseModel):
    value: str = Field(min_length=1, max_length=64 * 1024)


async def _deployed(session: AsyncSession, project_id: str) -> Project:
    project = await _load(session, project_id)
    if not scaffold.deployed(project.repo()["name"], get_settings()):
        raise HTTPException(409, "The cluster doesn't deploy this project's repo")
    return project


@router.get("/{project_id}/secrets", summary="Names of the project's secrets (values are sealed)")
async def list_secrets(project_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> SecretsResponse:
    project = await _load(session, project_id)
    if not scaffold.deployed(project.repo()["name"], get_settings()):
        return SecretsResponse(deployed=False)
    async with GitHubClient(token=get_settings().github_token) as gh:
        try:
            return SecretsResponse(deployed=True, **await secrets.names(gh, project))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"GitHub: {exc.response.status_code} {exc.response.text[:300]}") from exc


async def _update_secret(project: Project, env: str, name: str, value: str | None) -> SecretsResponse:
    settings = get_settings()
    async with GitHubClient(token=settings.github_token) as gh:
        try:
            names = await secrets.update(gh, project, env, name, value, settings)
        except secrets.SecretError as exc:
            raise HTTPException(422, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, f"No secret {name} in {env}") from exc
        except httpx.HTTPStatusError as exc:
            where = "GitHub" if "github.com" in str(exc.request.url) else "sealed-secrets"
            raise HTTPException(502, f"{where}: {exc.response.status_code} {exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"sealed-secrets certificate: {exc}") from exc
    return SecretsResponse(deployed=True, **names)


@router.put("/{project_id}/secrets/{env}/{name}", summary="Set a secret (sealed, committed to stage and prod)")
async def set_secret(
    project_id: str, env: str, name: str, body: SecretValue, session: Annotated[AsyncSession, Depends(get_session)]
) -> SecretsResponse:
    return await _update_secret(await _deployed(session, project_id), env, name, body.value)


@router.delete("/{project_id}/secrets/{env}/{name}", summary="Remove a secret")
async def delete_secret(
    project_id: str, env: str, name: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> SecretsResponse:
    return await _update_secret(await _deployed(session, project_id), env, name, None)
