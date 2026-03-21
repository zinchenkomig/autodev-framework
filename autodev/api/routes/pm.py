"""PM Agent API routes."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from autodev.api.database import get_session
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
    architecture: str | None
    current_focus: str | None
    last_analyzed_at: datetime | None


class AnalyzeRequest(BaseModel):
    repo: str


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
                # Filter to important files
                important = [p for p in paths if any(x in p.lower() for x in 
                    ["readme", "claude", "package.json", "pyproject.toml", "requirements", 
                     "dockerfile", "main.py", "app.py", "index.ts", "page.tsx"])]
                return "\n".join(important[:50])
        except Exception:
            pass
    return ""


async def analyze_repo_with_llm(repo: str, claude_md: str | None, readme: str | None, 
                                 structure: str, package_info: str | None) -> dict:
    """Use LLM to analyze repo and create context."""
    
    context_parts = []
    if claude_md:
        context_parts.append(f"## CLAUDE.md:\n{claude_md[:4000]}")
    if readme:
        context_parts.append(f"## README.md:\n{readme[:2000]}")
    if structure:
        context_parts.append(f"## File structure:\n{structure}")
    if package_info:
        context_parts.append(f"## Dependencies:\n{package_info[:1000]}")
    
    combined = "\n\n".join(context_parts)
    
    prompt = f"""Проанализируй этот репозиторий и создай краткий контекст для PM агента.

Репозиторий: {repo}

{combined}

Ответь в формате JSON:
{{
    "name": "Название проекта",
    "description": "Краткое описание (1-2 предложения)",
    "stack": "Технологический стек через запятую",
    "features": "Ключевые фичи и возможности (bullet points)",
    "architecture": "Краткое описание архитектуры (основные компоненты)",
    "current_focus": "На чём сейчас фокус разработки (если понятно)"
}}

Только JSON, без markdown."""

    response = await call_llm([
        {"role": "system", "content": "Ты анализатор репозиториев. Отвечай только JSON."},
        {"role": "user", "content": prompt}
    ])
    
    # Parse JSON from response
    try:
        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            import json
            return json.loads(json_match.group())
    except Exception:
        pass
    
    return {
        "name": repo.split("/")[-1],
        "description": "Не удалось проанализировать",
        "stack": "",
        "features": "",
        "architecture": "",
        "current_focus": ""
    }


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


async def get_all_contexts(session: AsyncSession) -> str:
    """Get all project contexts from DB."""
    stmt = select(ProjectContext)
    result = await session.execute(stmt)
    contexts = result.scalars().all()
    
    if not contexts:
        return "Нет сохранённых контекстов проектов. Используй команду 'изучи проект owner/repo' чтобы добавить."
    
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
    """Build PM system prompt with project contexts."""
    return f"""Ты PM агент в системе AutoDev. Твоя задача — помогать создавать задачи для разработчиков.

## Проекты которыми ты управляешь:
{contexts}

## Специальные команды:
- "изучи проект owner/repo" — проанализировать репозиторий и сохранить контекст
- "покажи контексты" — показать все сохранённые контексты

## Как работать:
1. Ты знаешь контекст проектов — не спрашивай про стек/архитектуру
2. Уточни только ЧТО именно делать если непонятно
3. Сразу предлагай конкретное решение

## Создание задачи:
Когда готов, ответь в формате:
---TASK---
title: <краткое название>
repo: <owner/repo>
priority: <low/normal/high/critical>
description: <подробное описание с техническими деталями>
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


@router.post("/chat", summary="Chat with PM agent")
async def pm_chat(
    request: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatResponse:
    """Process a message and optionally create a task."""
    
    msg_lower = request.message.lower().strip()
    
    # Check for analyze command
    if msg_lower.startswith("изучи проект") or msg_lower.startswith("analyze"):
        # Extract repo name
        parts = request.message.split()
        if len(parts) >= 3:
            repo = parts[-1]
            if "/" in repo:
                # Do the analysis
                claude_md = await fetch_file_from_github(repo, "CLAUDE.md")
                readme = await fetch_file_from_github(repo, "README.md")
                structure = await get_repo_structure(repo)
                package_json = await fetch_file_from_github(repo, "package.json")
                pyproject = await fetch_file_from_github(repo, "pyproject.toml")
                
                analysis = await analyze_repo_with_llm(
                    repo, claude_md, readme, structure, 
                    package_json or pyproject
                )
                
                # Save to DB
                existing = await session.scalar(
                    select(ProjectContext).where(ProjectContext.repo == repo)
                )
                
                if existing:
                    existing.name = analysis.get("name", repo)
                    existing.description = analysis.get("description")
                    existing.stack = analysis.get("stack")
                    existing.features = analysis.get("features")
                    existing.architecture = analysis.get("architecture")
                    existing.current_focus = analysis.get("current_focus")
                    existing.last_analyzed_at = datetime.now(UTC)
                else:
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
                
                return ChatResponse(
                    response=f"""✅ Проект `{repo}` проанализирован и сохранён!

**{analysis.get('name', repo)}**
{analysis.get('description', '')}

**Стек:** {analysis.get('stack', 'не определён')}

**Фичи:**
{analysis.get('features', 'не определены')}

Теперь я знаю этот проект и могу создавать задачи."""
                )
        
        return ChatResponse(response="Укажи репозиторий в формате: изучи проект owner/repo")
    
    # Check for show contexts command
    if "покажи контекст" in msg_lower or "show context" in msg_lower:
        contexts = await get_all_contexts(session)
        return ChatResponse(response=f"## Сохранённые контексты проектов:\n\n{contexts}")
    
    # Regular chat - get contexts and respond
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
    
    # Check if task should be created
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


@router.get("/contexts", summary="List all project contexts")
async def list_contexts(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectContextResponse]:
    """List all saved project contexts."""
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


@router.post("/analyze", summary="Analyze a repository")
async def analyze_repo(
    request: AnalyzeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectContextResponse:
    """Analyze a repository and save its context."""
    repo = request.repo
    
    claude_md = await fetch_file_from_github(repo, "CLAUDE.md")
    readme = await fetch_file_from_github(repo, "README.md")
    structure = await get_repo_structure(repo)
    package_json = await fetch_file_from_github(repo, "package.json")
    pyproject = await fetch_file_from_github(repo, "pyproject.toml")
    
    analysis = await analyze_repo_with_llm(
        repo, claude_md, readme, structure,
        package_json or pyproject
    )
    
    existing = await session.scalar(
        select(ProjectContext).where(ProjectContext.repo == repo)
    )
    
    if existing:
        existing.name = analysis.get("name", repo)
        existing.description = analysis.get("description")
        existing.stack = analysis.get("stack")
        existing.features = analysis.get("features")
        existing.architecture = analysis.get("architecture")
        existing.current_focus = analysis.get("current_focus")
        existing.last_analyzed_at = datetime.now(UTC)
        ctx = existing
    else:
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
    
    return ProjectContextResponse(
        repo=ctx.repo,
        name=ctx.name,
        description=ctx.description,
        stack=ctx.stack,
        features=ctx.features,
        architecture=ctx.architecture,
        current_focus=ctx.current_focus,
        last_analyzed_at=ctx.last_analyzed_at,
    )
