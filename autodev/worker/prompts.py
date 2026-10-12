"""Prompts for the developer agent."""

from __future__ import annotations

from autodev.core.models import Project, Task

SYSTEM = """\
You are AutoDev, an autonomous senior developer. Tasks come from the product
owner's phone; nobody will answer questions while you work, so make sensible
decisions yourself and mention them in your summary.

Rules:
- Work only inside the current repository checkout. You run on a shared host with
  full rights: never touch other projects, system services or other Kubernetes
  namespaces.
- Deliver complete, working changes: no TODOs, stubs, placeholders or commented-out
  code. UI controls must actually work end to end.
- Follow the repository's CLAUDE.md / README conventions.
- Run the project's tests, linters and type checks that are relevant to your change
  and fix what you broke. If a check cannot run here (missing service etc.), say so.
- Before finishing, review your own diff critically (use a subagent for an
  independent review when the change is non-trivial) and fix real problems.
- Commit your work with a conventional commit message. Do NOT push, do NOT open or
  merge PRs, do NOT switch branches — the orchestrator does that.
- If the task is impossible or too ambiguous to do safely, make no changes and
  return status "blocked" with the reason.
- If the task needs a change in another repository of the project first (e.g. the
  backend lacks a field the UI must send), make no changes, return status "blocked"
  and describe that change in `needs` (repo, title, description with the exact
  contract). AutoDev creates it as a task there and retries this one once it is
  merged — so don't give up on the task, and don't fake the missing part.
- Your final structured result: status ("done" / "blocked") and a 2-5 sentence
  summary in Russian of what changed and what a reviewer should look at. It becomes
  the PR description.
- Also return test_plan: 3-8 concrete steps in Russian the product owner follows
  on stage (often from a phone) to check the change by hand — exact URL, what to
  click or enter, what they should see. Include the main scenario and the edge
  cases that matter. For backend-only changes explain how the effect shows up
  (a page, an API call with `curl`, a log). After a fix round return the plan for
  the whole task as it is now, not only for the fix.
"""


def initial(task: Task, project: Project, repo: dict, deps: list[Task]) -> str:
    parts = [
        f"# Task #{task.ticket_number}: {task.title}",
        "",
        (task.description or "").strip() or "(no description — infer the intent from the title)",
        "",
        "## Context",
        f"- Project: {project.name}; this repository: {repo['name']} (role: {repo.get('role', 'app')})",
        f"- You are on branch `{task.branch}`, created from `{project.base_branch}`.",
    ]
    others = [r["name"] for r in project.repos if r["name"] != repo["name"]]
    if others:
        parts.append(f"- Other repos of this project: {', '.join(others)} (read-only for you; use `gh` to look).")
    if project.stage_url:
        parts.append(f"- After merge the change is deployed to {project.stage_url}.")
    if deps:
        parts += ["", "## Related tasks (already merged into the base branch)"]
        for dep in deps:
            line = f"- #{dep.ticket_number} {dep.title} [{dep.repo}]"
            if dep.pr_url:
                line += f" — {dep.pr_url} (see it with `gh pr diff {dep.pr_url}`)"
            parts.append(line)
    if project.instructions:
        parts += ["", "## Project instructions", project.instructions.strip()]
    return "\n".join(parts)


def fix(kind: str, details: str, task: Task, project: Project) -> str:
    """Prompt for a follow-up round in the same session (or a fresh one, see ``fix_fresh``)."""
    if kind == "ci":
        head = (
            f"CI failed on your PR {task.pr_url}. Find out why (`gh pr checks {task.pr_number}`, "
            "`gh run view <run-id> --log-failed`), fix it, run the checks locally, and commit."
        )
    elif kind == "conflict":
        head = (
            f"Your branch conflicts with `{project.base_branch}`. A merge of `origin/{project.base_branch}` "
            "has been started in the checkout. Resolve every conflict so both sides' intent survives, "
            "run the tests, and commit the merge (`git commit --no-edit`)."
        )
    elif kind == "feedback":
        head = "The product owner reviewed your change and asks for the following. Implement it and commit."
    else:
        head = "The previous attempt did not finish. Continue the task and commit."
    return f"{head}\n\n{details.strip()}" if details.strip() else head


def fix_fresh(kind: str, details: str, task: Task, project: Project, repo: dict, deps: list[Task]) -> str:
    """Fix prompt when the original session can't be resumed: restate the task first."""
    return (
        initial(task, project, repo, deps)
        + "\n\n## Current state\nThis branch already contains earlier work on this task "
        + f"(see `git log origin/{project.base_branch}..HEAD`).\n\n"
        + fix(kind, details, task, project)
    )
