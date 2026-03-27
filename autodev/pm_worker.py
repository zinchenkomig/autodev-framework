"""Autonomous PM Worker — proposes tasks periodically.

Runs as a background loop in the orchestrator. Every hour:
1. Reads PROJECT.md / CLAUDE.md from repos
2. Checks current tasks (in progress, queued, ready)
3. Checks GitHub issues
4. Asks LLM to propose new tasks
5. Creates tasks and notifies user
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.models import Task, TaskStatus, Priority, ProjectContext

logger = logging.getLogger(__name__)

PM_INTERVAL_SECONDS = int(os.environ.get("PM_INTERVAL", "3600"))  # 1 hour default


async def get_repo_docs(repo: str) -> str:
    """Fetch PROJECT.md and CLAUDE.md from repo."""
    token = os.environ.get("GITHUB_TOKEN", "")
    docs = []
    for path in ["PROJECT.md", "CLAUDE.md"]:
        url = f"https://raw.githubusercontent.com/{repo}/develop/{path}"
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"token {token}"} if token else {}
                resp = await client.get(url, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    docs.append(f"# {path}\n{resp.text[:4000]}")
        except Exception:
            pass
    return "\n\n".join(docs)


async def get_github_issues(repo: str, limit: int = 10) -> list[dict]:
    """Fetch open GitHub issues."""
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/issues",
                headers={"Authorization": f"token {token}"} if token else {},
                params={"state": "open", "per_page": limit},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return [
                    {"number": i["number"], "title": i["title"], "labels": [l["name"] for l in i.get("labels", [])]}
                    for i in resp.json()
                    if "pull_request" not in i  # Skip PRs
                ]
    except Exception as e:
        logger.warning(f"Failed to fetch issues for {repo}: {e}")
    return []


async def call_pm_llm(messages: list[dict]) -> str:
    """Call the PM LLM model."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return ""
    
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("PM_MODEL", "z-ai/glm-5-turbo")
    
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 4000},
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def parse_tasks(response: str) -> list[dict]:
    """Parse tasks from LLM response."""
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


