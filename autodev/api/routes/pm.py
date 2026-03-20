"""PM Agent API routes."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.database import get_session
from autodev.core.models import Task, TaskStatus, Project

router = APIRouter(tags=["pm"])


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


# PM Agent system prompt
PM_SYSTEM_PROMPT = """Ты PM агент в системе AutoDev. Твоя задача — помогать создавать задачи для разработчиков.

Когда пользователь описывает что нужно сделать:
1. Уточни детали если нужно (проект, приоритет, acceptance criteria)
2. Сформулируй чёткое название задачи
3. Напиши подробное описание

Когда готов создать задачу, ответь в формате:
---TASK---
title: <название задачи>
project: <проект, например great_alerter_backend или great_alerter_frontend>
priority: <low/medium/high/critical>
description: <подробное описание что нужно сделать>
---END---

Доступные проекты:
- great_alerter_backend
- great_alerter_frontend
- autodev-framework

После создания задачи, сообщи пользователю номер задачи."""


async def call_llm(messages: list[dict]) -> str:
    """Call LLM API."""
    import httpx
    
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Ошибка: API ключ не настроен"
    
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("PM_MODEL", "anthropic/claude-sonnet-4-20250514")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 1024,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


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
    
    # Build messages for LLM
    messages = [{"role": "system", "content": PM_SYSTEM_PROMPT}]
    
    for msg in request.history:
        messages.append({"role": msg.role if msg.role != "pm" else "assistant", "content": msg.content})
    
    messages.append({"role": "user", "content": request.message})
    
    # Call LLM
    llm_response = await call_llm(messages)
    
    # Check if task should be created
    task_data = parse_task_from_response(llm_response)
    task_id = None
    task_created = False
    
    if task_data:
        # Find or create project
        project_name = task_data.get("project", "autodev-framework")
        project = await session.scalar(select(Project).where(Project.name == project_name))
        
        if not project:
            # Create project if doesn't exist
            project = Project(
                id=uuid4(),
                name=project_name,
                repo_url=f"https://github.com/zinchenkomig/{project_name}",
                created_at=datetime.now(UTC),
            )
            session.add(project)
            await session.flush()
        
        # Create task
        priority_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        priority = priority_map.get(task_data.get("priority", "medium"), 2)
        
        task = Task(
            id=uuid4(),
            title=task_data["title"],
            description=task_data["description"],
            status=TaskStatus.QUEUED,
            priority=priority,
            project_id=project.id,
            created_at=datetime.now(UTC),
        )
        session.add(task)
        await session.flush()
        
        task_id = str(task.id)
        task_created = True
        
        # Clean response - remove task block and add confirmation
        clean_response = re.sub(r"---TASK---.*?---END---", "", llm_response, flags=re.DOTALL).strip()
        llm_response = f"{clean_response}\n\n✅ Задача создана: #{task_id[:8]}"
    
    return ChatResponse(
        response=llm_response,
        task_created=task_created,
        task_id=task_id,
    )
