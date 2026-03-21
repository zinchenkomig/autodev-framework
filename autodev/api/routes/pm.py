"""PM Agent API routes with approval flow."""

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
    proposals: list[TaskProposal] = []  # Tasks waiting for approval


class ApproveRequest(BaseModel):
    session_id: str
    proposals: list[TaskProposal]


class ApproveResponse(BaseModel):
    created_tasks: list[dict]  # id, title, url


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


class ProjectContextResponse(BaseModel):
    repo: str
    name: str
    description: str | None
    stack: str | None
    features: str | None
    last_analyzed_at: datetime | None


# === Helpers ===

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


async def analyze_repo(repo: str) -> dict:
    """Analyze a repository."""
    claude_md = await fetch_file_from_github(repo, "CLAUDE.md")
    readme = await fetch_file_from_github(repo, "README.md")
    
    if not claude_md and not readme:
        return {"name": repo.split("/")[-1], "description": "Нет данных"}
    
    content = claude_md or readme
    
    prompt = f"""Кратко опиши проект. Репозиторий: {repo}

{content[:3000]}

JSON: {{"name": "...", "description": "...", "stack": "...", "features": "..."}}"""

    response = await call_llm([
        {"role": "system", "content": "Ответь только JSON."},
        {"role": "user", "content": prompt}
    ])
    
    try:
        match = re.search(r'\{[\s\S]*\}', response)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    
    return {"name": repo.split("/")[-1], "description": content[:200]}


async def ensure_context_exists(session: AsyncSession, repo: str) -> ProjectContext | None:
    """Ensure project context exists and is analyzed."""
    existing = await session.scalar(
        select(ProjectContext).where(ProjectContext.repo == repo)
    )
    
    if existing and existing.stack:
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
    result = await session.execute(select(ProjectContext))
    return list(result.scalars().all())


def build_system_prompt(contexts: list[ProjectContext]) -> str:
    """Build system prompt with approval flow."""
    projects_info = []
    for ctx in contexts:
        repo_type = "frontend" if "frontend" in ctx.repo.lower() else "backend" if "backend" in ctx.repo.lower() else "general"
        projects_info.append(f"**{ctx.name}** (`{ctx.repo}`) — {repo_type}\n{ctx.description or ''}\nСтек: {ctx.stack or '?'}")
    
    projects_str = "\n\n".join(projects_info) if projects_info else "Нет проектов"
    
    return f"""Ты PM агент AutoDev.

## Проекты:
{projects_str}

## Правила:
1. САМ определяй репозиторий: UI/React/компоненты → frontend, API/модели/эндпоинты → backend
2. НЕ создавай задачу сразу — ПРЕДЛОЖИ её для подтверждения
3. Если нужны оба репо — предложи 2 задачи

## Формат ПРЕДЛОЖЕНИЯ задачи (пользователь должен подтвердить):
---PROPOSAL---
title: краткое название
repo: owner/repo  
priority: low/normal/high/critical
description: подробное описание что сделать
---END---

После блока PROPOSAL напиши краткое объяснение и спроси подтверждение.
Пользователь нажмёт кнопку "Создать" в интерфейсе."""


def parse_proposals_from_response(response: str) -> list[dict]:
    """Parse task proposals from response."""
    proposals = []
    for match in re.finditer(r"---PROPOSAL---\s*(.*?)\s*---END---", response, re.DOTALL):
        proposal = {}
        for line in match.group(1).strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                proposal[key.strip().lower()] = value.strip()
        if "title" in proposal and "description" in proposal:
            proposals.append(proposal)
    return proposals


def generate_session_title(message: str) -> str:
    """Generate title from first message."""
    title = message[:50].strip()
    if len(message) > 50:
        title += "..."
    return title


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
            session_uuid = UUID(request.session_id)
            chat_session = await session.get(ChatSession, session_uuid)
        except ValueError:
            pass
    
    if not chat_session:
        chat_session = ChatSession(
            id=uuid4(),
            title=generate_session_title(request.message),
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
    history = history_result.scalars().all()
    
    # Get project contexts
    contexts = await get_all_contexts(session)
    for ctx in contexts:
        if not ctx.stack:
            await ensure_context_exists(session, ctx.repo)
    contexts = await get_all_contexts(session)
    
    # Build messages for LLM
    system_prompt = build_system_prompt(contexts)
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in history:
        messages.append({
            "role": "user" if msg.role == "user" else "assistant",
            "content": msg.content
        })
    
    # Call LLM
    try:
        llm_response = await call_llm(messages)
    except Exception as e:
        return ChatResponse(
            response=f"Ошибка: {e}",
            session_id=str(chat_session.id),
        )
    
    # Parse proposals (not creating tasks yet)
    proposals_data = parse_proposals_from_response(llm_response)
    proposals = [
        TaskProposal(
            title=p.get("title", ""),
            repo=p.get("repo", ""),
            priority=p.get("priority", "normal"),
            description=p.get("description", ""),
        )
        for p in proposals_data
    ]
    
    # Clean response (remove proposal blocks for display)
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
    """Approve proposed tasks and create them."""
    
    created_tasks = []
    
    for proposal in request.proposals:
        priority_map = {
            "low": Priority.LOW,
            "normal": Priority.NORMAL,
            "high": Priority.HIGH,
            "critical": Priority.CRITICAL,
        }
        priority = priority_map.get(proposal.priority, Priority.NORMAL)
        
        task = Task(
            id=uuid4(),
            title=proposal.title,
            description=proposal.description,
            status=TaskStatus.QUEUED,
            priority=priority,
            repo=proposal.repo,
            created_at=datetime.now(UTC),
            created_by="pm_agent",
        )
        session.add(task)
        await session.flush()
        
        task_url = f"{DASHBOARD_URL}/tasks?id={task.id}"
        
        created_tasks.append({
            "id": str(task.id),
            "title": task.title,
            "repo": task.repo,
            "url": task_url,
        })
    
    # Add confirmation message to chat
    if request.session_id:
        try:
            session_uuid = UUID(request.session_id)
            task_links = "\n".join([f"• [{t['title']}]({t['url']})" for t in created_tasks])
            confirm_msg = PMChatMessage(
                id=uuid4(),
                session_id=session_uuid,
                role="pm",
                content=f"✅ Создано задач: {len(created_tasks)}\n\n{task_links}",
                task_id=UUID(created_tasks[0]["id"]) if created_tasks else None,
            )
            session.add(confirm_msg)
        except ValueError:
            pass
    
    return ApproveResponse(created_tasks=created_tasks)


@router.get("/sessions", summary="List chat sessions")
async def list_sessions(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 20,
) -> list[SessionSummary]:
    """List recent chat sessions."""
    result = await session.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .order_by(desc(ChatSession.updated_at))
        .limit(limit)
    )
    sessions = result.scalars().all()
    
    return [
        SessionSummary(
            id=str(s.id),
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=len(s.messages),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", summary="Get chat session")
async def get_session_detail(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionDetail:
    """Get chat session with messages."""
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
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "task_id": str(m.task_id) if m.task_id else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in chat_session.messages
        ],
    )


@router.delete("/sessions/{session_id}", summary="Delete chat session")
async def delete_session(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Delete a chat session."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    
    chat_session = await session.get(ChatSession, session_uuid)
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await session.delete(chat_session)
    return {"deleted": True}


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
