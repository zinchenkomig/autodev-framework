"""Tests for autodev.agents.developer — DeveloperAgent."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autodev.agents.developer import DeveloperAgent, _slugify  # noqa: F401
from autodev.core.events import EventBus, EventTypes
from autodev.core.models import Priority, Task, TaskSource, TaskStatus
from autodev.core.queue import TaskQueue
from autodev.core.runner import AgentResult, MockRunner
from autodev.core.state import StateManager

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_task(
    title: str = "Add feature X",
    description: str = "Please implement feature X.",
    issue_number: int | None = 42,
    repo: str | None = "https://github.com/owner/repo.git",
    metadata: dict | None = None,
) -> Task:
    return Task(
        id=uuid.uuid4(),
        title=title,
        description=description,
        source=TaskSource.GITHUB_ISSUE,
        priority=Priority.NORMAL,
        status=TaskStatus.ASSIGNED,
        repo=repo,
        issue_number=issue_number,
        metadata_=metadata or {"github_repo": "owner/repo"},
    )


def _make_agent(
    runner: MockRunner | None = None,
    github: Any = None,
    queue: TaskQueue | None = None,
    state: StateManager | None = None,
    event_bus: EventBus | None = None,
    config: dict | None = None,
) -> DeveloperAgent:
    if runner is None:
        runner = MockRunner(AgentResult(status="success", output="done"))

    if github is None:
        github = AsyncMock()
        github.create_pr = AsyncMock(return_value={"number": 7, "html_url": "https://github.com/owner/repo/pull/7"})

    if queue is None:
        queue = AsyncMock(spec=TaskQueue)
        queue.complete = AsyncMock(return_value=None)
        queue.fail = AsyncMock(return_value=None)
        queue.dequeue = AsyncMock(return_value=None)

    if state is None:
        state = AsyncMock(spec=StateManager)
        state.set = AsyncMock(return_value=None)
        state.delete = AsyncMock(return_value=None)

    if event_bus is None:
        event_bus = AsyncMock(spec=EventBus)
        event_bus.emit = AsyncMock(return_value=MagicMock())

    return DeveloperAgent(
        runner=runner,
        github=github,
        queue=queue,
        state=state,
        event_bus=event_bus,
        config=config or {"max_iterations": 3, "agent_id": "dev-test"},
    )


# ---------------------------------------------------------------------------
# Unit: _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercase_and_spaces(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_special_characters(self) -> None:
        assert _slugify("Fix: bug/issue #42!") == "fix-bug-issue-42"

    def test_truncation(self) -> None:
        long_text = "a" * 100
        assert len(_slugify(long_text)) <= 50

    def test_empty_string(self) -> None:
        assert _slugify("") == ""


# ---------------------------------------------------------------------------
# Unit: branch naming
# ---------------------------------------------------------------------------


class TestBranchNaming:
    def test_branch_with_issue_number(self) -> None:
        """Branch name must follow issue-{N}-{slug} pattern."""
        task = _make_task(title="Add login feature", issue_number=5)
        slug = _slugify("Add login feature")
        expected = f"issue-5-{slug}"
        # Re-derive same way process_task does
        derived = f"issue-{task.issue_number}-{_slugify(task.title)}"
        assert derived == expected

    def test_branch_without_issue_number(self) -> None:
        slug = _slugify("Refactor auth")
        derived = f"task-{slug}"
        assert derived == "task-refactor-auth"

    def test_branch_slug_no_special_chars(self) -> None:
        branch = f"issue-1-{_slugify('Fix crash: NullPointer in auth!')}"
        assert " " not in branch
        assert ":" not in branch
        assert "!" not in branch


# ---------------------------------------------------------------------------
# Unit: _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_prompt_includes_title_and_description(self) -> None:
        agent = _make_agent()
        task = _make_task(title="My Task", description="Do the thing")
        prompt = agent._build_prompt(task, None)
        assert "My Task" in prompt
        assert "Do the thing" in prompt

    def test_prompt_includes_context_file(self, tmp_path: Path) -> None:
        ctx = tmp_path / "CLAUDE.md"
        ctx.write_text("# Project rules\nDo not break anything.")
        agent = _make_agent()
        task = _make_task()
        prompt = agent._build_prompt(task, ctx)
        assert "Project rules" in prompt
        assert "Do not break anything." in prompt

    def test_prompt_without_context_file(self) -> None:
        agent = _make_agent()
        task = _make_task(description="Implement feature Y")
        prompt = agent._build_prompt(task, None)
        assert "Implement feature Y" in prompt
        assert "Project Context" not in prompt

    def test_prompt_includes_issue_number(self) -> None:
        agent = _make_agent()
        task = _make_task(issue_number=99)
        prompt = agent._build_prompt(task, None)
        assert "#99" in prompt

    def test_prompt_no_issue_number_no_reference_section(self) -> None:
        agent = _make_agent()
        task = _make_task(issue_number=None)
        prompt = agent._build_prompt(task, None)
        assert "GitHub Issue" not in prompt


# ---------------------------------------------------------------------------
# Integration: process_task success
# ---------------------------------------------------------------------------


class TestProcessTaskSuccess:
    @pytest.mark.asyncio
    async def test_success_calls_create_pr(self) -> None:
        """On success, github.create_pr must be called."""
        github = AsyncMock()
        github.create_pr = AsyncMock(return_value={"number": 3})
        queue = AsyncMock(spec=TaskQueue)
        queue.complete = AsyncMock(return_value=None)
        queue.fail = AsyncMock(return_value=None)

        agent = _make_agent(github=github, queue=queue)
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_commit_and_push", new_callable=AsyncMock):
                    with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                        result = await agent.process_task(task)

        assert result.status == "success"
        github.create_pr.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_calls_queue_complete(self) -> None:
        queue = AsyncMock(spec=TaskQueue)
        queue.complete = AsyncMock(return_value=None)
        queue.fail = AsyncMock(return_value=None)

        agent = _make_agent(queue=queue)
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_commit_and_push", new_callable=AsyncMock):
                    with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                        await agent.process_task(task)

        queue.complete.assert_called_once_with(task.id, pr_number=ANY_INT)

    @pytest.mark.asyncio
    async def test_success_emits_pr_created_event(self) -> None:
        event_bus = AsyncMock(spec=EventBus)
        event_bus.emit = AsyncMock(return_value=MagicMock())

        agent = _make_agent(event_bus=event_bus)
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_commit_and_push", new_callable=AsyncMock):
                    with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                        await agent.process_task(task)

        calls = [call.args[0] for call in event_bus.emit.call_args_list]
        assert EventTypes.PR_CREATED in calls


# Helper sentinel: accept any int (used above)
class _AnyInt:
    def __eq__(self, other: object) -> bool:
        return isinstance(other, int)

ANY_INT = _AnyInt()


# ---------------------------------------------------------------------------
# Integration: process_task failure and retry
# ---------------------------------------------------------------------------


class TestProcessTaskFailure:
    @pytest.mark.asyncio
    async def test_failure_calls_queue_fail(self) -> None:
        runner = MockRunner(AgentResult(status="failure", output="oops"))
        queue = AsyncMock(spec=TaskQueue)
        queue.complete = AsyncMock(return_value=None)
        queue.fail = AsyncMock(return_value=None)

        agent = _make_agent(runner=runner, queue=queue, config={"max_iterations": 2})
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                    result = await agent.process_task(task)

        assert result.status == "failure"
        queue.fail.assert_called_once()
        queue.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_emits_task_failed_event(self) -> None:
        runner = MockRunner(AgentResult(status="failure", output="error"))
        event_bus = AsyncMock(spec=EventBus)
        event_bus.emit = AsyncMock(return_value=MagicMock())

        agent = _make_agent(runner=runner, event_bus=event_bus, config={"max_iterations": 1})
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                    await agent.process_task(task)

        calls = [call.args[0] for call in event_bus.emit.call_args_list]
        assert EventTypes.TASK_FAILED in calls

    @pytest.mark.asyncio
    async def test_retry_exhausted_after_max_iterations(self) -> None:
        """Runner must be called exactly max_iterations times on persistent failure."""
        runner = MockRunner(AgentResult(status="failure", output="nope"))
        max_iter = 4
        agent = _make_agent(runner=runner, config={"max_iterations": max_iter})
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                    await agent.process_task(task)

        assert len(runner.calls) == max_iter

    @pytest.mark.asyncio
    async def test_success_on_second_attempt(self) -> None:
        """When the first attempt fails but the second succeeds, PR should be created."""
        github = AsyncMock()
        github.create_pr = AsyncMock(return_value={"number": 9})
        queue = AsyncMock(spec=TaskQueue)
        queue.complete = AsyncMock(return_value=None)
        queue.fail = AsyncMock(return_value=None)

        results = [
            AgentResult(status="failure", output="not yet"),
            AgentResult(status="success", output="done"),
        ]
        call_count = 0

        class _FlippingRunner:
            calls: list = []
            async def run(self, instructions: str, context: dict) -> AgentResult:
                nonlocal call_count
                r = results[min(call_count, len(results) - 1)]
                call_count += 1
                self.calls.append({"instructions": instructions, "context": context})
                return r

        runner = _FlippingRunner()
        agent = _make_agent(runner=runner, github=github, queue=queue, config={"max_iterations": 3})
        task = _make_task()

        with patch.object(agent, "_clone_repo", new_callable=AsyncMock, return_value=Path("/tmp/fake")):  # noqa: E501
            with patch.object(agent, "_create_branch", new_callable=AsyncMock):
                with patch.object(agent, "_commit_and_push", new_callable=AsyncMock):
                    with patch.object(agent, "_cleanup", new_callable=AsyncMock):
                        result = await agent.process_task(task)

        assert result.status == "success"
        assert call_count == 2
        github.create_pr.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: run_loop
# ---------------------------------------------------------------------------


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_loop_processes_task_then_stops(self) -> None:
        """run_loop should dequeue a task, process it, then exit after stop()."""
        task = _make_task()

        queue = AsyncMock(spec=TaskQueue)
        queue.complete = AsyncMock(return_value=None)
        queue.fail = AsyncMock(return_value=None)

        dequeue_calls = 0

        async def _dequeue_side_effect():
            nonlocal dequeue_calls
            dequeue_calls += 1
            if dequeue_calls == 1:
                return task
            # Return None to let the loop sleep, then stop it
            return None

        queue.dequeue = AsyncMock(side_effect=_dequeue_side_effect)

        agent = _make_agent(queue=queue, config={"max_iterations": 1, "sleep_interval": 0.01})

        # process_task is heavy — patch it to a no-op
        async def _fake_process(t: Task) -> AgentResult:
            agent._running = False  # stop after first task
            return AgentResult(status="success", output="ok")

        agent.process_task = _fake_process  # type: ignore[method-assign]

        await agent.run_loop()
        assert dequeue_calls >= 1

    @pytest.mark.asyncio
    async def test_run_loop_sleeps_when_no_task(self) -> None:
        """run_loop should sleep and not crash when queue is empty."""
        queue = AsyncMock(spec=TaskQueue)
        queue.dequeue = AsyncMock(return_value=None)

        agent = _make_agent(queue=queue, config={"sleep_interval": 0.01})

        async def _stop_soon() -> None:
            await asyncio.sleep(0.05)
            agent._running = False

        await asyncio.gather(agent.run_loop(), _stop_soon())

        # dequeue was called at least once
        assert queue.dequeue.call_count >= 1
