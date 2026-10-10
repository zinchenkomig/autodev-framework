"""Triage: decide which repo(s) a task touches in a multi-repo project.

The original task becomes the first part; further parts become new tasks
that depend on the previous one (e.g. backend API first, then frontend).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from autodev.core.claude import ClaudeRunner
from autodev.core.models import Project, Task, TaskStatus
from autodev.worker.context import WorkerContext


class RateLimited(Exception):
    def __init__(self, until) -> None:
        super().__init__(f"Claude limit until {until}")
        self.until = until


def triage_schema(project: Project) -> dict:
    names = [r["name"] for r in project.repos]
    return {
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "enum": names},
                        "title": {"type": "string", "description": "short imperative title, task language"},
                        "description": {
                            "type": "string",
                            "description": "what to do in this repo, incl. contracts shared with other parts",
                        },
                    },
                    "required": ["repo", "title", "description"],
                },
            }
        },
        "required": ["parts"],
    }


def triage_prompt(task: Task, project: Project) -> str:
    repos = "\n".join(f"- {r['name']} (role: {r.get('role', 'app')})" for r in project.repos)
    return f"""\
Decide where this task has to be implemented. Do not change any code.

Project: {project.name}
Repositories:
{repos}

Task #{task.ticket_number}: {task.title}
{task.description or ""}

You may look at the repositories with `gh` (e.g. `gh api repos/OWNER/REPO/contents/CLAUDE.md`,
`gh search code --repo OWNER/REPO ...`) if the right place isn't obvious.

Return the parts in execution order — one per repository that needs changes, with
the provider of an API before its consumers. Use a single part when one repo is
enough. Keep the owner's wording; add the shared contract (endpoints, fields) to
each part's description when parts depend on each other."""


async def triage(ctx: WorkerContext, task: Task, project: Project, log) -> Task:
    """Assign a repo to *task* (creating follow-up tasks for extra repos). Returns the updated task."""
    workdir = Path(ctx.settings.workdir) / "triage" / str(task.id)
    workdir.mkdir(parents=True, exist_ok=True)
    runner = ClaudeRunner(
        str(workdir),
        model=project.model or ctx.settings.model,
        timeout=600,
        env=ctx.env(),
        schema=triage_schema(project),
    )
    await log("info", "🧭 Triage: choosing repositories")
    result = await runner.run(triage_prompt(task, project), on_log=log)
    if result.rate_limited:
        raise RateLimited(result.rate_limited_until)
    parts = result.data.get("parts") or []
    if not result.ok or not parts:
        raise RuntimeError(f"Triage failed: {result.summary}")

    first, rest = parts[0], parts[1:]
    description = task.description or ""
    if len(parts) > 1:
        description = f"{description}\n\n## This part ({first['repo']})\n{first['description']}".strip()
    updated = await ctx.store.update(task.id, repo=first["repo"], description=description) or task

    previous = task.id
    async with ctx.session_factory() as session:
        for part in rest:
            child = Task(
                id=uuid.uuid4(),
                title=part["title"],
                description=f"{part['description']}\n\n---\nPart of #{task.ticket_number}: {task.title}",
                project_id=project.id,
                repo=part["repo"],
                priority=task.priority,
                depends_on=[previous],
                created_by="triage",
                status=TaskStatus.QUEUED,
                metadata_={},
            )
            session.add(child)
            previous = child.id
        await session.commit()

    plan = "\n".join(f"{i + 1}. [{p['repo']}] {p['title']}" for i, p in enumerate(parts))
    await log("info", f"🧭 Triage: {len(parts)} part(s)", plan)
    return updated
