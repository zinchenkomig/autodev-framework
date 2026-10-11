"""Claude runner: parsing, guard, outcome mapping, cancel/timeout."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk.types import RateLimitInfo

import autodev.core.claude as claude_mod
from autodev.core.claude import ClaudeRunner, describe_tool_use, forbidden_reason, parse_reset_time


def result(**kw) -> ResultMessage:
    base = dict(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=3,
        session_id="s-1",
        total_cost_usd=0.12,
        result="",
        structured_output={"status": "done", "summary": "Сделал"},
    )
    base.update(kw)
    return ResultMessage(**base)


def fake_query(messages, delay: float = 0):
    async def _query(prompt, options):
        for m in messages:
            if delay:
                await asyncio.sleep(delay)
            yield m

    return _query


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("You've hit your limit · resets 3am (UTC)", (3, 0)),
        ("limit reached, resets 3pm UTC", (15, 0)),
        ("resets at 15:30 UTC", (15, 30)),
        ("resets 12am (UTC)", (0, 0)),
    ],
)
def test_parse_reset_time(text: str, expected: tuple[int, int]) -> None:
    now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    reset = parse_reset_time(text, now)
    assert reset is not None and (reset.hour, reset.minute) == expected
    assert reset > now


def test_parse_reset_time_none() -> None:
    assert parse_reset_time("all good") is None


def test_describe_tool_use() -> None:
    assert describe_tool_use("Bash", {"command": "pytest -q\nmore"}) == "🔧 Bash: pytest -q"
    assert describe_tool_use("Edit", {"file_path": "/a.py"}) == "🔧 Edit: /a.py"
    assert describe_tool_use("TodoWrite", {}) == "🔧 TodoWrite"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf ~",
        "sudo systemctl stop k3s",
        "reboot",
        "kubectl delete namespace app-prod",
        "kubectl -n app-vpn delete pod x",
        "kubectl delete pod x --namespace=argocd",
        "kubectl delete pods --all -A",
        "iptables -F",
        "git push origin main",
    ],
)
def test_guard_blocks(command: str) -> None:
    assert forbidden_reason(command)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf node_modules",
        "pytest -q",
        "docker build .",
        "kubectl -n app-autodev get pods",
        "git push -u origin autodev/1-x",
    ],
)
def test_guard_allows(command: str) -> None:
    assert forbidden_reason(command) is None


async def test_run_success_streams_logs(monkeypatch) -> None:
    messages = [
        AssistantMessage(content=[ToolUseBlock(id="1", name="Bash", input={"command": "ls"})], model="m"),
        AssistantMessage(content=[TextBlock(text="Готово")], model="m"),
        result(),
    ]
    monkeypatch.setattr(claude_mod, "query", fake_query(messages))
    logs = []

    async def on_log(level, message, details):
        logs.append(message)

    r = await ClaudeRunner("/tmp").run("do it", on_log=on_log)
    assert r.ok and r.summary == "Сделал" and r.session_id == "s-1" and r.num_turns == 3
    assert logs == ["🔧 Bash: ls", "💬 Готово"]


async def test_run_blocked(monkeypatch) -> None:
    msg = result(structured_output={"status": "blocked", "summary": "Непонятно что делать"})
    monkeypatch.setattr(claude_mod, "query", fake_query([msg]))
    r = await ClaudeRunner("/tmp").run("x")
    assert not r.ok and r.blocked and "Непонятно" in r.summary


async def test_run_rate_limited_from_event(monkeypatch) -> None:
    info = RateLimitInfo(status="rejected", resets_at=1_900_000_000)
    messages = [RateLimitEvent(rate_limit_info=info, uuid="u", session_id="s"), result(is_error=True, result="limit")]
    monkeypatch.setattr(claude_mod, "query", fake_query(messages))
    r = await ClaudeRunner("/tmp").run("x")
    assert r.rate_limited and r.rate_limited_until == datetime.fromtimestamp(1_900_000_000, UTC)


async def test_run_rate_limited_from_text(monkeypatch) -> None:
    msg = result(is_error=True, result="Claude usage limit reached · resets 3am (UTC)", structured_output=None)
    monkeypatch.setattr(claude_mod, "query", fake_query([msg]))
    r = await ClaudeRunner("/tmp").run("x")
    assert r.rate_limited and r.rate_limited_until.hour == 3


async def test_run_session_missing(monkeypatch) -> None:
    msg = result(is_error=True, result="No conversation found with session ID: abc", structured_output=None)
    monkeypatch.setattr(claude_mod, "query", fake_query([msg]))
    r = await ClaudeRunner("/tmp").run("x", resume="abc")
    assert not r.ok and r.session_missing


async def test_run_without_result_is_failure(monkeypatch) -> None:
    async def broken(prompt, options):
        raise RuntimeError("cli crashed")
        yield  # pragma: no cover

    monkeypatch.setattr(claude_mod, "query", broken)
    r = await ClaudeRunner("/tmp").run("x")
    assert not r.ok and "cli crashed" in r.summary


async def test_run_timeout(monkeypatch) -> None:
    monkeypatch.setattr(claude_mod, "query", fake_query([result()], delay=5))
    r = await ClaudeRunner("/tmp", timeout=0.2).run("x")
    assert r.timed_out and not r.ok


async def test_run_cancel(monkeypatch) -> None:
    monkeypatch.setattr(claude_mod, "query", fake_query([result()], delay=30))
    monkeypatch.setattr(claude_mod.asyncio, "sleep", _fast_sleep)

    async def yes() -> bool:
        return True

    r = await ClaudeRunner("/tmp").run("x", should_cancel=yes)
    assert r.cancelled


_real_sleep = asyncio.sleep


async def _fast_sleep(delay, *a, **kw):
    await _real_sleep(min(delay, 0.01))


def test_options() -> None:
    opts = ClaudeRunner("/w", model="opus", system_prompt_append="rules").options(resume="s")
    assert opts.permission_mode == "bypassPermissions"
    assert opts.env["IS_SANDBOX"] == "1"
    assert opts.resume == "s" and opts.model == "opus"
    assert opts.system_prompt["append"] == "rules"
    assert opts.output_format["schema"]["required"] == ["status", "summary", "test_plan"]
