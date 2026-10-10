"""AgentRunner protocol and base implementation.

Defines the interface all agents must implement, and provides a base class
with lifecycle hooks and error handling boilerplate.

Also provides LLM-session runner abstractions:
- AgentResult: dataclass for runner output
- AgentRunner: Protocol for LLM-session runners
- ClaudeCodeRunner: Runs claude CLI via asyncio subprocess
- MockRunner: Returns pre-configured results (for tests)
- ShellRunner: Runs arbitrary bash commands (no LLM needed)

"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Result returned by any AgentRunner after executing a task.

    Attributes:
        status: Execution outcome — ``"success"`` or ``"failure"``.
        output: Human-readable text output produced by the agent.
        artifacts: Arbitrary key/value pairs (e.g. PR URLs, file paths).
        tokens_used: Number of LLM tokens consumed (0 for non-LLM runners).
        cost_usd: Estimated monetary cost in USD (0.0 for non-LLM runners).
        duration_seconds: Wall-clock time taken by the run.
    """

    status: Literal["success", "failure"]
    output: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# AgentRunner Protocol
# ---------------------------------------------------------------------------


class AgentRunner(Protocol):
    """Protocol that every LLM-session runner must satisfy.

    Runners implement ``run`` to execute a task given instructions and
    an optional context dictionary, then return an ``AgentResult``.
    """

    async def run(self, instructions: str, context: dict[str, Any]) -> AgentResult:
        """Run the agent with the supplied instructions.

        Args:
            instructions: Natural-language instructions for the agent.
            context: Extra key/value context (repo path, task ID, etc.).

        Returns:
            An ``AgentResult`` describing the outcome.
        """
        ...


# ---------------------------------------------------------------------------
# ClaudeCodeRunner
# ---------------------------------------------------------------------------


class ClaudeCodeRunner:
    """Runs tasks via the ``claude`` CLI (Claude Code).

    Spawns ``claude --print`` as a
    subprocess, pipes *instructions* to stdin, collects stdout, and
    returns an :class:`AgentResult`.

    Args:
        model: Claude model identifier to pass via ``--model``.
        timeout: Maximum number of seconds to wait before killing the process.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        timeout: int = 300,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation of the running process."""
        self._cancelled = True
        if self._process and self._process.returncode is None:
            logger.info("ClaudeCodeRunner: cancelling process (pid=%s)", self._process.pid)
            self._process.kill()

    async def run(self, instructions: str, context: dict[str, Any]) -> AgentResult:
        """Execute *instructions* via the Claude Code CLI.

        Args:
            instructions: Task instructions to pass to Claude.
            context: Dict with 'workdir' for the working directory.

        Returns:
            An :class:`AgentResult` with the captured output and timing.
        """
        self._cancelled = False
        workdir = context.get("workdir")
        cmd = [
            "claude",
            "--print",
            "--model",
            self.model,
            "--permission-mode",
            "bypassPermissions",
        ]
        logger.info("ClaudeCodeRunner: spawning %s in %s", shlex.join(cmd), workdir or "cwd")
        start = time.monotonic()

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    self._process.communicate(instructions.encode()),
                    timeout=self.timeout,
                )
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
                duration = time.monotonic() - start
                logger.warning("ClaudeCodeRunner: timed out after %.1fs", duration)
                return AgentResult(
                    status="failure",
                    output=f"Timed out after {self.timeout}s",
                    duration_seconds=duration,
                )

            duration = time.monotonic() - start

            # Check if cancelled
            if self._cancelled:
                logger.info("ClaudeCodeRunner: cancelled after %.1fs", duration)
                return AgentResult(
                    status="failure",
                    output="Task cancelled by user",
                    duration_seconds=duration,
                )

            output = stdout_bytes.decode(errors="replace").strip()
            stderr_text = stderr_bytes.decode(errors="replace").strip()

            if self._process.returncode == 0:
                logger.info("ClaudeCodeRunner: finished in %.2fs", duration)
                return AgentResult(
                    status="success",
                    output=output,
                    duration_seconds=duration,
                )
            else:
                logger.warning(
                    "ClaudeCodeRunner: exited with code %d, stderr=%r",
                    self._process.returncode,
                    stderr_text,
                )
                return AgentResult(
                    status="failure",
                    output=output or stderr_text,
                    duration_seconds=duration,
                )

        except FileNotFoundError:
            duration = time.monotonic() - start
            logger.error("ClaudeCodeRunner: 'claude' binary not found")
            return AgentResult(
                status="failure",
                output="'claude' binary not found — is Claude Code installed?",
                duration_seconds=duration,
            )
        finally:
            self._process = None


