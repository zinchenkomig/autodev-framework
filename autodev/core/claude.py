"""Claude runner on top of the Claude Agent SDK.

One :meth:`ClaudeRunner.run` call = one agent session in a checkout. Tool
calls and text are streamed to a log callback; the session ends with a
structured result (summary + whether the agent got the task done) that the
worker uses for the PR description and for failing tasks it couldn't do.

The worker runs on the host with full rights. ``IS_SANDBOX=1`` lets
``bypassPermissions`` work as root; a PreToolUse guard still blocks a short
list of commands that would damage the rest of the machine.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

logger = logging.getLogger(__name__)

LogCallback = Callable[[str, str, str | None], Awaitable[None]]  # level, message, details
CancelCheck = Callable[[], Awaitable[bool]]

#: Structured result every session must end with.
RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["done", "blocked"],
            "description": "done = change implemented and committed; blocked = could not do it",
        },
        "summary": {
            "type": "string",
            "description": "2-5 sentences in Russian: what changed and what a reviewer should check, "
            "or why the task is blocked",
        },
        "check_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URL paths on the deployed site where the change is visible, e.g. ['/settings']. "
            "Empty for backend-only changes.",
        },
        "test_plan": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Manual test plan in Russian for the product owner on stage, one step per item. "
            "Step 1 opens the stage home page; after that navigate only through the UI (menu items, tabs, "
            "buttons named by their visible labels in «quotes»), never by URL paths. Then what to do and "
            "what result to expect. Cover the main scenario and the important edge cases. "
            "Empty only when status is blocked.",
        },
    },
    "required": ["status", "summary", "test_plan"],
}

_RATE_LIMIT_TEXT = re.compile(r"usage limit|hit your limit|rate limit|limit reached", re.IGNORECASE)
_RESET_AT = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*\(?UTC\)?", re.IGNORECASE)
_NO_SESSION = re.compile(r"no conversation found", re.IGNORECASE)

# Commands that would hurt the host or other workloads on it. The agent may
# do anything else (docker, kubectl in its own namespaces, package installs…).
_FORBIDDEN_COMMANDS = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*(/|/\*|~|/root|/home|/etc|/var|/usr)(\s|$)"), "deleting system paths"),
    (
        re.compile(r"\b(systemctl|service)\s+(stop|disable|mask|restart)\s+\S*(k3s|docker|containerd|ssh)"),
        "stopping core services",
    ),
    (re.compile(r"\b(shutdown|reboot|poweroff|halt)\b"), "rebooting the host"),
    (re.compile(r"\bkubectl\b.*\bdelete\b.*(\s-A\b|--all-namespaces|\bnamespaces?\b|\bns\b)"), "deleting namespaces"),
    (
        re.compile(
            r"\bkubectl\b"
            r"(?=.*(?:\s-n\s*|--namespace[= ])(?:kube-system|argocd|cert-manager|app-vpn|app-immich|app-prod)\b)"
            r"(?=.*\b(?:delete|apply|edit|patch|scale|replace|rollout|set)\b)"
        ),
        "changing other workloads",
    ),
    (re.compile(r"\b(mkfs|fdisk|parted|wipefs)\b|\bdd\s+.*of=/dev/"), "touching disks"),
    (re.compile(r"\biptables\b|\bufw\b|\bnft\b"), "changing the firewall"),
    (re.compile(r"\bgit\s+push\b.*\s(main|master)(\s|$)"), "pushing to the production branch"),
]


def forbidden_reason(command: str) -> str | None:
    """Why *command* is not allowed on the host, or None if it is fine."""
    for pattern, reason in _FORBIDDEN_COMMANDS:
        if pattern.search(command):
            return reason
    return None


async def _guard_hook(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
    if input_data.get("tool_name") != "Bash":
        return {}
    reason = forbidden_reason(str(input_data.get("tool_input", {}).get("command", "")))
    if reason is None:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by AutoDev host guard ({reason}). Find another way.",
        }
    }


@dataclass
class ClaudeResult:
    ok: bool  # session finished and the agent reports the task done
    summary: str  # agent's summary, or the error
    session_id: str | None = None
    blocked: bool = False  # agent says it can't do the task
    cost_usd: float = 0.0
    num_turns: int = 0
    rate_limited_until: datetime | None = None
    cancelled: bool = False
    timed_out: bool = False
    session_missing: bool = False  # the --resume target no longer exists
    data: dict[str, Any] = field(default_factory=dict)  # the structured result

    @property
    def rate_limited(self) -> bool:
        return self.rate_limited_until is not None


def parse_reset_time(text: str, now: datetime | None = None) -> datetime | None:
    """Parse "resets 3am (UTC)" / "resets at 15:30 UTC" into the next such moment."""
    match = _RESET_AT.search(text)
    if not match:
        return None
    now = now or datetime.now(UTC)
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return reset if reset > now else reset + timedelta(days=1)


def describe_tool_use(name: str, tool_input: dict) -> str:
    """One-line description of a tool call for the task log."""
    for key in ("description", "command", "file_path", "pattern", "url", "prompt", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"🔧 {name}: {value.strip().splitlines()[0][:200]}"
    return f"🔧 {name}"


class ClaudeRunner:
    """Runs agent sessions in *cwd*."""

    def __init__(
        self,
        cwd: str,
        *,
        model: str | None = None,
        timeout: int = 45 * 60,
        env: dict[str, str] | None = None,
        system_prompt_append: str | None = None,
        max_budget_usd: float | None = None,
        cli_path: str | None = None,
        schema: dict[str, Any] | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> None:
        self.cwd = cwd
        self.model = model or None
        self.timeout = timeout
        self.env = env or {}
        self.system_prompt_append = system_prompt_append
        self.max_budget_usd = max_budget_usd
        self.cli_path = cli_path
        self.schema = schema or RESULT_SCHEMA
        self.disallowed_tools = disallowed_tools or []

    def options(self, resume: str | None = None) -> ClaudeAgentOptions:
        system_prompt: Any = None
        if self.system_prompt_append:
            system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt_append}
        return ClaudeAgentOptions(
            cwd=self.cwd,
            model=self.model,
            resume=resume,
            permission_mode="bypassPermissions",
            system_prompt=system_prompt,
            setting_sources=["project"],  # the repo's CLAUDE.md and .claude/settings.json
            env={"IS_SANDBOX": "1", **self.env},
            output_format={"type": "json_schema", "schema": self.schema},
            max_budget_usd=self.max_budget_usd,
            cli_path=self.cli_path,
            hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[_guard_hook])]},
            disallowed_tools=self.disallowed_tools,
        )

    async def run(
        self,
        prompt: str,
        *,
        resume: str | None = None,
        on_log: LogCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> ClaudeResult:
        state = _State()
        consumer = asyncio.create_task(self._consume(prompt, resume, state, on_log))
        watcher = asyncio.create_task(_watch_cancel(should_cancel)) if should_cancel else None
        waiting = {consumer} | ({watcher} if watcher else set())
        try:
            done, _ = await asyncio.wait(waiting, timeout=self.timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in waiting:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*waiting, return_exceptions=True)

        if consumer not in done:
            if watcher is not None and watcher in done:
                return ClaudeResult(ok=False, summary="Cancelled", session_id=state.session_id, cancelled=True)
            return ClaudeResult(
                ok=False, summary=f"Timed out after {self.timeout}s", session_id=state.session_id, timed_out=True
            )
        return state.outcome(consumer.exception())

    async def _consume(self, prompt: str, resume: str | None, state: _State, on_log: LogCallback | None) -> None:
        async for message in query(prompt=prompt, options=self.options(resume)):
            await state.handle(message, on_log)


async def _watch_cancel(should_cancel: CancelCheck) -> None:
    while not await should_cancel():
        await asyncio.sleep(5)


class _State:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.result: ResultMessage | None = None
        self.rate_limited_until: datetime | None = None

    async def handle(self, message: Any, on_log: LogCallback | None) -> None:
        self.session_id = getattr(message, "session_id", None) or self.session_id
        if isinstance(message, ResultMessage):
            self.result = message
        elif isinstance(message, RateLimitEvent):
            info = message.rate_limit_info
            if str(info.status) == "rejected" and info.resets_at:
                self.rate_limited_until = datetime.fromtimestamp(int(info.resets_at), UTC)
        elif isinstance(message, AssistantMessage) and on_log is not None:
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name != "StructuredOutput":
                    await on_log("info", describe_tool_use(block.name, block.input or {}), None)
                elif isinstance(block, TextBlock) and block.text.strip():
                    text = block.text.strip()
                    await on_log("info", f"💬 {text[:300]}", text if len(text) > 300 else None)

    def outcome(self, error: BaseException | None) -> ClaudeResult:
        r = self.result
        if r is None:
            text = str(error) if error else "Session ended without a result"
            if isinstance(error, ClaudeSDKError):
                logger.warning("claude session failed: %s", error)
            return self._failure(text)

        structured = r.structured_output if isinstance(r.structured_output, dict) else {}
        summary = str(structured.get("summary") or r.result or "").strip()
        if r.is_error:
            return self._failure(summary or "; ".join(r.errors or []) or r.subtype, r)

        blocked = structured.get("status") == "blocked"
        return ClaudeResult(
            ok=not blocked,
            summary=summary,
            session_id=r.session_id or self.session_id,
            blocked=blocked,
            cost_usd=float(r.total_cost_usd or 0.0),
            num_turns=r.num_turns,
            data=structured,
        )

    def _failure(self, text: str, r: ResultMessage | None = None) -> ClaudeResult:
        until = self.rate_limited_until
        if until is None and _RATE_LIMIT_TEXT.search(text):
            until = parse_reset_time(text) or datetime.now(UTC) + timedelta(hours=1)
        return ClaudeResult(
            ok=False,
            summary=text,
            session_id=(r.session_id if r else None) or self.session_id,
            cost_usd=float(r.total_cost_usd or 0.0) if r else 0.0,
            num_turns=r.num_turns if r else 0,
            rate_limited_until=until,
            session_missing=bool(_NO_SESSION.search(text)),
        )
