"""Prompts for the developer agent, the test-plan writer and the chat agent."""

from __future__ import annotations

from autodev.core.models import Project, Task

TEST_PLAN_RULES = """\
- Also return test_plan: 3-10 concrete steps in Russian the product owner follows
  on stage (often from a phone) to check the change by hand. The owner doesn't
  know the app's URLs, so walk them there through the UI:
  - Step 1 opens the stage home page (its full URL); no other step names a URL
    or path like /checks.
  - Every next step is one action on what is visible on screen: which menu item,
    tab, button or link to tap, named exactly as its label reads in the UI (in
    «quotes»), and where it is (top menu, sidebar, ☰ menu on a phone, card list…).
    Look the labels and the navigation up in the code — don't guess them.
  - If getting there needs data first (log in, create an item), include those
    steps too.
  - Then what to do and what they should see as a result.
  Include the main scenario and the edge cases that matter. For backend-only
  changes explain how the effect shows up in the UI (or, if it doesn't, an API
  call with `curl` or a log). After a fix round return the plan for the whole
  task as it is now, not only for the fix.
  When the task is a follow-up or part of a main task, the owner checks the main
  task as a whole with one plan: return that whole plan, updated for your change.
"""

SYSTEM = (
    """\
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
- The repository holds the whole project: when a change spans several apps in it
  (e.g. a backend field and the UI that uses it), make all of it here, in one change.
- Your final structured result: status ("done" / "blocked") and a 2-5 sentence
  summary in Russian of what changed and what a reviewer should look at. It becomes
  the PR description.
"""
    + TEST_PLAN_RULES
)


def initial(task: Task, project: Project, repo: dict, deps: list[Task], main: Task | None = None) -> str:
    parts = [
        f"# Task #{task.ticket_number}: {task.title}",
        "",
        (task.description or "").strip() or "(no description — infer the intent from the title)",
        "",
        "## Context",
        f"- Project: {project.name}; repository: {repo['name']}",
        f"- You are on branch `{task.branch}`, created from `{project.base_branch}`.",
    ]
    if project.stage_url:
        parts.append(f"- After merge the change is deployed to {project.stage_url}.")
    if deps:
        parts += ["", "## Related tasks (already merged into the base branch)"]
        for dep in deps:
            line = f"- #{dep.ticket_number} {dep.title}"
            if dep.pr_url:
                line += f" — {dep.pr_url} (see it with `gh pr diff {dep.pr_url}`)"
            parts.append(line)
    if main is not None:
        parts += ["", _main_task(main)]
    if project.instructions:
        parts += ["", "## Project instructions", project.instructions.strip()]
    return "\n".join(parts)


def _main_task(main: Task) -> str:
    """Section for a follow-up/part: the owner checks the main task once, by one plan."""
    lines = [
        f"## Main task #{main.ticket_number}: {main.title}",
        "This task is a follow-up to (or a part of) the main task. The owner checks the main task",
        "as a whole, by one test plan, once all of its work is on stage — not this task separately.",
    ]
    plan = (main.metadata_ or {}).get("test_plan") or []
    if plan:
        lines += ["", "Its current test plan:"] + [f"{i}. {step}" for i, step in enumerate(plan, 1)]
        lines += [
            "",
            "Return test_plan as this whole plan updated for your change: keep the steps that still",
            "hold, rewrite the ones your change affects, add steps for what you added or fixed.",
        ]
    else:
        lines += ["", "Return test_plan for the main task as a whole, including your change."]
    return "\n".join(lines)


def fix(kind: str, details: str, task: Task, project: Project, main: Task | None = None) -> str:
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
    text = f"{head}\n\n{details.strip()}" if details.strip() else head
    if main is not None:
        text += f"\n\nAs before, test_plan is the whole plan of main task #{main.ticket_number}."
    return text


def fix_fresh(
    kind: str, details: str, task: Task, project: Project, repo: dict, deps: list[Task], main: Task | None = None
) -> str:
    """Fix prompt when the original session can't be resumed: restate the task first."""
    return (
        initial(task, project, repo, deps, main)
        + "\n\n## Current state\nThis branch already contains earlier work on this task "
        + f"(see `git log origin/{project.base_branch}..HEAD`).\n\n"
        + fix(kind, details, task, project)
    )


PLANNER_SYSTEM = (
    """\
You are AutoDev's test-plan writer. The product owner checks a main task on stage
as a whole — the task itself and all its follow-ups and parts — by one manual test
plan. Your job: write that one plan as the code on stage is now. Nobody will answer
questions while you work.

Rules:
- The current directory holds a read-only checkout of the stage branch of every
  repository involved, one subdirectory per repo. Read code, `git log` and
  `gh pr diff <url>`; don't change files, commit, push or touch anything outside.
- Describe what is on stage now: a later follow-up may have changed or replaced
  what an earlier one did; the plan follows the latest behaviour.
- Plans written earlier for the task or its follow-ups are hints, not truth: check
  every label and every navigation step against the code.
- Return status "done", a 1-3 sentence summary in Russian of what the plan covers,
  and test_plan. Return "blocked" with the reason only if no plan can be written.
- The plan covers the whole main task, so it may be longer than 10 steps
  (at most 20): group related checks into one step rather than dropping them.
"""
    + TEST_PLAN_RULES
)