async def run_pm_cycle(session_factory: async_sessionmaker) -> list[dict]:
    """Run one PM cycle: analyze repos, propose and create tasks."""
    
    async with session_factory() as session:
        # 1. Get repos
        result = await session.execute(select(ProjectContext.repo))
        repos = [r[0] for r in result.all()]
        
        if not repos:
            logger.info("PM Worker: no repos configured")
            return []
        
        # 2. Get current tasks and check backlog limit
        result = await session.execute(
            select(Task).where(
                Task.status.in_([
                    TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, 
                    TaskStatus.AUTOREVIEW, TaskStatus.READY_TO_RELEASE,
                    TaskStatus.STAGING
                ])
            )
        )
        active_tasks = result.scalars().all()
        active_titles = [t.title for t in active_tasks]
        
        # Check backlog SP limit
        backlog_sp = sum(t.story_points or 1 for t in active_tasks)
        max_backlog_sp = int(os.environ.get("MAX_BACKLOG_SP", "15"))
        
        if backlog_sp >= max_backlog_sp:
            logger.info(f"PM Worker: backlog full ({backlog_sp}/{max_backlog_sp} SP). Skipping.")
            return []
        
        # 3. Build context
        repo_docs = []
        all_issues = []
        for repo in repos:
            docs = await get_repo_docs(repo)
            if docs:
                repo_docs.append(docs)
            issues = await get_github_issues(repo)
            all_issues.extend(issues)
        
        project_context = "\n\n---\n\n".join(repo_docs) if repo_docs else "No project docs found"
        
        issues_text = ""
        if all_issues:
            issues_text = "\n## Open GitHub Issues:\n"
            issues_text += "\n".join([f"- #{i['number']}: {i['title']} [{', '.join(i['labels'])}]" for i in all_issues])
        
        active_text = ""
        if active_titles:
            active_text = "\n## Current Active Tasks (DO NOT duplicate):\n"
            active_text += "\n".join([f"- {t}" for t in active_titles])
        
        # 4. Ask LLM to propose tasks
        system_prompt = f"""Ты автономный PM-агент. Твоя задача — анализировать проект и предлагать улучшения.

{project_context}

{issues_text}

{active_text}

## Правила:
- Предлагай только ПОЛЕЗНЫЕ задачи которые улучшат проект
- НЕ дублируй уже существующие задачи
- НЕ создавай задачи для issues которые уже покрыты активными задачами
- Максимум 3 задачи за раз
- Фокусируйся на: баги, производительность, безопасность, UX, тесты
- Используй формат ---TASK--- / ---END---
- repo: полное имя (zinchenkomig/great_alerter_backend или zinchenkomig/great_alerter_frontend)
- priority: low/normal/high/critical
- Если нет хороших идей — ответь "NO_TASKS" (лучше ничего, чем мусор)

## Формат задачи:

---TASK---
title: Короткое название
repo: zinchenkomig/great_alerter_backend
priority: normal
story_points: 2
description: Подробное описание
---END---

## Story Points (оценка сложности):
- 1 — тривиальное изменение (фикс опечатки, правка конфига)
- 2 — простая задача (добавить поле, маленький рефакторинг)
- 3 — средняя задача (новый эндпоинт, компонент)
- 5 — сложная задача (новая фича, интеграция)
- 8 — очень сложная (архитектурное изменение, миграция)"""

        user_msg = "Проанализируй проект и предложи задачи для улучшения. Сфокусируйся на том что принесёт наибольшую пользу."
        
        try:
            response = await call_pm_llm([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ])
        except Exception as e:
            logger.error(f"PM Worker: LLM call failed: {e}")
            return []
        
        if "NO_TASKS" in response:
            logger.info("PM Worker: no tasks proposed")
            return []
        
        # 5. Parse and create tasks
        proposed = parse_tasks(response)
        if not proposed:
            logger.info("PM Worker: no tasks parsed from response")
            return []
        
        pmap = {"low": Priority.LOW, "normal": Priority.NORMAL, "high": Priority.HIGH, "critical": Priority.CRITICAL}
        created = []
        
        prev_task_id = None
        for p in proposed:
            # Skip if title is too similar to existing
            title = p.get("title", "")
            if any(title.lower() in t.lower() or t.lower() in title.lower() for t in active_titles):
                logger.info(f"PM Worker: skipping duplicate '{title}'")
                continue
            
            depends_on = [prev_task_id] if prev_task_id else []
            
            # Parse story_points (default 2)
            try:
                sp = int(p.get("story_points", "2"))
                sp = max(1, min(sp, 13))  # clamp to 1-13
            except (ValueError, TypeError):
                sp = 2
            
            task = Task(
                id=uuid4(),
                title=title,
                description=p.get("description", ""),
                status=TaskStatus.QUEUED,
                priority=pmap.get(p.get("priority", "normal"), Priority.NORMAL),
                story_points=sp,
                repo=p.get("repo", ""),
                depends_on=depends_on,
                created_by="pm-auto",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(task)
            await session.flush()
            prev_task_id = task.id
            created.append({"id": str(task.id), "title": title, "repo": task.repo})
        
        await session.commit()
        
        logger.info(f"PM Worker: created {len(created)} tasks")
        return created


async def notify_new_tasks(tasks: list[dict]) -> None:
    """Notify user about auto-created tasks via Telegram."""
    if not tasks:
        return
    
    try:
        from autodev.integrations.telegram_pm import get_telegram_bot
        bot = await get_telegram_bot()
        
        text = f"📋 <b>PM Agent создал {len(tasks)} задач(и):</b>\n\n"
        for t in tasks:
            text += f"• <b>{t['title']}</b>\n  <i>{t['repo']}</i>\n\n"
        text += "Задачи в очереди. Удалите ненужные через Dashboard."
        
        await bot.send_message(bot.owner_chat_id, text)
    except Exception as e:
        logger.warning(f"PM Worker: failed to notify: {e}")


async def pm_worker_loop(session_factory: async_sessionmaker) -> None:
    """Endless loop: run PM cycle every hour."""
    import asyncio
    
    logger.info(f"PM Worker started — running every {PM_INTERVAL_SECONDS}s")
    
    # Wait 2 minutes on startup before first run
    await asyncio.sleep(120)
    
    while True:
        try:
            created = await run_pm_cycle(session_factory)
            if created:
                await notify_new_tasks(created)
        except Exception:
            logger.exception("PM Worker: unhandled error")
        
        await asyncio.sleep(PM_INTERVAL_SECONDS)
