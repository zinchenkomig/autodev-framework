"""The PM's brief: one read-only Claude session before the developer's first round (see :mod:`autodev.pm`)."""

from __future__ import annotations

from typing import Any

from autodev import pm
from autodev.core.claude import ClaudeResult, ClaudeRunner
from autodev.core.models import Project, Task
from autodev.worker import prompts
from autodev.worker.context import WorkerContext

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked"]},
        "brief": {
            "type": "string",
            "description": "The brief for the developer in Russian Markdown: «Что и зачем», «Сценарии», «Решения», "
            "«Не делаем», «Готово, когда» — shorter for a small task",
        },
        "summary": {"type": "string", "description": "When blocked: why"},
    },
    "required": ["status", "brief"],
}

#: Tasks the PM doesn't think through: QA's fixes are about errors, not product questions,
#: and the PM's own follow-ups from acceptance are a brief already.
SKIP_CREATED_BY = frozenset({"qa", pm.PM_AUTHOR})


def needed(task: Task, fix: dict | None, existing: bool) -> bool:
    """A brief before the first round of a task the PM works on (a retry keeps the brief it has)."""
    if existing or (fix and fix.get("kind") != "retry"):
        return False
    return pm.enabled(task) and pm.brief(task) is None and task.created_by not in SKIP_CREATED_BY


async def write(
    ctx: WorkerContext, task: Task, project: Project, main: Task | None, cwd: str, log, cancelled
) -> ClaudeResult:
    async with ctx.session_factory() as session:
        history = await pm.history(session, project.id)
    runner = ClaudeRunner(
        cwd,
        model=project.model or ctx.settings.model,
        timeout=ctx.settings.claude_timeout,
        env=ctx.env(),
        system_prompt_append=prompts.PM_SYSTEM,
        schema=SCHEMA,
        disallowed_tools=["Edit", "Write", "NotebookEdit"],
    )
    await log("info", "📝 PM продумывает задачу")
    return await runner.run(prompts.pm_brief(task, project, main, history), on_log=log, should_cancel=cancelled)