def plan_refresh(main: Task, children: list[Task], project: Project, repos: list[str]) -> str:
    """Prompt for rebuilding a main task's one test plan from the task and its landed follow-ups."""
    parts = [f"# Test plan for main task #{main.ticket_number}: {main.title}", ""]
    if project.stage_url:
        parts.append(f"Stage: {project.stage_url}")
    parts.append("Checkouts here (stage branch): " + ", ".join(f"`{r.split('/')[-1]}/` = {r}" for r in repos))
    parts += ["", _task_section("The main task", main)]
    for child in children:
        parts += ["", _task_section(f"Follow-up / part #{child.ticket_number}", child)]
    plan = (main.metadata_ or {}).get("test_plan") or []
    if plan:
        parts += ["", "## The main task's current plan (may be outdated or incomplete)"]
        parts += [f"{i}. {step}" for i, step in enumerate(plan, 1)]
    parts += [
        "",
        "Return test_plan: the one plan for the main task with all of the above, as it works on stage now.",
    ]
    if project.instructions:
        parts += ["", "## Project instructions", project.instructions.strip()]
    return "\n".join(parts)


def _task_section(heading: str, task: Task) -> str:
    lines = [f"## {heading}: {task.title}"]
    if task.repo:
        lines.append(f"Repository: {task.repo}" + (f"; PR {task.pr_url}" if task.pr_url else ""))
    lines += ["", "What the owner asked:", (task.description or "").strip()[:4000] or "(only the title)"]
    if task.summary:
        lines += ["", "What the agent did:", task.summary.strip()[:3000]]
    metadata = task.metadata_ or {}
    proposal = metadata.get("root_plan")
    plan = metadata.get("test_plan") or (proposal.get("plan") if isinstance(proposal, dict) else None) or []
    if task.parent_id and plan:
        lines += ["", "The plan its agent wrote then:"] + [f"{i}. {step}" for i, step in enumerate(plan, 1)]
    return "\n".join(lines)


CHAT_SYSTEM = """\
You are AutoDev's assistant in a chat with the product owner. AutoDev is the owner's
system where agents implement tasks the owner sends from a phone and ship them to
stage. The owner writes from a phone, often while checking a task on stage by its
test plan: a term they don't know, a question about how something works or why it
was done this way.

How to answer:
- In Russian, short and to the point: a few sentences or a short list, readable on
  a phone. Light Markdown only (lists, **bold**, `code`), no tables or headings.
- Explain in the owner's words; when it is about the app, say where it is on screen.
- Base answers on facts: the context you are given, the code in the current
  directory (a checkout of the project's stage branch: what is on stage now, or
  will be once open PRs merge), `git log`, `gh pr view/diff <url>`, and the stage
  site itself (curl). Look things up rather than guess; say so when you aren't sure.
- You are read-only. Never edit files, commit, push, open or merge PRs, or change
  anything on stage, in GitHub or in the cluster.

You can't change anything yourself. When the conversation shows something should
change (a bug, a missing case, the owner wants it different), propose an action:
the owner approves or rejects it with a button, and only then it happens.
- Not every question needs a change: propose only with a real reason, or when the
  owner asks for one. One proposal per distinct change. Don't repeat proposals the
  owner already approved or rejected.
- The proposal's description is the whole brief for a developer agent who won't
  see this chat: what is wrong now, what should happen instead, how to check it.
- Say in your reply that you proposed it, in one line.

Every turn ends with the structured result: `reply` (your message) and
`proposals` (usually empty).
"""


def chat_turn(messages: list, context: str | None, *, fresh: bool = False, history: list = ()) -> str:
    """One agent turn: the owner's new messages (and events), with the subject's context when it is new.

    *messages* and *history* are ChatMessage rows. *history* is the earlier conversation, for a
    fresh session that replaces one which can't be resumed.
    """
    parts = []
    if context is not None:
        heading = "Context" if fresh else "Updated context (it changed since your last answer)"
        parts += [f"# {heading}", "", context, ""]
    if history:
        parts += ["# The conversation so far", ""]
        parts += [_chat_line(m) for m in history]
        parts.append("")
    parts += ["# New in the chat", ""]
    parts += [_chat_line(m) for m in messages]
    return "\n".join(parts)


def _chat_line(message) -> str:
    if message.role == "event":
        return f"(Event: {message.text})"
    if message.role == "error":
        return f"(Your previous answer failed: {message.text[:300]})"
    if message.role == "assistant":
        proposed = [f"\n  (proposed {p['action']} «{p['title']}»: {p.get('state')})" for p in message.proposals or []]
        return f"You: {message.text}" + "".join(proposed)
    text = message.text
    if message.quote:
        text = f"[about: «{message.quote}»]\n{text}"
    return f"Owner: {text}"
