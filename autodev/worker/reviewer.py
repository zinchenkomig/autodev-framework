"""The code review: a read-only Claude session that checks the developer's diff with fresh eyes.

The developer's own session is anchored on its own reasoning and misses what it got wrong, so
after it finishes a separate session reviews the branch. Its findings go back to the developer's
session to fix, then the reviewer looks again — up to ``AUTODEV_REVIEW_ROUNDS`` times.
"""

from __future__ import annotations

from typing import Any

from autodev.core.claude import READ_ONLY, ClaudeResult, ClaudeRunner
from autodev.core.models import Project, Task
from autodev.worker import prompts
from autodev.worker.context import WorkerContext

KINDS = ["bug", "edge-case", "missing", "simplify", "naming", "readability", "ux", "tests"]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked"]},
        "summary": {"type": "string", "description": "In Russian, 1-2 sentences: how the change is overall"},
        "findings": {
            "type": "array",
            "description": "What must change, most important first; empty when nothing is worth changing",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": KINDS},
                    "where": {"type": "string", "description": "file:line, or the screen / scenario"},
                    "problem": {"type": "string", "description": "What is wrong, with the failing case"},
                    "fix": {"type": "string", "description": "What it should be instead"},
                },
                "required": ["kind", "where", "problem", "fix"],
            },
        },
    },
    "required": ["status", "summary", "findings"],
}

#: Rounds the reviewer runs on: the task's own work. CI and conflict fixes are narrow repairs.
REVIEWED_FIXES = frozenset({"feedback", "retry"})


def needed(fix: dict | None) -> bool:
    return fix is None or fix.get("kind") in REVIEWED_FIXES


async def review(
    ctx: WorkerContext,
    task: Task,
    project: Project,
    fix: dict | None,
    cwd: str,
    done: str,
    earlier: list[dict],
    log,
    cancelled,
) -> ClaudeResult:
    """One look at the branch; *done* is the developer's summary, *earlier* the previous look's findings."""
    runner = ClaudeRunner(
        cwd,
        model=task.model or project.model or ctx.settings.model,
        timeout=ctx.settings.claude_timeout,
        env=ctx.env(),
        system_prompt_append=prompts.REVIEW_SYSTEM,
        schema=SCHEMA,
        disallowed_tools=READ_ONLY,
    )
    await log("info", "🔍 Ревьюер смотрит изменение")
    asked = fix.get("details", "") if fix and fix.get("kind") == "feedback" else ""
    prompt = prompts.code_review(task, project, asked, done, describe(earlier))
    return await runner.run(prompt, on_log=log, should_cancel=cancelled)


def findings(result: ClaudeResult) -> list[dict]:
    return [f for f in result.data.get("findings") or [] if isinstance(f, dict) and f.get("problem")]


def describe(items: list[dict]) -> str:
    return "\n\n".join(
        f"{i}. [{f.get('kind', '?')}] {f.get('where', '')}\n{f['problem']}\n→ {f.get('fix', '')}"
        for i, f in enumerate(items, 1)
    )
