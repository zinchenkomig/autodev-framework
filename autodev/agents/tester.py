"""Tester Agent - E2E testing with Playwright like a real user."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from autodev.core.models import Agent, AgentLog, AgentStatus, Task, TaskStatus

logger = logging.getLogger(__name__)


TESTER_SYSTEM_PROMPT = """Ты Tester агент. Анализируешь изменения в PR и составляешь план тестирования.

Для каждого PR ты должен:
1. Понять что изменилось (какие файлы, какая функциональность)
2. Составить план E2E тестирования как реальный пользователь
3. Написать Playwright тесты

Формат ответа:
---TEST_PLAN---
summary: <краткое описание что тестируем>
scenarios:
  - name: <название сценария>
    steps:
      - <шаг 1>
      - <шаг 2>
    expected: <ожидаемый результат>
---END---

---PLAYWRIGHT_TEST---
<код теста на TypeScript>
---END---
"""


async def call_llm(messages: list[dict]) -> str:
    """Call LLM API."""
    import httpx
    
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Error: API key not configured"
    
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("TESTER_MODEL", "anthropic/claude-sonnet-4-20250514")
    
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
                "max_tokens": 4096,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def get_pr_diff(repo: str, pr_number: int, token: str) -> str:
    """Get PR diff from GitHub."""
    import httpx
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3.diff",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.text


def parse_test_plan(response: str) -> dict | None:
    """Parse test plan from LLM response."""
    if "---TEST_PLAN---" not in response:
        return None
    
    match = re.search(r"---TEST_PLAN---\s*(.*?)\s*---END---", response, re.DOTALL)
    if not match:
        return None
    
    return {"raw": match.group(1)}


def parse_playwright_test(response: str) -> str | None:
    """Extract Playwright test code."""
    if "---PLAYWRIGHT_TEST---" not in response:
        return None
    
    match = re.search(r"---PLAYWRIGHT_TEST---\s*(.*?)\s*---END---", response, re.DOTALL)
    if not match:
        return None
    
    return match.group(1).strip()


async def run_playwright_test(test_code: str, base_url: str) -> tuple[bool, str]:
    """Run Playwright test and return result."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.spec.ts"
        test_file.write_text(f"""
import {{ test, expect }} from '@playwright/test';

test.use({{ baseURL: '{base_url}' }});

{test_code}
""")
        
        # Run playwright test
        proc = await asyncio.create_subprocess_exec(
            "npx", "playwright", "test", str(test_file), "--reporter=line",
            cwd=tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        
        output = stdout.decode()
        success = proc.returncode == 0
        
        return success, output


class TesterAgent:
    """Tester agent that creates and runs E2E tests."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.github_token = os.environ.get("GITHUB_TOKEN", "")
    
    async def _log(self, task_id, level: str, message: str):
        """Log a message."""
        log = AgentLog(
            id=uuid4(),
            agent_id="tester",
            task_id=task_id,
            level=level,
            message=message,
            created_at=datetime.now(UTC),
        )
        self.session.add(log)
        await self.session.flush()
    
    async def _update_status(self, status: AgentStatus, task_id=None):
        """Update agent status."""
        agent = await self.session.get(Agent, "tester")
        if agent:
            agent.status = status
            agent.current_task_id = task_id
            if status == AgentStatus.IDLE:
                agent.last_run_at = datetime.now(UTC)
            await self.session.flush()
    
    async def process_task(self, task: Task) -> bool:
        """Process a task in review status."""
        try:
            await self._update_status(AgentStatus.WORKING, task.id)
            await self._log(task.id, "info", f"Starting to test: {task.title}")
            
            # Get PR info if available
            pr_diff = ""
            if task.pr_url:
                # Parse PR URL: https://github.com/owner/repo/pull/123
                match = re.match(r"https://github.com/([^/]+/[^/]+)/pull/(\d+)", task.pr_url)
                if match:
                    repo, pr_num = match.groups()
                    try:
                        pr_diff = await get_pr_diff(repo, int(pr_num), self.github_token)
                        await self._log(task.id, "info", f"Got PR diff: {len(pr_diff)} chars")
                    except Exception as e:
                        await self._log(task.id, "warning", f"Failed to get PR diff: {e}")
            
            # Call LLM to create test plan
            messages = [
                {"role": "system", "content": TESTER_SYSTEM_PROMPT},
                {"role": "user", "content": f"""
Задача: {task.title}
Описание: {task.description or 'нет описания'}

PR Diff:
```
{pr_diff[:8000] if pr_diff else 'PR diff недоступен'}
```

Составь план тестирования и напиши Playwright тест.
"""},
            ]
            
            llm_response = await call_llm(messages)
            await self._log(task.id, "info", "Got test plan from LLM")
            
            # Parse test plan
            test_plan = parse_test_plan(llm_response)
            if test_plan:
                await self._log(task.id, "info", f"Test plan: {test_plan['raw'][:500]}")
            
            # Parse and run Playwright test
            test_code = parse_playwright_test(llm_response)
            if test_code:
                await self._log(task.id, "info", "Running Playwright test...")
                
                # Determine base URL based on project
                base_url = "https://staging.alerter.zinchenkomig.com"
                if task.project and "autodev" in task.project.name:
                    base_url = "https://autodev.zinchenkomig.com"
                
                success, output = await run_playwright_test(test_code, base_url)
                
                if success:
                    await self._log(task.id, "info", "✅ All tests passed!")
                    # Move to ready_to_release
                    task.status = TaskStatus.READY_TO_RELEASE
                    await self._log(task.id, "info", "Task moved to ready_to_release")
                else:
                    await self._log(task.id, "error", f"❌ Tests failed:\n{output[:1000]}")
                    # Keep in review for developer to fix
                    await self._log(task.id, "info", "Task stays in review - needs fixes")
            else:
                await self._log(task.id, "warning", "No Playwright test generated, manual review needed")
            
            await self._update_status(AgentStatus.IDLE)
            return True
            
        except Exception as e:
            logger.exception("Tester agent error")
            await self._log(task.id, "error", f"Error: {e}")
            await self._update_status(AgentStatus.FAILED)
            return False
    
    async def run(self):
        """Main loop - process tasks in review status."""
        agent = await self.session.get(Agent, "tester")
        if not agent or not agent.enabled:
            logger.debug("Tester agent is disabled")
            return
        
        # Find tasks in review
        stmt = select(Task).where(Task.status == TaskStatus.REVIEW).order_by(Task.created_at)
        result = await self.session.execute(stmt)
        tasks = result.scalars().all()
        
        for task in tasks:
            await self.process_task(task)
            await asyncio.sleep(1)  # Small delay between tasks
