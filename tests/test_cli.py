"""Tests for autodev CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from autodev.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_response(data, status_code: int = 200) -> MagicMock:
    """Create a mock httpx Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# Test: autodev init
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_creates_file_from_template(self, tmp_path: Path) -> None:
        """init should create autodev.yaml in tmp dir."""
        dest = tmp_path / "autodev.yaml"
        result = runner.invoke(app, ["init", "--output", str(dest)])
        assert result.exit_code == 0
        assert dest.exists()

    def test_init_aborts_on_existing_file_no_overwrite(self, tmp_path: Path) -> None:
        """init should abort if file exists and user says no."""
        dest = tmp_path / "autodev.yaml"
        dest.write_text("existing")
        result = runner.invoke(app, ["init", "--output", str(dest)], input="n\n")
        assert result.exit_code == 0
        assert "Aborted" in result.output
        assert dest.read_text() == "existing"

    def test_init_overwrites_on_confirm(self, tmp_path: Path) -> None:
        """init should overwrite if user confirms."""
        dest = tmp_path / "autodev.yaml"
        dest.write_text("old")
        result = runner.invoke(app, ["init", "--output", str(dest)], input="y\n")
        assert result.exit_code == 0
        assert dest.read_text() != "old"


# ---------------------------------------------------------------------------
# Test: autodev status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_online(self) -> None:
        """status should show Online when server responds 200."""
        health_resp = make_response({"status": "ok"})

        with (
            patch("autodev.cli.main.httpx.get") as mock_get,
            patch("autodev.cli.main.api_get") as mock_api_get,
        ):
            mock_get.return_value = health_resp
            mock_api_get.side_effect = [
                [{"id": "dev1", "role": "developer", "status": "idle"}],
                [{"id": "t1", "title": "Fix bug", "status": "queued", "priority": "high"}],
            ]
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Online" in result.output

    def test_status_unreachable(self) -> None:
        """status should exit 1 when server is unreachable."""
        import httpx as _httpx

        with patch("autodev.cli.main.httpx.get") as mock_get:
            mock_get.side_effect = _httpx.ConnectError("refused")
            result = runner.invoke(app, ["status"])

        assert result.exit_code != 0
        assert "Unreachable" in result.output


# ---------------------------------------------------------------------------
# Test: autodev task add
# ---------------------------------------------------------------------------

class TestTaskAdd:
    def test_task_add_minimal(self) -> None:
        """task add should POST to /api/tasks and print task id."""
        with patch("autodev.cli.main.api_post") as mock_post:
            mock_post.return_value = {"id": "abc123", "status": "queued"}
            result = runner.invoke(app, ["task", "add", "Fix the login bug"])

        assert result.exit_code == 0
        assert "abc123" in result.output
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/api/tasks"
        payload = call_args[0][1]
        assert "Fix the login bug" in payload["description"]

    def test_task_add_with_options(self) -> None:
        """task add should pass repo and priority to API."""
        with patch("autodev.cli.main.api_post") as mock_post:
            mock_post.return_value = {"id": "def456", "status": "queued"}
            result = runner.invoke(
                app, ["task", "add", "Add feature", "--repo", "backend", "--priority", "high"]
            )

        assert result.exit_code == 0
        payload = mock_post.call_args[0][1]
        assert payload["repo"] == "backend"
        assert payload["priority"] == "high"


# ---------------------------------------------------------------------------
# Test: autodev task list
# ---------------------------------------------------------------------------

