"""Developer agent — writes and refactors code.

Receives coding tasks from the queue, interacts with the GitHub integration
to create branches and pull requests, and uses the AgentRunner for
LLM-powered code generation.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from autodev.core.events import EventBus, EventTypes
from autodev.core.models import Task
from autodev.core.queue import TaskQueue
from autodev.core.runner import AgentResult, AgentRunner
from autodev.core.state import StateManager
from autodev.integrations.github import GitHubClient

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert *text* to a URL-safe slug for branch names.

    Lowercases, replaces non-alphanumeric runs with hyphens, and strips
    leading/trailing hyphens.  Truncated to 50 characters to stay within
    Git branch name limits.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:50]


class DeveloperAgent:
    """Autonomous developer agent.

    Processes coding tasks: feature implementation, bug fixes, refactoring.
    For each task it clones the target repository, creates a feature branch,
    invokes the configured LLM runner to generate code, commits the result,
    pushes to the remote, and opens a pull request.

    Args:
        runner: LLM-session runner (e.g. :class:`~autodev.core.runner.ClaudeCodeRunner`).
        github: GitHub REST API client.
        queue: Shared task queue.
        state: In-process key-value state store.
        event_bus: Domain event bus for publishing lifecycle events.
        config: Agent-level configuration dict.  Recognised keys:

            ``max_iterations`` (int, default ``3``)
                Maximum number of retry attempts per task.

            ``agent_id`` (str, default ``"developer-agent"``)
                Identifier used in state keys and log messages.

            ``base_branch`` (str, default ``"main"``)
                Base branch used when opening pull requests.

            ``sleep_interval`` (float, default ``2.0``)
                Seconds to sleep between queue polls when no task is found.
    """

    role = "developer"

    def __init__(
        self,
        runner: AgentRunner,
        github: GitHubClient,
        queue: TaskQueue,
        state: StateManager,
        event_bus: EventBus,
        config: dict[str, Any],
    ) -> None:
        self.runner = runner
        self.github = github
        self.queue = queue
        self.state = state
        self.event_bus = event_bus
        self.config = config

        self._max_iterations: int = config.get("max_iterations", 3)
        self._agent_id: str = config.get("agent_id", "developer-agent")
        self._base_branch: str = config.get("base_branch", "main")
        self._sleep_interval: float = float(config.get("sleep_interval", 2.0))
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_task(self, task: Task) -> AgentResult:
        """Execute a single coding task end-to-end.

        Workflow:

        1. Clone the repository into a temporary directory.
        2. Create a feature branch named ``issue-{N}-{slug}``.
        3. Build an LLM prompt from the task description + optional ``CLAUDE.md``.
        4. Run the LLM runner; retry up to *max_iterations* on failure.
        5. On success: commit changes, push the branch, open a PR.
        6. Update task status (complete / failed) and emit the relevant domain event.

        Args:
            task: The :class:`~autodev.core.models.Task` to process.

        Returns:
            The final :class:`~autodev.core.runner.AgentResult` from the runner.
        """
        repo_url: str = task.repo or ""
        issue_number: int = task.issue_number or 0
        slug = _slugify(task.title or "task")
        branch_name = f"issue-{issue_number}-{slug}" if issue_number else f"task-{slug}"

        work_dir = tempfile.mkdtemp(prefix="autodev-")
        last_result: AgentResult | None = None

        try:
            # 1. Clone repo
            repo_path = await self._clone_repo(repo_url, work_dir)

            # 2. Feature branch
            await self._create_branch(repo_path, branch_name)

            # 3. Build prompt (CLAUDE.md context file if present)
            context_file = repo_path / "CLAUDE.md"
            prompt = self._build_prompt(task, context_file if context_file.exists() else None)

            # 4. Run with retries
            context: dict[str, Any] = {
                "repo_url": repo_url,
                "branch": branch_name,
                "work_dir": str(repo_path),
                "task_id": str(task.id),
                "issue_number": issue_number,
            }

            for attempt in range(1, self._max_iterations + 1):
                logger.info(
                    "[%s] Running task %s attempt %d/%d",
                    self._agent_id,
                    task.id,
                    attempt,
                    self._max_iterations,
                )
                result = await self.runner.run(prompt, context)
                last_result = result

                if result.status == "success":
                    break

                logger.warning(
                    "[%s] Attempt %d failed for task %s: %s",
                    self._agent_id,
                    attempt,
                    task.id,
                    result.output,
                )
                if attempt == self._max_iterations:
                    logger.error(
                        "[%s] All %d attempts exhausted for task %s",
                        self._agent_id,
                        self._max_iterations,
                        task.id,
                    )

            # 5. Handle outcome
            if last_result and last_result.status == "success":
                # Commit and push
                if issue_number:
                    commit_msg = f"feat: {task.title} (#{issue_number})"
                else:
                    commit_msg = f"feat: {task.title}"
                await self._commit_and_push(repo_path, commit_msg, branch_name)

                # Open PR via GitHub API
                pr_title = task.title or f"Fix issue #{issue_number}"
                pr_body = (f"Closes #{issue_number}\n\n{task.description or ''}").strip()
                repo_slug = task.metadata_.get("github_repo") if task.metadata_ else None  # type: ignore[union-attr]
                pr = await self.github.create_pr(
                    title=pr_title,
                    head=branch_name,
                    base=self._base_branch,
                    body=pr_body,
                    repo=repo_slug,
                )
                pr_number: int = pr.get("number", 0)

                # 7. Mark task complete
                await self.queue.complete(task.id, pr_number=pr_number)

                # 8. Emit pr.created
                await self.event_bus.emit(
                    EventTypes.PR_CREATED,
                    payload={
                        "task_id": str(task.id),
                        "pr_number": pr_number,
                        "branch": branch_name,
                        "repo": repo_slug or repo_url,
                    },
                    source=self._agent_id,
                )
                logger.info("[%s] PR #%d created for task %s", self._agent_id, pr_number, task.id)

            else:
                # Mark task failed
                reason = last_result.output if last_result else "unknown error"
                await self.queue.fail(task.id, reason=reason)

                # Emit task.failed
                await self.event_bus.emit(
                    EventTypes.TASK_FAILED,
                    payload={
                        "task_id": str(task.id),
                        "reason": reason,
                    },
                    source=self._agent_id,
                )

        except Exception as exc:
            logger.exception("[%s] Unexpected error processing task %s", self._agent_id, task.id)
            await self.queue.fail(task.id, reason=str(exc))
            await self.event_bus.emit(
                EventTypes.TASK_FAILED,
                payload={"task_id": str(task.id), "reason": str(exc)},
                source=self._agent_id,
            )
            if last_result is None:
                last_result = AgentResult(status="failure", output=str(exc))
        finally:
            await self._cleanup(work_dir)

        return last_result or AgentResult(status="failure", output="no result")

    async def run_loop(self) -> None:
        """Run the agent's main processing loop until stopped.

        Continuously polls the task queue.  When a task is available it is
        claimed, the agent state is updated, and :meth:`process_task` is called.
        When the queue is empty the loop sleeps for *sleep_interval* seconds.
        """
        logger.info("[%s] Starting run loop", self._agent_id)
        self._running = True
        await self.state.set(f"agents.{self._agent_id}.status", "idle")

        while self._running:
            task = await self.queue.dequeue()

            if task is None:
                await asyncio.sleep(self._sleep_interval)
                continue

            logger.info("[%s] Picked up task %s", self._agent_id, task.id)
            await self.state.set(f"agents.{self._agent_id}.status", "working")
            await self.state.set(f"agents.{self._agent_id}.current_task", str(task.id))

            try:
                await self.process_task(task)
            except Exception:
                logger.exception("[%s] Unhandled error in process_task for %s", self._agent_id, task.id)
            finally:
                await self.state.set(f"agents.{self._agent_id}.status", "idle")
                await self.state.delete(f"agents.{self._agent_id}.current_task")

    async def stop(self) -> None:
        """Signal the run loop to stop after the current task finishes."""
        logger.info("[%s] Stopping", self._agent_id)
        self._running = False

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    async def _clone_repo(self, repo_url: str, work_dir: str) -> Path:
        """Clone *repo_url* into *work_dir* and return the resulting path.

        Args:
            repo_url: Git clone URL (HTTPS or SSH).
            work_dir: Parent directory where the clone will be placed.

        Returns:
            Path to the cloned repository root.

        Raises:
            RuntimeError: If the ``git clone`` command fails.
        """
        if not repo_url:
            # No real URL — work in the work_dir itself (useful in tests)
            return Path(work_dir)

        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            repo_url,
            work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git clone failed (exit {proc.returncode}): {err}")
        logger.debug("[%s] Cloned %s → %s", self._agent_id, repo_url, work_dir)
        return Path(work_dir)

    async def _create_branch(self, work_dir: Path, branch_name: str) -> None:
        """Create and check out a new feature branch in *work_dir*.

        Args:
            work_dir: Path to the cloned repository.
            branch_name: Name of the branch to create.

        Raises:
            RuntimeError: If the ``git checkout -b`` command fails.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            "checkout",
            "-b",
            branch_name,
            cwd=str(work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git checkout -b failed (exit {proc.returncode}): {err}")
        logger.debug("[%s] Created branch %r in %s", self._agent_id, branch_name, work_dir)

    def _build_prompt(self, task: Task, context_file: Path | None) -> str:
        """Construct the LLM prompt for *task*.

        If *context_file* (typically ``CLAUDE.md``) exists and is readable,
        its contents are prepended to the task description as additional
        context for the LLM.

        Args:
            task: The task whose description forms the core of the prompt.
            context_file: Optional path to a Markdown context file.

        Returns:
            A string prompt ready to be passed to the runner.
        """
        parts: list[str] = []

        # Project context
        if context_file is not None:
            try:
                ctx_text = context_file.read_text(encoding="utf-8").strip()
                if ctx_text:
                    parts.append("# Project Context\n\n" + ctx_text)
            except OSError as exc:
                logger.warning("Could not read context file %s: %s", context_file, exc)

        # Task description
        task_section = "# Task\n\n"
        if task.title:
            task_section += f"**{task.title}**\n\n"
        if task.description:
            task_section += task.description
        elif task.title:
            task_section += f"Implement: {task.title}"
        parts.append(task_section)

        # Issue reference
        if task.issue_number:
            parts.append(f"# Reference\n\nGitHub Issue: #{task.issue_number}")

        return "\n\n---\n\n".join(parts)

    async def _commit_and_push(
        self,
        work_dir: Path,
        message: str,
        branch: str,
    ) -> None:
        """Stage all changes, commit, and push the branch to the remote.

        Args:
            work_dir: Path to the cloned repository.
            message: Git commit message.
            branch: Branch name to push to ``origin``.

        Raises:
            RuntimeError: If any git command fails.
        """
        for cmd in [
            ["git", "add", "."],
            ["git", "commit", "--allow-empty", "-m", message],
            ["git", "push", "origin", branch],
        ]:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"'{' '.join(cmd)}' failed (exit {proc.returncode}): {stderr.decode(errors='replace').strip()}"
                )
        logger.debug("[%s] Committed and pushed branch %r", self._agent_id, branch)

    async def _cleanup(self, work_dir: str) -> None:
        """Remove the temporary working directory.

        Errors are logged but not re-raised so that cleanup never masks the
        original exception from :meth:`process_task`.

        Args:
            work_dir: Path to the temporary directory to remove.
        """
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.debug("[%s] Cleaned up %s", self._agent_id, work_dir)
        except Exception as exc:  # pragma: no cover
            logger.warning("[%s] Failed to clean up %s: %s", self._agent_id, work_dir, exc)

    # ------------------------------------------------------------------
    # Legacy BaseAgent compatibility
    # ------------------------------------------------------------------

    async def handle_event(self, event: Any) -> None:
        """React to domain events relevant to the developer role.

        Currently a no-op; extend to handle ``task.assigned`` or
        ``review.requested`` events as the system grows.
        """
        logger.debug("[%s] Event received: %s", self._agent_id, getattr(event, "type", event))
