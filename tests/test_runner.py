"""Tests for autodev.core.runner — AgentResult, MockRunner, ShellRunner, ClaudeCodeRunner."""

from __future__ import annotations

import pytest

from autodev.core.runner import AgentResult, ClaudeCodeRunner, MockRunner, ShellRunner

# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------


class TestAgentResult:
    def test_defaults(self) -> None:
        result = AgentResult(status="success", output="hello")
        assert result.status == "success"
        assert result.output == "hello"
        assert result.artifacts == {}
        assert result.tokens_used == 0
        assert result.cost_usd == 0.0
        assert result.duration_seconds == 0.0

    def test_failure_status(self) -> None:
        result = AgentResult(status="failure", output="oops")
        assert result.status == "failure"

    def test_full_fields(self) -> None:
        result = AgentResult(
            status="success",
            output="done",
            artifacts={"pr": "https://github.com/pr/1"},
            tokens_used=100,
            cost_usd=0.05,
            duration_seconds=3.14,
        )
        assert result.artifacts["pr"] == "https://github.com/pr/1"
        assert result.tokens_used == 100
        assert result.cost_usd == pytest.approx(0.05)
        assert result.duration_seconds == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# MockRunner
# ---------------------------------------------------------------------------


class TestMockRunner:
    @pytest.mark.asyncio
    async def test_returns_default_result(self) -> None:
        runner = MockRunner()
        result = await runner.run("do something", {})
        assert result.status == "success"
        assert result.output == "mock output"
        assert result.tokens_used == 42

    @pytest.mark.asyncio
    async def test_returns_custom_result(self) -> None:
        custom = AgentResult(
            status="failure",
            output="custom error",
            tokens_used=7,
            cost_usd=0.0,
            duration_seconds=0.5,
        )
        runner = MockRunner(result=custom)
        result = await runner.run("anything", {})
        assert result.status == "failure"
        assert result.output == "custom error"
        assert result.tokens_used == 7

    @pytest.mark.asyncio
    async def test_records_calls(self) -> None:
        runner = MockRunner()
        await runner.run("first", {"a": 1})
        await runner.run("second", {"b": 2})
        assert len(runner.calls) == 2
        assert runner.calls[0]["instructions"] == "first"
        assert runner.calls[1]["context"] == {"b": 2}

    @pytest.mark.asyncio
    async def test_multiple_calls_same_result(self) -> None:
        runner = MockRunner()
        r1 = await runner.run("x", {})
        r2 = await runner.run("y", {})
        assert r1.status == r2.status
        assert r1.output == r2.output

    @pytest.mark.asyncio
    async def test_artifacts_preserved(self) -> None:
        custom = AgentResult(
            status="success",
            output="ok",
            artifacts={"pr_url": "https://example.com/pr/42"},
        )
        runner = MockRunner(result=custom)
        result = await runner.run("task", {})
        assert result.artifacts["pr_url"] == "https://example.com/pr/42"


# ---------------------------------------------------------------------------
# ShellRunner
# ---------------------------------------------------------------------------


class TestShellRunner:
    @pytest.mark.asyncio
    async def test_echo(self) -> None:
        runner = ShellRunner("echo hello")
        result = await runner.run("ignored", {})
        assert result.status == "success"
        assert result.output == "hello"
        assert result.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_echo_with_instructions_placeholder(self) -> None:
        runner = ShellRunner("echo {instructions}")
        result = await runner.run("world", {})
        assert result.status == "success"
        assert "world" in result.output

    @pytest.mark.asyncio
    async def test_echo_with_context_placeholder(self) -> None:
        runner = ShellRunner("echo {name}")
        result = await runner.run("", {"name": "autodev"})
        assert result.status == "success"
        assert "autodev" in result.output

    @pytest.mark.asyncio
    async def test_cat_stdin_via_file(self, tmp_path) -> None:
        p = tmp_path / "sample.txt"
        p.write_text("file content\n")
        runner = ShellRunner(f"cat {p}")
        result = await runner.run("", {})
        assert result.status == "success"
        assert "file content" in result.output

    @pytest.mark.asyncio
    async def test_failing_command(self) -> None:
        runner = ShellRunner("exit 1")
        result = await runner.run("", {})
        assert result.status == "failure"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        runner = ShellRunner("sleep 10", timeout=1)
        result = await runner.run("", {})
        assert result.status == "failure"
        assert "Timed out" in result.output

    @pytest.mark.asyncio
    async def test_missing_template_variable(self) -> None:
        runner = ShellRunner("echo {missing_var}")
        result = await runner.run("", {})
        assert result.status == "failure"
        assert "missing_var" in result.output

    @pytest.mark.asyncio
    async def test_duration_is_positive(self) -> None:
        runner = ShellRunner("echo ok")
        result = await runner.run("", {})
        assert result.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# ClaudeCodeRunner — instantiation only (do not invoke Claude in CI)
# ---------------------------------------------------------------------------


class TestClaudeCodeRunnerInstantiation:
    def test_default_init(self) -> None:
        runner = ClaudeCodeRunner()
        assert runner.model == "claude-sonnet-4-20250514"
        assert runner.timeout == 300

    def test_custom_init(self) -> None:
        runner = ClaudeCodeRunner(model="claude-opus-4", timeout=60)
        assert runner.model == "claude-opus-4"
        assert runner.timeout == 60

    def test_has_run_method(self) -> None:
        runner = ClaudeCodeRunner()
        assert callable(runner.run)
