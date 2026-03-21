"""PM Agent API routes - reads docs from repositories."""

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


class ProjectContextResponse(BaseModel):
    repo: str
    name: str
    description: str | None
    stack: str | None
    features: str | None
    api_summary: str | None
    last_updated: datetime | None


# === Documentation Fetching ===

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


async def fetch_openapi_spec(repo: str) -> dict | None:
    """Fetch OpenAPI spec from repo or live endpoint."""
    # Try common locations
    for path in ["openapi.json", "openapi/openapi.json", "docs/openapi.json"]:
        content = await fetch_from_github(repo, path)
        if content:
            try:
                return json.loads(content)
            except Exception:
                pass
    return None


def summarize_openapi(spec: dict) -> str:
    """Create summary of API endpoints."""
    if not spec:
        return ""
    
    paths = spec.get("paths", {})
    endpoints = []
    
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "delete", "patch"]:
                summary = details.get("summary", details.get("operationId", ""))
                endpoints.append(f"- {method.upper()} {path}: {summary}")
    
    if len(endpoints) > 20:
        return "\n".join(endpoints[:20]) + f"\n... и ещё {len(endpoints) - 20} эндпоинтов"
    
    return "\n".join(endpoints)


async def get_repo_documentation(repo: str) -> dict:
    """Fetch all documentation for a repo."""
    docs = {
        "repo": repo,
        "name": repo.split("/")[-1],
        "project_md": None,
        "claude_md": None,
        "readme": None,
        "openapi_summary": None,
    }
    
    # Fetch docs in parallel
    docs["project_md"] = await fetch_from_github(repo, "PROJECT.md")
    docs["claude_md"] = await fetch_from_github(repo, "CLAUDE.md")
    docs["readme"] = await fetch_from_github(repo, "README.md")
    
    # Fetch OpenAPI for backends
    if "backend" in repo.lower():
        openapi = await fetch_openapi_spec(repo)
        if openapi:
            docs["openapi_summary"] = summarize_openapi(openapi)
    
    return docs


def build_project_context(docs: dict) -> str:
    """Build context string from documentation."""
    parts = []
    repo = docs["repo"]
    repo_type = "frontend" if "frontend" in repo.lower() else "backend"
    
    parts.append(f"### {docs['name']} (`{repo}`) — {repo_type}")
    
    # Prefer PROJECT.md, fallback to CLAUDE.md, then README
    main_doc = docs.get("project_md") or docs.get("claude_md") or docs.get("readme")
    if main_doc:
        # Take first 1500 chars
        parts.append(main_doc[:1500])
    
    # Add API summary for backends
    if docs.get("openapi_summary"):
        parts.append("\n**API Endpoints:**")
        parts.append(docs["openapi_summary"])
    
    return "\n".join(parts)


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
                "max_tokens": 2048,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# === Context Management ===

async def get_all_repos(session: AsyncSession) -> list[str]:
    """Get all tracked repos from DB."""
    result = await session.execute(select(ProjectContext.repo))
    return [r[0] for r in result.all()]


async def build_full_context(session: AsyncSession) -> str:
    """Build full project context from repo documentation."""
    repos = await get_all_repos(session)
    
    if not repos:
        return "Нет отслеживаемых проектов."
    
    contexts = []
    for repo in repos:
        docs = await get_repo_documentation(repo)
        ctx = build_project_context(docs)
        contexts.append(ctx)
    
    return "\n\n---\n\n".join(contexts)


def build_system_prompt(context: str) -> str:
    """Build system prompt."""
    return f"""Ты PM агент AutoDev. Ты знаешь проекты на основе их документации.

## Проекты (документация из репозиториев):
{context}

## Правила:
1. САМ определяй репозиторий по контексту задачи
2. НЕ создавай задачу сразу — ПРЕДЛОЖИ для подтверждения
3. Если задача затрагивает оба репо — предложи 2 задачи
4. Используй знание API эндпоинтов и структуры проекта

## Формат предложения:
---PROPOSAL---
title: краткое название
repo: owner/repo
priority: low/normal/high/critical
description: подробное описание (с учётом архитектуры проекта)
---END---"""


def parse_proposals(response: str) -> list[dict]:
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
    
    # Build context from repo documentation
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
    return [
        SessionSummary(
            id=str(s.id), title=s.title,
            created_at=s.created_at, updated_at=s.updated_at,
            message_count=len(s.messages),
        )
        for s in result.scalars().all()
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
    """Delete a chat session."""
    try:
        chat_session = await session.get(ChatSession, UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await session.delete(chat_session)
    return {"deleted": True}


@router.get("/contexts", summary="Get project contexts")
async def list_contexts(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectContextResponse]:
    """Get documentation from all tracked repos."""
    repos = await get_all_repos(session)
    
    result = []
    for repo in repos:
        docs = await get_repo_documentation(repo)
        
        # Extract description from docs
        main_doc = docs.get("project_md") or docs.get("claude_md") or docs.get("readme") or ""
        description = main_doc[:300] if main_doc else None
        
        result.append(ProjectContextResponse(
            repo=repo,
            name=docs["name"],
            description=description,
            stack=None,  # Could parse from docs
            features=None,
            api_summary=docs.get("openapi_summary"),
            last_updated=datetime.now(UTC),
        ))
    
    return result


@router.post("/refresh", summary="Refresh project documentation")
async def refresh_contexts(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Force refresh documentation from all repos."""
    repos = await get_all_repos(session)
    
    for repo in repos:
        # Fetch fresh docs (will be used on next PM chat)
        await get_repo_documentation(repo)
    
    return {"refreshed": len(repos)}
