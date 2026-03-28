"""PM Agent API routes."""

from __future__ import annotations

import os
import re
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
from autodev.agent_log import log_agent

router = APIRouter(tags=["pm"])

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://autodev.zinchenkomig.com")


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


async def fetch_github(repo: str, path: str) -> str | None:
    url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            return resp.text if resp.status_code == 200 else None
        except:
            return None


async def get_repo_docs(repo: str) -> str:
    project = await fetch_github(repo, "PROJECT.md")
    claude = await fetch_github(repo, "CLAUDE.md")
    docs = []
    if project:
        docs.append(project[:4000])
    if claude:
        docs.append(claude[:3000])
    return "\n\n".join(docs) if docs else ""


async def build_context(session: AsyncSession) -> str:
    # 1. Project docs
    result = await session.execute(select(ProjectContext.repo))
    repos = [r[0] for r in result.all()]
    parts = []
    for repo in repos:
        docs = await get_repo_docs(repo)
        if docs:
            parts.append(f"# {repo}\n{docs}")
    
    # 2. Current tasks by status
    from autodev.core.models import Release, ReleaseStatus
    
    result = await session.execute(
        select(Task).where(
            Task.status.in_(['queued', 'in_progress', 'autoreview', 'ready_to_release', 'staging', 'failed'])
        ).order_by(Task.status, Task.created_at)
    )
    tasks = result.scalars().all()
    
    if tasks:
        task_section = "\n\n# Текущие задачи\n"
        by_status: dict[str, list] = {}
        for t in tasks:
            by_status.setdefault(t.status, []).append(t)
        
        status_labels = {
            'queued': '📋 В очереди',
            'in_progress': '🔨 В работе',
            'autoreview': '🔍 Автоматическая проверка',
            'ready_to_release': '✅ Готово к релизу',
            'staging': '🚀 На staging',
            'failed': '❌ Ошибка',
        }
        
        for status, task_list in by_status.items():
            label = status_labels.get(status, status)
            total_sp = sum(t.story_points or 1 for t in task_list)
            task_section += f"\n## {label} ({len(task_list)} задач, {total_sp} SP)\n"
            for t in task_list:
                sp = f"[{t.story_points}SP]" if t.story_points else ""
                pr = f" PR: {t.pr_url}" if t.pr_url else ""
                task_section += f"- {sp} {t.title} ({t.repo}){pr}\n"
                if t.description:
                    task_section += f"  Описание: {t.description[:150]}\n"
        
        parts.append(task_section)
    
    # 3. Active release on staging
    result = await session.execute(
        select(Release).where(Release.status == ReleaseStatus.STAGING).order_by(Release.created_at.desc()).limit(1)
    )
    release = result.scalar_one_or_none()
    
    if release:
        release_section = f"\n\n# Текущий релиз на staging: {release.version}\n"
        release_section += f"Задач: {len(release.tasks or [])}\n"
        if release.release_notes:
            release_section += f"\nRelease notes:\n{release.release_notes[:1000]}\n"
        parts.append(release_section)
    
    return "\n\n---\n\n".join(parts) if parts else "Нет данных о проекте"


async def call_llm(messages: list[dict]) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return "No API key"
    
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("PM_MODEL", "z-ai/glm-5-turbo")
    
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 8000},
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


SYSTEM_PROMPT = """You are a PM agent for this project. You can see all tasks, releases, and project state.

{context}

## Your role:
- Answer questions about the project, tasks, releases
- When the user describes a feature or problem — create tasks
- When the user asks about status — just answer, do NOT create tasks
- When the user gives staging feedback — create hotfix tasks

## When to create tasks:
- User describes a new feature → create tasks
- User reports a bug → create a task
- User gives staging feedback → create hotfix tasks
- User asks "what's on staging?" → just answer, do NOT create tasks

## Task format (ALWAYS use this exact format):

---TASK---
title: Short task title
repo: zinchenkomig/great_alerter_backend
priority: normal
description: Detailed description of what needs to be done
---END---

## Example response:

I'll add a new mode to the data generator.

---TASK---
title: Add replace mode to degradation generator
repo: zinchenkomig/great_alerter_backend
priority: normal
description: Add a mode parameter to the degradation creation function. When mode="replace", update existing records (UPDATE) instead of creating new ones (INSERT). This will allow injecting anomalies into existing data.
---END---

## Rules:
- When creating tasks, ALWAYS use the exact ---TASK--- / ---END--- format
- repo: zinchenkomig/great_alerter_backend for backend, zinchenkomig/great_alerter_frontend for frontend
- priority: low/normal/high/critical
- Respond to the user in their language (Russian if they write in Russian)"""


def parse_tasks(response: str) -> list[dict]:
    tasks = []
    for m in re.finditer(r"---TASK---\s*(.*?)\s*---END---", response, re.DOTALL):
        task = {}
        key, val = None, []
        for line in m.group(1).strip().split("\n"):
            if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                if key:
                    task[key] = "\n".join(val).strip()
                k, v = line.split(":", 1)
                key, val = k.strip().lower(), [v.strip()] if v.strip() else []
            else:
                val.append(line)
        if key:
            task[key] = "\n".join(val).strip()
        if "title" in task:
            tasks.append(task)
    return tasks


