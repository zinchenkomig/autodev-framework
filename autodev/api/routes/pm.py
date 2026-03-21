"""PM Agent API routes - thoughtful task creation."""

from __future__ import annotations

import os
import re
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx

from autodev.api.database import get_session
from autodev.core.models import (
    Task, TaskStatus, Priority, ProjectContext,
    ChatSession, PMChatMessage
)

router = APIRouter(tags=["pm"])

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://autodev.zinchenkomig.com")


# === Models ===

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class TaskProposal(BaseModel):
    title: str
    repo: str
    priority: str
    description: str


class ChatResponse(BaseModel):
    response: str
    session_id: str
    proposals: list[TaskProposal] = []


class ApproveRequest(BaseModel):
    session_id: str
    proposals: list[TaskProposal]


class ApproveResponse(BaseModel):
    created_tasks: list[dict]


class SessionSummary(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


class SessionDetail(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    messages: list[dict]


# === Documentation ===

async def fetch_from_github(repo: str, path: str) -> str | None:
    """Fetch a file from GitHub repo."""
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


async def get_repo_docs(repo: str) -> str:
    """Get documentation for a repo."""
    project_md = await fetch_from_github(repo, "PROJECT.md")
    claude_md = await fetch_from_github(repo, "CLAUDE.md")
    
    docs = []
    if project_md:
        docs.append(f"### PROJECT.md\n{project_md[:2000]}")
    if claude_md:
        docs.append(f"### CLAUDE.md\n{claude_md[:1500]}")
    
    return "\n\n".join(docs) if docs else "Документация не найдена"


async def build_full_context(session: AsyncSession) -> str:
    """Build context from all repos."""
    result = await session.execute(select(ProjectContext.repo))
    repos = [r[0] for r in result.all()]
    
    contexts = []
    for repo in repos:
        repo_type = "frontend" if "frontend" in repo.lower() else "backend"
        docs = await get_repo_docs(repo)
        contexts.append(f"## {repo} ({repo_type})\n{docs}")
    
    return "\n\n---\n\n".join(contexts)


# === LLM ===

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
                "max_tokens": 3000,
            },
            timeout=90.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


def build_system_prompt(context: str) -> str:
    """Build system prompt for thoughtful PM."""
    return f"""Ты опытный PM. Когда пользователь описывает что хочет — ты анализируешь задачу и предлагаешь план.

# Проекты (документация):
{context}

# Как работать:

1. **Понять задачу** — перескажи своими словами что нужно сделать
2. **Продумать реализацию** — какие компоненты затронуты, какие шаги нужны
3. **Декомпозировать** — если задача сложная, разбей на 2-4 отдельные таски
4. **Предложить** — покажи структурированные карточки задач

# Формат ответа:

## Понимание
<Своими словами что хочет пользователь>

## Анализ
<Какие части системы затронуты, как это реализовать>

## Задачи

---PROPOSAL---
title: Название задачи 1
repo: owner/repo
priority: normal
description: |
  **Что сделать:**
  - Пункт 1
  - Пункт 2
  
  **Где менять:**
  - файл/компонент
  
  **Acceptance criteria:**
  - Критерий готовности
---END---

---PROPOSAL---
title: Название задачи 2 (если нужна)
repo: owner/repo
priority: normal
description: |
  ...
---END---

# Правила:
- Определяй репозиторий сам (frontend/backend) по контексту
- Одна фича может = несколько тасок (backend API + frontend UI)
- В description пиши конкретно: файлы, функции, компоненты
- Priority: low (мелочь), normal (обычная), high (важно), critical (блокер)
- НЕ спрашивай уточнений если можешь решить сам на основе документации"""


def parse_proposals(response: str) -> list[dict]:
    """Parse task proposals from response."""
    proposals = []
    for match in re.finditer(r"---PROPOSAL---\s*(.*?)\s*---END---", response, re.DOTALL):
        proposal = {}
        current_key = None
        current_value = []
        
        for line in match.group(1).strip().split("\n"):
            if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                # Save previous key
                if current_key:
                    proposal[current_key] = "\n".join(current_value).strip()
                # Start new key
                key, value = line.split(":", 1)
                current_key = key.strip().lower()
                current_value = [value.strip()] if value.strip() else []
            else:
                current_value.append(line)
        
        # Save last key
        if current_key:
            proposal[current_key] = "\n".join(current_value).strip()
        
        if "title" in proposal:
            proposals.append(proposal)
    
    return proposals


# === Endpoints ===

@router.post("/chat", summary="Chat with PM agent")
async def pm_chat(
    request: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatResponse:
    """Send message to PM agent."""
    
    # Get or create chat session
    chat_session: ChatSession | None = None
    
    if request.session_id:
        try:
            chat_session = await session.get(ChatSession, UUID(request.session_id))
        except ValueError:
            pass
    
    if not chat_session:
        chat_session = ChatSession(
            id=uuid4(),
            title=request.message[:50] + ("..." if len(request.message) > 50 else ""),
        )
        session.add(chat_session)
        await session.flush()
    
    # Save user message
    user_msg = PMChatMessage(
        id=uuid4(),
        session_id=chat_session.id,
        role="user",
        content=request.message,
    )
    session.add(user_msg)
    
    # Load chat history
    history_result = await session.execute(
        select(PMChatMessage)
        .where(PMChatMessage.session_id == chat_session.id)
        .order_by(PMChatMessage.created_at)
    )
    history = list(history_result.scalars().all())
    
    # Build context
    project_context = await build_full_context(session)
    system_prompt = build_system_prompt(project_context)
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({
            "role": "user" if msg.role == "user" else "assistant",
            "content": msg.content
        })
    
    try:
        llm_response = await call_llm(messages)
    except Exception as e:
        return ChatResponse(response=f"Ошибка: {e}", session_id=str(chat_session.id))
    
    # Parse proposals
    proposals_data = parse_proposals(llm_response)
    proposals = [
        TaskProposal(
            title=p.get("title", ""),
            repo=p.get("repo", ""),
            priority=p.get("priority", "normal"),
            description=p.get("description", ""),
        )
        for p in proposals_data
    ]
    
    # Clean response (keep analysis, remove proposal blocks)
    clean_response = re.sub(r"---PROPOSAL---.*?---END---", "", llm_response, flags=re.DOTALL).strip()
    
    # Save PM response
    pm_msg = PMChatMessage(
        id=uuid4(),
        session_id=chat_session.id,
        role="pm",
        content=clean_response,
    )
    session.add(pm_msg)
    chat_session.updated_at = datetime.now(UTC)
    
    return ChatResponse(
        response=clean_response,
        session_id=str(chat_session.id),
        proposals=proposals,
    )


@router.post("/approve", summary="Approve and create tasks")
async def approve_tasks(
    request: ApproveRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApproveResponse:
    """Approve proposed tasks."""
    created_tasks = []
    
    for proposal in request.proposals:
        priority_map = {
            "low": Priority.LOW, "normal": Priority.NORMAL,
            "high": Priority.HIGH, "critical": Priority.CRITICAL,
        }
        
        task = Task(
            id=uuid4(),
            title=proposal.title,
            description=proposal.description,
            status=TaskStatus.QUEUED,
            priority=priority_map.get(proposal.priority, Priority.NORMAL),
            repo=proposal.repo,
            created_at=datetime.now(UTC),
            created_by="pm_agent",
        )
        session.add(task)
        await session.flush()
        
        created_tasks.append({
            "id": str(task.id),
            "title": task.title,
            "repo": task.repo,
            "url": f"{DASHBOARD_URL}/tasks?id={task.id}",
        })
    
    # Add confirmation to chat
    if request.session_id:
        try:
            task_links = "\n".join([f"• [{t['title']}]({t['url']})" for t in created_tasks])
            confirm_msg = PMChatMessage(
                id=uuid4(),
                session_id=UUID(request.session_id),
                role="pm",
                content=f"✅ Создано задач: {len(created_tasks)}\n\n{task_links}",
                task_id=UUID(created_tasks[0]["id"]) if created_tasks else None,
            )
            session.add(confirm_msg)
        except ValueError:
            pass
    
    return ApproveResponse(created_tasks=created_tasks)


@router.get("/sessions")
async def list_sessions(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 20,
) -> list[SessionSummary]:
    result = await session.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .order_by(desc(ChatSession.updated_at))
        .limit(limit)
    )
    return [
        SessionSummary(
            id=str(s.id), title=s.title,
            created_at=s.created_at, updated_at=s.updated_at,
            message_count=len(s.messages),
        )
        for s in result.scalars().all()
    ]


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionDetail:
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    
    result = await session.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_uuid)
    )
    chat_session = result.scalar_one_or_none()
    
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionDetail(
        id=str(chat_session.id),
        title=chat_session.title,
        created_at=chat_session.created_at,
        messages=[
            {"id": str(m.id), "role": m.role, "content": m.content,
             "task_id": str(m.task_id) if m.task_id else None,
             "created_at": m.created_at.isoformat()}
            for m in chat_session.messages
        ],
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        chat_session = await session.get(ChatSession, UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await session.delete(chat_session)
    return {"deleted": True}
