"""Project Manager (PM) agent — planning, prioritisation, and coordination.

Implements Issue #13: PM Agent with automatic codebase analysis,
task decomposition, prioritisation, and developer assignment.
"""

from __future__ import annotations

import ast
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autodev.core.events import EventBus, EventTypes
from autodev.core.models import Priority, Task, TaskSource, TaskStatus
from autodev.core.queue import TaskQueue
from autodev.integrations.github import GitHubClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Improvement:
    """A suggested code improvement found during codebase analysis.

    Attributes:
        file_path: Path to the file containing the improvement opportunity.
        line_number: Approximate line number (0 if not applicable).
        category: Category of improvement (e.g. "todo", "complexity", "missing_tests").
        description: Human-readable description of the suggested improvement.
        priority: Suggested priority level for addressing this improvement.
        estimated_effort: Rough effort estimate in story points (1-13).
    """

    file_path: str
    line_number: int
    category: str
    description: str
    priority: str = Priority.NORMAL
    estimated_effort: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskDecomposition:
    """Result of decomposing a large task into subtasks.

    Attributes:
        parent_task: The original task that was decomposed.
        subtasks: List of smaller Task objects derived from the parent.
        rationale: Explanation of how/why the task was split.
    """

    parent_task: Task
    subtasks: list[Task]
    rationale: str


# ---------------------------------------------------------------------------
# PMAgent
# ---------------------------------------------------------------------------


