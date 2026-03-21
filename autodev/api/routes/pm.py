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
    """Analyze a repository."""
    claude_md = await fetch_file_from_github(repo, "CLAUDE.md")
    readme = await fetch_file_from_github(repo, "README.md")
    
    if not claude_md and not readme:
        return {"name": repo.split("/")[-1], "description": "Нет данных"}
    
    content = claude_md or readme
    
    prompt = f"""Кратко опиши проект (2-3 предложения). Репозиторий: {repo}

{content[:3000]}

JSON: {{"name": "...", "description": "...", "stack": "...", "features": "..."}}"""

    response = await call_llm([
        {"role": "system", "content": "Ответь только JSON."},
        {"role": "user", "content": prompt}
    ])
    
    try:
        import json
        match = re.search(r'\{[\s\S]*\}', response)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    
    return {"name": repo.split("/")[-1], "description": content[:200]}


async def ensure_context_exists(session: AsyncSession, repo: str) -> ProjectContext | None:
    """Ensure project context exists."""
    existing = await session.scalar(
        select(ProjectContext).where(ProjectContext.repo == repo)
    )
    
    if existing and existing.stack:  # Already analyzed
        return existing
    
    try:
        analysis = await analyze_repo(repo)
        
        if existing:
            existing.name = analysis.get("name", repo)
            existing.description = analysis.get("description")
            existing.stack = analysis.get("stack")
            existing.features = analysis.get("features")
            existing.last_analyzed_at = datetime.now(UTC)
            return existing
        
        ctx = ProjectContext(
            id=uuid4(),
            repo=repo,
            name=analysis.get("name", repo),
            description=analysis.get("description"),
            stack=analysis.get("stack"),
            features=analysis.get("features"),
            last_analyzed_at=datetime.now(UTC),
        )
        session.add(ctx)
        await session.flush()
        return ctx
    except Exception:
        return existing


async def get_all_contexts(session: AsyncSession) -> list[ProjectContext]:
    """Get all project contexts."""
    stmt = select(ProjectContext)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def build_system_prompt(contexts: list[ProjectContext]) -> str:
    """Build system prompt with unified project view."""
    
    projects_info = []
    for ctx in contexts:
        repo_type = "frontend" if "frontend" in ctx.repo.lower() else "backend" if "backend" in ctx.repo.lower() else "unknown"
        projects_info.append(f"""
**{ctx.name}** (`{ctx.repo}`) — {repo_type}
{ctx.description or 'нет описания'}
Стек: {ctx.stack or 'не определён'}
Фичи: {ctx.features or 'не определены'}
""")
    
    projects_str = "\n".join(projects_info) if projects_info else "Нет проектов"
    
    return f"""Ты PM агент AutoDev. Управляешь проектом как единым целым.

## Проекты (это ОДИН продукт с разными компонентами):
{projects_str}

## Правила:
1. НИКОГДА не спрашивай "в какой репозиторий" — определяй сам:
   - UI, компоненты, страницы, стили, React → frontend
   - API, эндпоинты, база данных, модели, бизнес-логика → backend
   - Если задача затрагивает оба — создай ДВЕ задачи

2. Сразу создавай задачу, не уточняй лишнего

3. Формат задачи:
---TASK---
title: краткое название
repo: полный путь owner/repo
priority: low/normal/high/critical
description: что сделать (конкретно, с техническими деталями)
---END---

4. Если нужны изменения в обоих репо, выдай две задачи подряд

Пользователь описывает ЧТО хочет — ты понимаешь ГДЕ это делать."""


def parse_tasks_from_response(response: str) -> list[dict]:
    """Parse one or more tasks from response."""
    tasks = []
    pattern = r"---TASK---\s*(.*?)\s*---END---"
    
    for match in re.finditer(pattern, response, re.DOTALL):
        task_block = match.group(1)
        task = {}
        
        for line in task_block.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                task[key.strip().lower()] = value.strip()
        
        if "title" in task and "description" in task:
            tasks.append(task)
    
    return tasks


@router.post("/chat", summary="Chat with PM agent")
async def pm_chat(
    request: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatResponse:
    """Process a message and create tasks."""
    
    # Get and analyze contexts
    contexts = await get_all_contexts(session)
    for ctx in contexts:
        if not ctx.stack:
            await ensure_context_exists(session, ctx.repo)
    
    # Refresh contexts after analysis
    contexts = await get_all_contexts(session)
    
    system_prompt = build_system_prompt(contexts)
    
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
        return ChatResponse(response=f"Ошибка: {e}")
    
    # Parse and create tasks
    tasks_data = parse_tasks_from_response(llm_response)
    created_tasks = []
    
    for task_data in tasks_data:
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
        created_tasks.append(task)
    
    # Clean response and add confirmations
    clean_response = re.sub(r"---TASK---.*?---END---", "", llm_response, flags=re.DOTALL).strip()
    
    if created_tasks:
        task_lines = [f"- `{t.title}` → {t.repo} (ID: {str(t.id)[:8]})" for t in created_tasks]
        clean_response += f"\n\n✅ Создано задач: {len(created_tasks)}\n" + "\n".join(task_lines)
    
    return ChatResponse(
        response=clean_response,
        task_created=len(created_tasks) > 0,
        task_id=str(created_tasks[0].id) if created_tasks else None,
    )


@router.get("/contexts", summary="List project contexts")
async def list_contexts(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectContextResponse]:
    """List all project contexts."""
    contexts = await get_all_contexts(session)
    return [
        ProjectContextResponse(
            repo=c.repo,
            name=c.name,
            description=c.description,
            stack=c.stack,
            features=c.features,
            last_analyzed_at=c.last_analyzed_at,
        )
        for c in contexts
    ]
