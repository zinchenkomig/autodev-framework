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
    result = await session.execute(select(ProjectContext.repo))
    repos = [r[0] for r in result.all()]
    parts = []
    for repo in repos:
        docs = await get_repo_docs(repo)
        if docs:
            parts.append(f"# {repo}\n{docs}")
    return "\n\n---\n\n".join(parts)


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


SYSTEM_PROMPT = """Ты PM. Когда пользователь описывает фичу, ты ОБЯЗАТЕЛЬНО создаёшь задачи.

{context}

## ВАЖНО: Всегда создавай задачи!

Твой ответ ДОЛЖЕН содержать:
1. Краткий комментарий (1-2 предложения)
2. Одну или несколько задач в формате ниже

## Формат задачи (ОБЯЗАТЕЛЬНО используй этот формат):

---TASK---
title: Короткое название задачи
repo: zinchenkomig/great_alerter_backend
priority: normal
description: Подробное описание что нужно сделать
---END---

## Пример ответа:

Добавлю новый режим в генератор данных.

---TASK---
title: Режим replace в генераторе деградаций
repo: zinchenkomig/great_alerter_backend
priority: normal
description: Добавить параметр mode в функцию создания деградации. При mode="replace" обновлять существующие записи (UPDATE) вместо создания новых (INSERT). Это позволит инжектировать аномалии в существующие данные.
---END---

## Правила:
- ВСЕГДА генерируй хотя бы одну задачу
- Используй точный формат ---TASK--- и ---END---
- repo: zinchenkomig/great_alerter_backend для бэкенда, zinchenkomig/great_alerter_frontend для фронта
- priority: low/normal/high/critical"""


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
    
    return ChatResponse(response=clean, session_id=str(chat.id), proposals=proposals)


@router.post("/approve")
async def approve_tasks(request: ApproveRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> ApproveResponse:
    created = []
    pmap = {"low": Priority.LOW, "normal": Priority.NORMAL, "high": Priority.HIGH, "critical": Priority.CRITICAL}
    
    for p in request.proposals:
        task = Task(id=uuid4(), title=p.title, description=p.description, status=TaskStatus.QUEUED,
                    priority=pmap.get(p.priority, Priority.NORMAL), repo=p.repo, created_at=datetime.now(UTC), created_by="pm")
        session.add(task)
        await session.flush()
        created.append({"id": str(task.id), "title": task.title, "repo": task.repo, "url": f"{DASHBOARD_URL}/tasks?id={task.id}"})
    
    if request.session_id:
        try:
            links = "\n".join([f"• [{t['title']}]({t['url']})" for t in created])
            session.add(PMChatMessage(id=uuid4(), session_id=UUID(request.session_id), role="pm",
                                      content=f"✅ Создано: {len(created)}\n\n{links}", task_id=UUID(created[0]["id"]) if created else None))
        except:
            pass
    
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