# ---------------------------------------------------------------------------
# MockRunner
# ---------------------------------------------------------------------------


class MockRunner:
    """Pre-configured runner for use in tests.

    Returns a fixed :class:`AgentResult` on every call.  Optionally
    introduces a simulated delay to mimic real execution.

    Args:
        result: The :class:`AgentResult` to return.
        delay: Seconds to sleep before returning (default ``0``).
    """

    def __init__(
        self,
        result: AgentResult | None = None,
        delay: float = 0.0,
    ) -> None:
        self.result: AgentResult = result or AgentResult(
            status="success",
            output="mock output",
            artifacts={},
            tokens_used=42,
            cost_usd=0.001,
            duration_seconds=delay,
        )
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def run(self, instructions: str, context: dict[str, Any]) -> AgentResult:
        """Return the pre-configured result after an optional delay.

        Args:
            instructions: Recorded but otherwise ignored.
            context: Recorded but otherwise ignored.
        """
        self.calls.append({"instructions": instructions, "context": context})
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


# ---------------------------------------------------------------------------
# ShellRunner
# ---------------------------------------------------------------------------


class ShellRunner:
    """Runs an arbitrary bash command for simple tasks that need no LLM.

    The *command* template may contain ``{instructions}`` and ``{key}``
    placeholders which are filled from *instructions* and *context* at
    runtime.

    Args:
        command: Shell command (or template) to execute via ``/bin/bash -c``.
        timeout: Maximum seconds to wait before killing the process.
    """

    def __init__(self, command: str, timeout: int = 60) -> None:
        self.command = command
        self.timeout = timeout

    async def run(self, instructions: str, context: dict[str, Any]) -> AgentResult:
        """Execute the configured shell command.

        Args:
            instructions: Substituted as ``{instructions}`` in the command.
            context: Key/value pairs substituted as ``{key}`` in the command.

        Returns:
            An :class:`AgentResult` with captured stdout/stderr and timing.
        """
        fmt_vars = {"instructions": instructions, **context}
        try:
            rendered = self.command.format(**fmt_vars)
        except KeyError as exc:
            return AgentResult(
                status="failure",
                output=f"Command template error: missing variable {exc}",
            )

        logger.info("ShellRunner: running %r", rendered)
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                rendered,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                duration = time.monotonic() - start
                return AgentResult(
                    status="failure",
                    output=f"Timed out after {self.timeout}s",
                    duration_seconds=duration,
                )

            duration = time.monotonic() - start
            output = stdout_bytes.decode(errors="replace").strip()
            stderr_text = stderr_bytes.decode(errors="replace").strip()
            combined = "\n".join(filter(None, [output, stderr_text]))

            if proc.returncode == 0:
                return AgentResult(
                    status="success",
                    output=output,
                    duration_seconds=duration,
                )
            else:
                return AgentResult(
                    status="failure",
                    output=combined or f"Exit code {proc.returncode}",
                    duration_seconds=duration,
                )

        except FileNotFoundError:
            duration = time.monotonic() - start
            return AgentResult(
                status="failure",
                output="/bin/bash not found",
                duration_seconds=duration,
            )