class TestTaskList:
    def test_task_list_all(self) -> None:
        """task list should print a table of tasks."""
        tasks = [
            {
                "id": "t1", "title": "Task A", "status": "queued",
                "priority": "normal", "repo": "backend",
            },
            {
                "id": "t2", "title": "Task B", "status": "done",
                "priority": "low", "repo": "frontend",
            },
        ]
        with patch("autodev.cli.main.api_get") as mock_get:
            mock_get.return_value = tasks
            result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        assert "Task A" in result.output
        assert "Task B" in result.output

    def test_task_list_with_filters(self) -> None:
        """task list should include filters in URL."""
        with patch("autodev.cli.main.api_get") as mock_get:
            mock_get.return_value = []
            result = runner.invoke(app, ["task", "list", "--status", "queued", "--repo", "backend"])

        assert result.exit_code == 0
        call_path = mock_get.call_args[0][0]
        assert "status=queued" in call_path
        assert "repo=backend" in call_path

    def test_task_list_empty(self) -> None:
        """task list should handle empty response gracefully."""
        with patch("autodev.cli.main.api_get") as mock_get:
            mock_get.return_value = []
            result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        assert "No tasks" in result.output


# ---------------------------------------------------------------------------
# Test: autodev agent trigger
# ---------------------------------------------------------------------------

class TestAgentTrigger:
    def test_agent_trigger(self) -> None:
        """agent trigger should POST to /api/agents/{id}/trigger."""
        with patch("autodev.cli.main.api_post") as mock_post:
            mock_post.return_value = {"status": "triggered"}
            result = runner.invoke(app, ["agent", "trigger", "developer"])

        assert result.exit_code == 0
        assert "developer" in result.output
        mock_post.assert_called_once_with("/api/agents/developer/trigger", {})

    def test_agent_trigger_with_task(self) -> None:
        """agent trigger should pass task_id when provided."""
        with patch("autodev.cli.main.api_post") as mock_post:
            mock_post.return_value = {}
            result = runner.invoke(app, ["agent", "trigger", "tester", "--task", "task-999"])

        assert result.exit_code == 0
        payload = mock_post.call_args[0][1]
        assert payload["task_id"] == "task-999"


# ---------------------------------------------------------------------------
# Test: autodev release create
# ---------------------------------------------------------------------------

class TestReleaseCreate:
    def test_release_create(self) -> None:
        """release create should POST to /api/releases."""
        with patch("autodev.cli.main.api_post") as mock_post:
            mock_post.return_value = {"id": "rel1", "version": "1.0.0", "status": "draft"}
            result = runner.invoke(app, ["release", "create", "--version", "1.0.0"])

        assert result.exit_code == 0
        assert "1.0.0" in result.output
        mock_post.assert_called_once_with("/api/releases", {"version": "1.0.0"})


# ---------------------------------------------------------------------------
# Test: autodev release approve
# ---------------------------------------------------------------------------

class TestReleaseApprove:
    def test_release_approve(self) -> None:
        """release approve should find by version and POST approve."""
        releases = [{"id": "rel1", "version": "1.0.0", "status": "ready"}]
        with (
            patch("autodev.cli.main.api_get") as mock_get,
            patch("autodev.cli.main.api_post") as mock_post,
        ):
            mock_get.return_value = releases
            mock_post.return_value = {"status": "approved"}
            result = runner.invoke(app, ["release", "approve", "1.0.0"])

        assert result.exit_code == 0
        assert "1.0.0" in result.output
        mock_post.assert_called_once_with("/api/releases/rel1/approve", {})

    def test_release_approve_not_found(self) -> None:
        """release approve should exit 1 if version not found."""
        with patch("autodev.cli.main.api_get") as mock_get:
            mock_get.return_value = []
            result = runner.invoke(app, ["release", "approve", "9.9.9"])

        assert result.exit_code != 0
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# Test: autodev logs
# ---------------------------------------------------------------------------

class TestLogs:
    def test_logs_no_file(self) -> None:
        """logs should warn when no log file found."""
        result = runner.invoke(app, ["logs"])
        assert result.exit_code == 0
        assert "No log file found" in result.output

    def test_logs_reads_file(self, tmp_path: Path) -> None:
        """logs should show last N lines from log file."""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\nline3\n")

        with patch("autodev.cli.main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["logs", "--file", str(log_file)])

        assert result.exit_code == 0
        mock_run.assert_called_once()
