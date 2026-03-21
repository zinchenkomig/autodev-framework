"""PM Agent API routes."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.api.database import get_session
from autodev.core.models import Task, TaskStatus, Priority
from autodev.project_contexts import get_all_projects_context

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


def get_pm_system_prompt() -> str:
    """Build PM system prompt with project contexts."""
    projects_context = get_all_projects_context()
    
    return f"""Ты PM агент в системе AutoDev. Твоя задача — помогать создавать задачи для разработчиков.

## Проекты которыми ты управляешь:
{projects_context}

## Как работать:
1. Когда пользователь описывает что нужно — ты уже знаешь контекст проекта
2. Уточни детали только если непонятно ЧТО именно делать
3. Не спрашивай про стек/архитектуру — ты это знаешь
4. Сразу предлагай конкретное решение исходя из знания проекта

## Создание задачи:
Когда готов создать задачу, ответь в формате:
---TASK---
title: <краткое название задачи>
repo: <полный путь репозитория, например zinchenkomig/great_alerter_backend>
priority: <low/normal/high/critical>
description: <подробное описание что нужно сделать, с техническими деталями>
---END---

Пиши description так, чтобы разработчик мог сразу приступить к работе.
Включай конкретные файлы/компоненты если знаешь где менять.
"""


async def call_llm(messages: list[dict]) -> str:
    """Call LLM API - supports OpenRouter and Anthropic direct."""
    import httpx
    
    # Try OpenRouter first
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
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
    
    # Try Anthropic direct
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        model = os.environ.get("PM_MODEL", "claude-sonnet-4-20250514")
        
        system_content = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                user_messages.append(msg)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 2048,
                    "system": system_content,
                    "messages": user_messages,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
    
    return "Ошибка: API ключ не настроен. Установите OPENROUTER_API_KEY или ANTHROPIC_API_KEY."


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
    system_prompt = get_pm_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in request.history:
        messages.append({
            "role": "user" if msg.role == "user" else "assistant",
            "content": msg.content
        })
    
    messages.append({"role": "user", "content": request.message})
    
    # Call LLM
    try:
        llm_response = await call_llm(messages)
    except Exception as e:
        return ChatResponse(response=f"Ошибка при вызове LLM: {e}")
    
    # Check if task should be created
    task_data = parse_task_from_response(llm_response)
    task_id = None
    task_created = False
    
    if task_data:
        # Map priority
        priority_map = {
            "low": Priority.LOW,
            "normal": Priority.NORMAL,
            "high": Priority.HIGH,
            "critical": Priority.CRITICAL,
        }
        priority = priority_map.get(task_data.get("priority", "normal"), Priority.NORMAL)
        
        # Create task
        task = Task(
            id=uuid4(),
            title=task_data["title"],
            description=task_data["description"],
            status=TaskStatus.QUEUED,
            priority=priority,
            repo=task_data.get("repo", "zinchenkomig/great_alerter_backend"),
            created_at=datetime.now(UTC),
            created_by="pm_agent",
        )
        session.add(task)
        await session.flush()
        
        task_id = str(task.id)
        task_created = True
        
        # Clean response
        clean_response = re.sub(r"---TASK---.*?---END---", "", llm_response, flags=re.DOTALL).strip()
        llm_response = f"{clean_response}\n\n✅ Задача создана: `{task.title}`\nID: {task_id[:8]}"
    
    return ChatResponse(
        response=llm_response,
        task_created=task_created,
        task_id=task_id,
    )
