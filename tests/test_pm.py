"""Tests for autodev.agents.pm — PMAgent (Issue #13)."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from autodev.agents.pm import Improvement, PMAgent
from autodev.core.events import EventBus
from autodev.core.models import Priority, Task, TaskSource, TaskStatus
from autodev.core.queue import TaskQueue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    title: str = "Implement feature",
    description: str = "1. Setup\n2. Implement\n3. Test",
    priority: str = Priority.NORMAL,
    status: str = TaskStatus.QUEUED,
    depends_on: list | None = None,
) -> Task:
    return Task(
        id=uuid.uuid4(),
        title=title,
        description=description,
        source=TaskSource.MANUAL,
        priority=priority,
        status=status,
        depends_on=depends_on or [],
    )


def _make_agent(
    github: MagicMock | None = None,
    queue: MagicMock | None = None,
    event_bus: EventBus | None = None,
    config: dict | None = None,
) -> PMAgent:
    github = github or AsyncMock()
    queue = queue or AsyncMock(spec=TaskQueue)
    event_bus = event_bus or AsyncMock(spec=EventBus)
    if config is None:
        config = {"repo": "owner/repo"}
    return PMAgent(github=github, queue=queue, event_bus=event_bus, config=config)


# ---------------------------------------------------------------------------
# Improvement dataclass
# ---------------------------------------------------------------------------


def test_improvement_defaults() -> None:
    imp = Improvement(
        file_path="autodev/core/queue.py",
        line_number=42,
        category="todo",
        description="TODO: implement retry logic",
    )
    assert imp.priority == Priority.NORMAL
    assert imp.estimated_effort == 3
    assert imp.metadata == {}


def test_improvement_custom_fields() -> None:
    imp = Improvement(
        file_path="autodev/agents/developer.py",
        line_number=10,
        category="complexity",
        description="High complexity function",
        priority=Priority.HIGH,
        estimated_effort=8,
        metadata={"function": "run"},
    )
    assert imp.priority == Priority.HIGH
    assert imp.estimated_effort == 8
    assert imp.metadata["function"] == "run"


# ---------------------------------------------------------------------------
# analyze_codebase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_codebase_finds_todos(tmp_path: Path) -> None:
    """analyze_codebase should detect TODO comments."""
    (tmp_path / "module.py").write_text("# TODO: fix this\ndef foo(): pass\n")
    agent = _make_agent()
    improvements = await agent.analyze_codebase(str(tmp_path))
    assert any(i.category == "todo" for i in improvements)


@pytest.mark.asyncio
async def test_analyze_codebase_finds_missing_tests(tmp_path: Path) -> None:
    """analyze_codebase should flag source files without test counterparts."""
    src = tmp_path / "mymodule.py"
    src.write_text("def foo():\n    pass\n" * 20)
    agent = _make_agent()
    improvements = await agent.analyze_codebase(str(tmp_path))
    assert any(i.category == "missing_tests" for i in improvements)


@pytest.mark.asyncio
async def test_analyze_codebase_skips_test_files_from_missing_tests(tmp_path: Path) -> None:
    """Test files themselves should not be flagged as missing tests."""
    (tmp_path / "test_mymodule.py").write_text("def test_foo(): pass\n" * 15)
    agent = _make_agent()
    improvements = await agent.analyze_codebase(str(tmp_path))
    assert not any(i.category == "missing_tests" and "test_" in i.file_path for i in improvements)


@pytest.mark.asyncio
async def test_analyze_codebase_high_complexity(tmp_path: Path) -> None:
    """analyze_codebase should flag functions with many branches."""
    code_lines = ["def complex_func(x):\n"]
    for i in range(12):
        code_lines.append(f"    if x == {i}: return {i}\n")
    (tmp_path / "complex.py").write_text("".join(code_lines))
    agent = _make_agent()
    improvements = await agent.analyze_codebase(str(tmp_path))
    assert any(i.category == "complexity" for i in improvements)


@pytest.mark.asyncio
async def test_analyze_codebase_empty_dir(tmp_path: Path) -> None:
    """An empty directory should yield no improvements."""
    agent = _make_agent()
    improvements = await agent.analyze_codebase(str(tmp_path))
    assert improvements == []


# ---------------------------------------------------------------------------
# prioritize_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prioritize_tasks_ordering() -> None:
    """Critical tasks should come before Normal which come before Low."""
    t_low = _make_task(priority=Priority.LOW)
    t_high = _make_task(priority=Priority.HIGH)
    t_critical = _make_task(priority=Priority.CRITICAL)
    t_normal = _make_task(priority=Priority.NORMAL)

    agent = _make_agent()
    result = await agent.prioritize_tasks([t_low, t_normal, t_critical, t_high])

    priorities = [t.priority for t in result]
    assert priorities[0] == Priority.CRITICAL
    assert priorities[-1] == Priority.LOW


@pytest.mark.asyncio
async def test_prioritize_tasks_empty() -> None:
    agent = _make_agent()
    result = await agent.prioritize_tasks([])
    assert result == []


@pytest.mark.asyncio
async def test_prioritize_tasks_single() -> None:
    task = _make_task(priority=Priority.HIGH)
    agent = _make_agent()
    result = await agent.prioritize_tasks([task])
    assert result == [task]


# ---------------------------------------------------------------------------
# create_task_from_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_from_issue_basic() -> None:
    issue = {
        "number": 42,
        "title": "Fix login bug",
        "body": "Login is broken",
        "labels": [],
        "html_url": "https://github.com/owner/repo/issues/42",
        "user": {"login": "alice"},
    }
    mock_task = _make_task(title="Fix login bug")
    mock_queue = AsyncMock(spec=TaskQueue)
    mock_queue.enqueue.return_value = mock_task
    mock_bus = AsyncMock(spec=EventBus)

    agent = _make_agent(queue=mock_queue, event_bus=mock_bus)
    await agent.create_task_from_issue(issue)

    mock_queue.enqueue.assert_called_once()
    call_data = mock_queue.enqueue.call_args[0][0]
    assert call_data["title"] == "Fix login bug"
    assert call_data["issue_number"] == 42
    assert call_data["source"] == TaskSource.GITHUB_ISSUE
    mock_bus.emit.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_from_issue_critical_label() -> None:
    issue = {
        "number": 1,
        "title": "CRITICAL: DB down",
        "body": "",
        "labels": [{"name": "critical"}],
        "html_url": "",
        "user": {"login": "bob"},
    }
    mock_task = _make_task(priority=Priority.CRITICAL)
    mock_queue = AsyncMock(spec=TaskQueue)
    mock_queue.enqueue.return_value = mock_task
    agent = _make_agent(queue=mock_queue)
    await agent.create_task_from_issue(issue)

    call_data = mock_queue.enqueue.call_args[0][0]
    assert call_data["priority"] == Priority.CRITICAL


@pytest.mark.asyncio
async def test_create_task_from_issue_low_label() -> None:
    issue = {
        "number": 2,
        "title": "Nice-to-have: dark mode",
        "body": "",
        "labels": [{"name": "low"}],
        "html_url": "",
        "user": {},
    }
    mock_task = _make_task(priority=Priority.LOW)
    mock_queue = AsyncMock(spec=TaskQueue)
    mock_queue.enqueue.return_value = mock_task
    agent = _make_agent(queue=mock_queue)
    await agent.create_task_from_issue(issue)

    call_data = mock_queue.enqueue.call_args[0][0]
    assert call_data["priority"] == Priority.LOW


# ---------------------------------------------------------------------------
# decompose_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decompose_task_numbered_sections() -> None:
    """Tasks with numbered sections should be split into subtasks."""
    task = _make_task(description="1. Setup environment\n2. Write code\n3. Write tests\n4. Deploy")
    enqueued: list[dict] = []
    mock_queue = AsyncMock(spec=TaskQueue)

    async def _enqueue(data: dict) -> Task:
        t = Task(
            id=uuid.uuid4(),
            title=data["title"],
            status=TaskStatus.QUEUED,
            source=TaskSource.AGENT_CREATED,
            priority=data.get("priority", Priority.NORMAL),
            depends_on=data.get("depends_on", []),
        )
        enqueued.append(data)
        return t

    mock_queue.enqueue.side_effect = _enqueue
    agent = _make_agent(queue=mock_queue)
    subtasks = await agent.decompose_task(task)

    assert len(subtasks) >= 2


@pytest.mark.asyncio
async def test_decompose_task_no_sections() -> None:
    """Short tasks without numbered sections return the original task."""
    task = _make_task(description="Fix the typo in README.md")
    agent = _make_agent()
    result = await agent.decompose_task(task)
    assert result == [task]


@pytest.mark.asyncio
async def test_decompose_task_respects_max_subtasks() -> None:
    """Number of subtasks should not exceed max_subtasks config."""
    task = _make_task(description="\n".join(f"{i}. Step {i}" for i in range(1, 10)))
    enqueued: list[Task] = []
    mock_queue = AsyncMock(spec=TaskQueue)

    async def _enqueue(data: dict) -> Task:
        t = Task(
            id=uuid.uuid4(),
            title=data["title"],
            status=TaskStatus.QUEUED,
            source=TaskSource.AGENT_CREATED,
            priority=data.get("priority", Priority.NORMAL),
            depends_on=data.get("depends_on", []),
        )
        enqueued.append(t)
        return t

    mock_queue.enqueue.side_effect = _enqueue
    agent = _make_agent(config={"repo": "owner/repo", "max_subtasks": 3}, queue=mock_queue)
    subtasks = await agent.decompose_task(task)
    assert len(subtasks) <= 3


# ---------------------------------------------------------------------------
# assign_developer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_developer_already_queued() -> None:
    """If task is already QUEUED, assign_developer should not re-enqueue."""
    task = _make_task(status=TaskStatus.QUEUED)
    mock_queue = AsyncMock(spec=TaskQueue)
    agent = _make_agent(queue=mock_queue)
    await agent.assign_developer(task)
    mock_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_assign_developer_non_queued() -> None:
    """Non-queued tasks should be re-enqueued."""
    task = _make_task(status=TaskStatus.ASSIGNED)
    task.id = uuid.uuid4()
    mock_queue = AsyncMock(spec=TaskQueue)
    mock_queue.enqueue.return_value = task
    agent = _make_agent(queue=mock_queue)
    await agent.assign_developer(task)
    mock_queue.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_repo() -> None:
    """With no repo configured, run() should return without calling GitHub."""
    mock_github = AsyncMock()
    agent = _make_agent(github=mock_github, config={})
    await agent.run()
    mock_github.list_issues.assert_not_called()


@pytest.mark.asyncio
async def test_run_full_cycle() -> None:
    """Full cycle: issues → create tasks → prioritise → assign."""
    issues = [
        {"number": 1, "title": "Bug A", "body": "Fix it", "labels": [], "html_url": "", "user": {}},
        {
            "number": 2,
            "title": "Feature B",
            "body": "Add it",
            "labels": [{"name": "high"}],
            "html_url": "",
            "user": {},
        },
    ]
    mock_github = AsyncMock()
    mock_github.list_issues.return_value = issues

    created_tasks: list[Task] = []
    mock_queue = AsyncMock(spec=TaskQueue)

    async def _enqueue(data: dict) -> Task:
        t = Task(
            id=uuid.uuid4(),
            title=data["title"],
            status=TaskStatus.QUEUED,
            source=data.get("source", TaskSource.MANUAL),
            priority=data.get("priority", Priority.NORMAL),
            description=data.get("description", ""),
            depends_on=data.get("depends_on", []),
        )
        created_tasks.append(t)
        return t

    mock_queue.enqueue.side_effect = _enqueue
    mock_bus = AsyncMock(spec=EventBus)

    agent = _make_agent(github=mock_github, queue=mock_queue, event_bus=mock_bus, config={"repo": "owner/repo"})
    await agent.run()

    mock_github.list_issues.assert_called_once_with(repo="owner/repo", state="open")
    assert len(created_tasks) >= 2
