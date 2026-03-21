"""PM Agent API routes."""

from __future__ import annotations

import os
import re
import yaml
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from autodev.api.database import get_session, SessionLocal
from autodev.core.models import Task, TaskStatus, Priority, ProjectContext

router = APIRouter(tags=["pm"])

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
AUTODEV_CONFIG = os.environ.get("AUTODEV_CONFIG", "/app/autodev.yaml")

# Track if we've done initial sync
_initial_sync_done = False


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str
    task_created: bool = False
    task_id: str | None = None


class ProjectContextResponse(BaseModel):
    repo: str
    name: str
    description: str | None
    stack: str | None
    features: str | None
    architecture: str | None
    current_focus: str | None
    last_analyzed_at: datetime | None


async def fetch_file_from_github(repo: str, path: str) -> str | None:
    """Fetch a file from GitHub."""
    url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
    return None


async def get_repo_structure(repo: str) -> str:
    """Get repository file structure."""
    url = f"https://api.github.com/repos/{repo}/git/trees/main?recursive=1"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                tree = data.get("tree", [])
                paths = [item["path"] for item in tree if item["type"] == "blob"]
                important = [p for p in paths if any(x in p.lower() for x in 
                    ["readme", "claude", "package.json", "pyproject.toml", "requirements", 
                     "dockerfile", "main.py", "app.py", "index.ts", "page.tsx"])]
                return "\n".join(important[:50])
        except Exception:
            pass
    return ""


async def call_llm(messages: list[dict]) -> str:
    """Call LLM API."""
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        return "Error: No API key"
    
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("PM_MODEL", "z-ai/glm-5")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 2048,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def analyze_repo(repo: str) -> dict:
    """Analyze a repository and return context dict."""
    claude_md = await fetch_file_from_github(repo, "CLAUDE.md")
    readme = await fetch_file_from_github(repo, "README.md")
    structure = await get_repo_structure(repo)
    package_json = await fetch_file_from_github(repo, "package.json")
    pyproject = await fetch_file_from_github(repo, "pyproject.toml")
    
    context_parts = []
    if claude_md:
        context_parts.append(f"## CLAUDE.md:\n{claude_md[:4000]}")
    if readme:
        context_parts.append(f"## README.md:\n{readme[:2000]}")
    if structure:
        context_parts.append(f"## File structure:\n{structure}")
    if package_json or pyproject:
        context_parts.append(f"## Dependencies:\n{(package_json or pyproject)[:1000]}")
    
    if not context_parts:
        return {
            "name": repo.split("/")[-1],
            "description": "Не удалось получить данные репозитория",
        }
    
    combined = "\n\n".join(context_parts)
    
    prompt = f"""Проанализируй репозиторий и создай контекст. Репозиторий: {repo}

{combined}

Ответь JSON:
{{"name": "Название", "description": "Описание", "stack": "Стек", "features": "Фичи", "architecture": "Архитектура", "current_focus": "Фокус"}}"""

    response = await call_llm([
        {"role": "system", "content": "Ты анализатор репозиториев. Только JSON."},
        {"role": "user", "content": prompt}
    ])
    
    try:
        import json
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    
    return {"name": repo.split("/")[-1], "description": "Не удалось проанализировать"}


async def ensure_context_exists(session: AsyncSession, repo: str) -> ProjectContext | None:
    """Ensure project context exists, analyze if not."""
    existing = await session.scalar(
        select(ProjectContext).where(ProjectContext.repo == repo)
    )
    
    if existing:
        return existing
    
    # Analyze and create
    try:
        analysis = await analyze_repo(repo)
        
        ctx = ProjectContext(
            id=uuid4(),
            repo=repo,
            name=analysis.get("name", repo),
            description=analysis.get("description"),
            stack=analysis.get("stack"),
            features=analysis.get("features"),
            architecture=analysis.get("architecture"),
            current_focus=analysis.get("current_focus"),
            last_analyzed_at=datetime.now(UTC),
        )
        session.add(ctx)
        await session.flush()
        return ctx
    except Exception:
        return None


async def sync_repos_from_config(session: AsyncSession):
    """Sync repos from autodev.yaml config."""
    global _initial_sync_done
    if _initial_sync_done:
        return
    
    config_path = Path(AUTODEV_CONFIG)
    if not config_path.exists():
        _initial_sync_done = True
        return
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        repos = config.get("repos", [])
        for repo_config in repos:
            repo_url = repo_config.get("url", "")
            # Convert github.com/owner/repo to owner/repo
            if "github.com/" in repo_url:
                repo = repo_url.split("github.com/")[-1]
            else:
                repo = repo_url
            
            if "/" in repo:
                await ensure_context_exists(session, repo)
        
        _initial_sync_done = True
    except Exception:
        _initial_sync_done = True