@router.post("/chat")
async def pm_chat(request: ChatRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> ChatResponse:
    chat: ChatSession | None = None
    if request.session_id:
        try:
            chat = await session.get(ChatSession, UUID(request.session_id))
        except:
            pass
    
    if not chat:
        chat = ChatSession(id=uuid4(), title=request.message[:50])
        session.add(chat)
        await session.flush()
    
    session.add(PMChatMessage(id=uuid4(), session_id=chat.id, role="user", content=request.message))
    
    history = await session.execute(
        select(PMChatMessage).where(PMChatMessage.session_id == chat.id).order_by(PMChatMessage.created_at)
    )
    
    ctx = await build_context(session)
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(context=ctx)}]
    for m in history.scalars().all():
        msgs.append({"role": "user" if m.role == "user" else "assistant", "content": m.content})
    
    try:
        llm_resp = await call_llm(msgs)
    except Exception as e:
        return ChatResponse(response=f"Ошибка: {e}", session_id=str(chat.id))
    
    tasks = parse_tasks(llm_resp)
    proposals = [
        TaskProposal(
            title=t.get("title", ""),
            repo=t.get("repo", "zinchenkomig/great_alerter_backend"),
            priority=t.get("priority", "normal"),
            description=t.get("description", ""),
        )
        for t in tasks
    ]
    
    clean = re.sub(r"---TASK---.*?---END---", "", llm_resp, flags=re.DOTALL).strip()
    
    session.add(PMChatMessage(id=uuid4(), session_id=chat.id, role="pm", content=clean))
    chat.updated_at = datetime.now(UTC)
    
    # Log PM activity
    if proposals:
        await log_agent(
            session, "pm", "info",
            f"💬 Chat: proposed {len(proposals)} task(s)",
            details=f"User: {request.message[:200]}\n\nPM: {clean[:500]}\n\nProposals:\n" + "\n".join([f"- {p.title}" for p in proposals])
        )
    else:
        await log_agent(
            session, "pm", "info",
            f"💬 Chat response (no tasks)",
            details=f"User: {request.message[:200]}\n\nPM: {clean[:500]}"
        )
    
    return ChatResponse(response=clean, session_id=str(chat.id), proposals=proposals)


@router.post("/approve")
async def approve_tasks(request: ApproveRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> ApproveResponse:
    created = []
    pmap = {"low": Priority.LOW, "normal": Priority.NORMAL, "high": Priority.HIGH, "critical": Priority.CRITICAL}
    
    prev_task_id = None
    for i, p in enumerate(request.proposals):
        # Each subsequent task depends on the previous one (sequential execution)
        depends_on = [prev_task_id] if prev_task_id else []
        
        task = Task(
            id=uuid4(), 
            title=p.title, 
            description=p.description, 
            status=TaskStatus.QUEUED,
            priority=pmap.get(p.priority, Priority.NORMAL), 
            repo=p.repo, 
            depends_on=depends_on,
            created_at=datetime.now(UTC), 
            created_by="pm"
        )
        session.add(task)
        await session.flush()
        
        prev_task_id = task.id
        dep_info = f" (depends on #{i})" if depends_on else ""
        created.append({
            "id": str(task.id), 
            "title": task.title, 
            "repo": task.repo, 
            "url": f"{DASHBOARD_URL}/tasks?id={task.id}",
            "depends_on": [str(d) for d in depends_on]
        })
    
    if request.session_id:
        try:
            links = "\n".join([f"• [{t['title']}]({t['url']})" for t in created])
            session.add(PMChatMessage(id=uuid4(), session_id=UUID(request.session_id), role="pm",
                                      content=f"✅ Создано: {len(created)}\n\n{links}", task_id=UUID(created[0]["id"]) if created else None))
        except:
            pass
    
    # Log approved tasks
    if created:
        await log_agent(
            session, "pm", "info",
            f"✅ Approved {len(created)} task(s)",
            details="\n".join([f"- {t['title']} ({t['repo']})" for t in created])
        )
    
    return ApproveResponse(created_tasks=created)


@router.get("/sessions")
async def list_sessions(session: Annotated[AsyncSession, Depends(get_session)], limit: int = 20) -> list[SessionSummary]:
    r = await session.execute(select(ChatSession).options(selectinload(ChatSession.messages)).order_by(desc(ChatSession.updated_at)).limit(limit))
    return [SessionSummary(id=str(s.id), title=s.title, created_at=s.created_at, updated_at=s.updated_at, message_count=len(s.messages)) for s in r.scalars().all()]


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> SessionDetail:
    try:
        sid = UUID(session_id)
    except:
        raise HTTPException(400, "Invalid ID")
    r = await session.execute(select(ChatSession).options(selectinload(ChatSession.messages)).where(ChatSession.id == sid))
    chat = r.scalar_one_or_none()
    if not chat:
        raise HTTPException(404)
    return SessionDetail(id=str(chat.id), title=chat.title, created_at=chat.created_at,
                         messages=[{"id": str(m.id), "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in chat.messages])


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, session: Annotated[AsyncSession, Depends(get_session)]):
    try:
        chat = await session.get(ChatSession, UUID(session_id))
    except:
        raise HTTPException(400)
    if not chat:
        raise HTTPException(404)
    await session.delete(chat)
    return {"ok": True}