class PMAgent:
    """Autonomous Project Manager agent.

    Orchestrates backlog grooming, task creation from GitHub issues,
    prioritisation, decomposition, and developer assignment.

    Args:
        github: Authenticated GitHub API client.
        queue: Task queue for enqueuing work items.
        event_bus: Event bus for publishing domain events.
        config: Configuration dictionary (e.g. ``repo``, ``max_subtasks``).
    """

    role = "pm"

    def __init__(
        self,
        github: GitHubClient,
        queue: TaskQueue,
        event_bus: EventBus,
        config: dict[str, Any],
    ) -> None:
        self.github = github
        self.queue = queue
        self.event_bus = event_bus
        self.config = config
        self._repo = config.get("repo")

    # ------------------------------------------------------------------
    # Codebase analysis
    # ------------------------------------------------------------------

    async def analyze_codebase(self, repo_path: str) -> list[Improvement]:
        """Scan the local repository and return a list of potential improvements.

        Looks for:
        - TODO / FIXME comments
        - Functions with high cyclomatic complexity (> 10 branches)
        - Python files without any test counterpart
        - Empty __init__ blocks that may need exports

        Args:
            repo_path: Absolute or relative path to the repository root.

        Returns:
            List of :class:`Improvement` objects sorted by priority.
        """
        improvements: list[Improvement] = []
        root = Path(repo_path)

        python_files = list(root.rglob("*.py"))
        source_files = [
            f
            for f in python_files
            if not any(part.startswith(".") or part in {"node_modules", "__pycache__"} for part in f.parts)
        ]

        test_modules: set[str] = set()
        for f in source_files:
            if f.name.startswith("test_"):
                # e.g. test_developer → developer
                test_modules.add(f.stem[5:])

        for file_path in source_files:
            rel = str(file_path.relative_to(root))
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # --- TODO / FIXME detection ---
            for lineno, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                for marker in ("TODO", "FIXME", "HACK", "XXX"):
                    if marker in stripped:
                        improvements.append(
                            Improvement(
                                file_path=rel,
                                line_number=lineno,
                                category="todo",
                                description=f"{marker} found: {stripped[:120]}",
                                priority=Priority.LOW,
                                estimated_effort=2,
                            )
                        )
                        break

            # --- Complexity detection via AST ---
            try:
                tree = ast.parse(source)
            except SyntaxError:
                improvements.append(
                    Improvement(
                        file_path=rel,
                        line_number=0,
                        category="syntax_error",
                        description=f"Syntax error in {rel} — file cannot be parsed",
                        priority=Priority.HIGH,
                        estimated_effort=1,
                    )
                )
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    branches = sum(
                        1
                        for n in ast.walk(node)
                        if isinstance(
                            n,
                            (
                                ast.If,
                                ast.For,
                                ast.While,
                                ast.Try,
                                ast.ExceptHandler,
                                ast.With,
                                ast.Assert,
                            ),
                        )
                    )
                    if branches > 10:
                        improvements.append(
                            Improvement(
                                file_path=rel,
                                line_number=node.lineno,
                                category="complexity",
                                description=(
                                    f"Function '{node.name}' has high cyclomatic complexity "
                                    f"({branches} branches) — consider refactoring"
                                ),
                                priority=Priority.NORMAL,
                                estimated_effort=5,
                            )
                        )

            # --- Missing tests detection ---
            module_name = file_path.stem
            if (
                not file_path.name.startswith("test_")
                and module_name not in ("__init__", "conftest")
                and module_name not in test_modules
                and file_path.stat().st_size > 200
            ):
                improvements.append(
                    Improvement(
                        file_path=rel,
                        line_number=0,
                        category="missing_tests",
                        description=f"No test file found for module '{module_name}'",
                        priority=Priority.NORMAL,
                        estimated_effort=5,
                    )
                )

        logger.info("[pm] Codebase analysis found %d improvements", len(improvements))
        return improvements

    # ------------------------------------------------------------------
    # Task prioritisation
    # ------------------------------------------------------------------

    async def prioritize_tasks(self, tasks: list[Task]) -> list[Task]:
        """Sort tasks by priority level and dependency order.

        Critical > High > Normal > Low.  Within the same priority level,
        tasks with no unsatisfied dependencies come first.

        Args:
            tasks: List of Task objects to prioritise.

        Returns:
            New list sorted from highest to lowest priority.
        """
        _order = {
            Priority.CRITICAL: 0,
            Priority.HIGH: 1,
            Priority.NORMAL: 2,
            Priority.LOW: 3,
        }

        task_ids = {t.id for t in tasks}

        def _sort_key(task: Task) -> tuple[int, int, datetime]:
            pri = _order.get(task.priority, 99)
            # Tasks whose dependencies are all outside the current batch
            # (already done) go first; tasks with pending deps go last.
            unresolved_deps = len([d for d in (task.depends_on or []) if d in task_ids])
            return (pri, unresolved_deps, task.created_at or datetime.min.replace(tzinfo=UTC))

        sorted_tasks = sorted(tasks, key=_sort_key)
        logger.info("[pm] Prioritised %d tasks", len(sorted_tasks))
        return sorted_tasks

    # ------------------------------------------------------------------
    # Task creation from GitHub issues
    # ------------------------------------------------------------------

    async def create_task_from_issue(self, issue: dict) -> Task:
        """Convert a GitHub issue dict into a :class:`Task` and enqueue it.

        Args:
            issue: GitHub API issue object (as returned by the REST API).

        Returns:
            Newly created and persisted :class:`Task`.
        """
        labels: list[str] = [lbl.get("name", "") for lbl in issue.get("labels", [])]

        # Derive priority from labels
        if any(lbl in labels for lbl in ("critical", "P0", "blocker")):
            priority = Priority.CRITICAL
        elif any(lbl in labels for lbl in ("high", "P1", "important")):
            priority = Priority.HIGH
        elif any(lbl in labels for lbl in ("low", "P3", "nice-to-have")):
            priority = Priority.LOW
        else:
            priority = Priority.NORMAL

        repo = self._repo or issue.get("repository", {}).get("full_name")

        task_data: dict[str, Any] = {
            "title": issue.get("title", "Untitled issue"),
            "description": issue.get("body") or "",
            "source": TaskSource.GITHUB_ISSUE,
            "priority": priority,
            "status": TaskStatus.QUEUED,
            "repo": repo,
            "issue_number": issue.get("number"),
            "metadata": {
                "github_url": issue.get("html_url", ""),
                "labels": labels,
                "author": issue.get("user", {}).get("login", ""),
            },
            "created_by": "pm-agent",
        }

        task = await self.queue.enqueue(task_data)
        await self.event_bus.emit(
            EventTypes.TASK_CREATED,
            payload={"task_id": str(task.id), "issue_number": issue.get("number")},
            source="pm-agent",
        )
        logger.info("[pm] Created task %s from issue #%s", task.id, issue.get("number"))
        return task

    # ------------------------------------------------------------------
    # Task decomposition
    # ------------------------------------------------------------------

    async def decompose_task(self, task: Task) -> list[Task]:
        """Break a large task into smaller subtasks.

        Heuristic decomposition based on task description length and
        configuration.  Each subtask depends on its predecessor so they
        are processed in order.

        Args:
            task: The parent task to decompose.

        Returns:
            List of subtask :class:`Task` objects (already enqueued).
            Returns a list with just the original task if decomposition
            is not needed.
        """
        max_subtasks: int = self.config.get("max_subtasks", 4)
        description = task.description or ""

        # Simple heuristic: split by numbered sections or double newlines
        sections: list[str] = []
        lines = description.strip().splitlines()
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and stripped[0].isdigit() and stripped[1:3] in (". ", ") "):
                if current:
                    sections.append("\n".join(current).strip())
                current = [stripped[3:].strip() if len(stripped) > 3 else stripped]
            elif stripped == "" and current:
                sections.append("\n".join(current).strip())
                current = []
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current).strip())

        sections = [s for s in sections if s][:max_subtasks]

        if len(sections) <= 1:
            # Nothing to decompose
            return [task]

        subtasks: list[Task] = []
        prev_id: uuid.UUID | None = None

        for i, section in enumerate(sections, start=1):
            subtask_data: dict[str, Any] = {
                "title": f"{task.title} — Part {i}",
                "description": section,
                "source": TaskSource.AGENT_CREATED,
                "priority": task.priority,
                "status": TaskStatus.QUEUED,
                "repo": task.repo,
                "depends_on": [prev_id] if prev_id is not None else [],
                "metadata": {"parent_task_id": str(task.id), "part": i},
                "created_by": "pm-agent",
            }
            subtask = await self.queue.enqueue(subtask_data)
            subtasks.append(subtask)
            prev_id = subtask.id

        logger.info("[pm] Decomposed task %s into %d subtasks", task.id, len(subtasks))
        return subtasks

    # ------------------------------------------------------------------
    # Developer assignment
    # ------------------------------------------------------------------

    async def assign_developer(self, task: Task) -> None:
        """Place a task into the developer queue (enqueue if needed).

        If the task is already in the queue, this is a no-op.  Otherwise
        it will be re-enqueued.

        Args:
            task: Task to assign to a developer agent.
        """
        if task.status == TaskStatus.QUEUED:
            logger.info("[pm] Task %s already queued, skipping re-enqueue", task.id)
            return

        await self.queue.enqueue(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "source": task.source,
                "priority": task.priority,
                "status": TaskStatus.QUEUED,
                "repo": task.repo,
                "issue_number": task.issue_number,
                "depends_on": task.depends_on or [],
                "metadata": task.metadata_ or {},
                "created_by": "pm-agent",
            }
        )
        logger.info("[pm] Task %s assigned to developer queue", task.id)

    # ------------------------------------------------------------------
    # Full orchestration cycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Execute a full PM cycle: fetch issues → create tasks → prioritise → assign.

        1. Fetch open GitHub issues for the configured repo.
        2. Convert each issue to a Task and enqueue it.
        3. Prioritise all queued tasks.
        4. Decompose large tasks where appropriate.
        5. Assign tasks to the developer queue.
        """
        repo = self._repo
        if not repo:
            logger.warning("[pm] No repo configured — skipping GitHub issue fetch")
            tasks: list[Task] = []
        else:
            logger.info("[pm] Fetching open issues from %s", repo)
            issues = await self.github.list_issues(repo=repo, state="open")
            tasks = []
            for issue in issues:
                task = await self.create_task_from_issue(issue)
                tasks.append(task)

        if not tasks:
            logger.info("[pm] No new tasks from issues")
            return

        prioritised = await self.prioritize_tasks(tasks)

        for task in prioritised:
            subtasks = await self.decompose_task(task)
            for subtask in subtasks:
                if subtask.id != task.id:
                    await self.assign_developer(subtask)
                else:
                    await self.assign_developer(task)

        logger.info("[pm] PM cycle complete — processed %d tasks", len(prioritised))