async def get_all_contexts(session: AsyncSession) -> str:
    """Get all project contexts from DB."""
    # Sync from config on first call
    await sync_repos_from_config(session)
    
    stmt = select(ProjectContext)
    result = await session.execute(stmt)
    contexts = result.scalars().all()
    
    if not contexts:
        return "Нет контекстов проектов."
    
    parts = []
    for ctx in contexts:
        parts.append(f"""
### {ctx.name} (`{ctx.repo}`)
{ctx.description or ''}

**Стек:** {ctx.stack or 'не указан'}

**Фичи:**
{ctx.features or 'не указаны'}

**Архитектура:**
{ctx.architecture or 'не указана'}

**Фокус:** {ctx.current_focus or 'не указан'}
""")
    return "\n---\n".join(parts)


def get_pm_system_prompt(contexts: str) -> str:
    """Build PM system prompt."""
    return f"""Ты PM агент в системе AutoDev.

## Проекты:
{contexts}

## Как работать:
1. Ты знаешь контексты проектов
2. Не спрашивай про стек — ты его знаешь
3. Сразу предлагай решение

## Создание задачи:
---TASK---
title: <название>
repo: <owner/repo>
priority: <low/normal/high/critical>
description: <описание>
---END---
"""


def parse_task_from_response(response: str) -> dict | None:
    """Parse task from LLM response."""
    if "---TASK---" not in response:
        return None
    
    match = re.search(r"---TASK---\s*(.*?)\s*---END---", response, re.DOTALL)
    if not match:
        return None
    
    task_block = match.group(1)
    task = {}
    
    for line in task_block.strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            task[key.strip().lower()] = value.strip()
    
    if "title" in task and "description" in task:
        return task
    return None


def extract_repo_mentions(text: str) -> list[str]:
    """Extract GitHub repo mentions from text."""
    # Match patterns like owner/repo, github.com/owner/repo
    pattern = r'(?:github\.com/)?([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)'
    matches = re.findall(pattern, text)
    return [m for m in matches if not m.startswith('api/')]


@router.post("/chat", summary="Chat with PM agent")
async def pm_chat(
    request: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatResponse:
    """Process a message and optionally create a task."""
    
    # Auto-learn any mentioned repos
    mentioned_repos = extract_repo_mentions(request.message)
    for repo in mentioned_repos:
        await ensure_context_exists(session, repo)
    
    # Get contexts (also syncs from config on first call)
    contexts = await get_all_contexts(session)
    system_prompt = get_pm_system_prompt(contexts)
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history:
        messages.append({
            "role": "user" if msg.role == "user" else "assistant",
            "content": msg.content
        })
    messages.append({"role": "user", "content": request.message})
    
    try:
        llm_response = await call_llm(messages)
    except Exception as e:
        return ChatResponse(response=f"Ошибка LLM: {e}")
    
    # Check for task
    task_data = parse_task_from_response(llm_response)
    task_id = None
    task_created = False
    
    if task_data:
        priority_map = {
            "low": Priority.LOW,
            "normal": Priority.NORMAL,
            "high": Priority.HIGH,
            "critical": Priority.CRITICAL,
        }
        priority = priority_map.get(task_data.get("priority", "normal"), Priority.NORMAL)
        
        task = Task(
            id=uuid4(),
            title=task_data["title"],
            description=task_data["description"],
            status=TaskStatus.QUEUED,
            priority=priority,
            repo=task_data.get("repo", ""),
            created_at=datetime.now(UTC),
            created_by="pm_agent",
        )
        session.add(task)
        await session.flush()
        
        task_id = str(task.id)
        task_created = True
        
        clean_response = re.sub(r"---TASK---.*?---END---", "", llm_response, flags=re.DOTALL).strip()
        llm_response = f"{clean_response}\n\n✅ Задача создана: `{task.title}`\nID: {task_id[:8]}"
    
    return ChatResponse(
        response=llm_response,
        task_created=task_created,
        task_id=task_id,
    )


@router.get("/contexts", summary="List project contexts")
async def list_contexts(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectContextResponse]:
    """List all project contexts."""
    await sync_repos_from_config(session)
    
    stmt = select(ProjectContext)
    result = await session.execute(stmt)
    contexts = result.scalars().all()
    
    return [
        ProjectContextResponse(
            repo=c.repo,
            name=c.name,
            description=c.description,
            stack=c.stack,
            features=c.features,
            architecture=c.architecture,
            current_focus=c.current_focus,
            last_analyzed_at=c.last_analyzed_at,
        )
        for c in contexts
    ]
