"""Tests for TesterAgent and BrowserTester data-classes.

Uses mock objects to avoid requiring a running browser or GitHub API.
Minimum 10 test cases covering:
- Data-class construction and properties
- TesterAgent.run_scenarios (happy path, failure path)
- TesterAgent.test_navigation
- TesterAgent.test_crud_flow
- TesterAgent.test_api_health
- TesterAgent.report_bugs
- BrowserTester.check_page_health helper logic
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autodev.agents.tester import (
    TesterAgent,
    TestReport,
    TestResult,
    TestScenario,
)
from autodev.integrations.browser import BrowserTester, HealthResult, PageSnapshot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_browser(
    *,
    navigate_snapshot: PageSnapshot | None = None,
    snapshot_snapshot: PageSnapshot | None = None,
    console_errors: list[str] | None = None,
    health: HealthResult | None = None,
    click_raises: Exception | None = None,
) -> MagicMock:
    """Return a mock BrowserTester with sensible defaults."""
    browser = MagicMock(spec=BrowserTester)

    default_snapshot = PageSnapshot(
        url="https://example.com",
        title="Example",
        accessibility_tree="",
        links=["https://example.com/about", "https://example.com/contact"],
        status=200,
    )
    browser.navigate = AsyncMock(return_value=navigate_snapshot or default_snapshot)
    browser.snapshot = AsyncMock(return_value=snapshot_snapshot or default_snapshot)
    browser.screenshot = AsyncMock(return_value="/tmp/screenshot.png")
    browser.click = AsyncMock(side_effect=click_raises)
    browser.type_text = AsyncMock()
    browser.get_console_errors = AsyncMock(return_value=console_errors or [])
    browser.check_page_health = AsyncMock(
        return_value=health
        or HealthResult(url="https://example.com", status=200, healthy=True)
    )
    browser.start = AsyncMock()
    browser.stop = AsyncMock()
    return browser


def _make_github(**overrides: Any) -> MagicMock:
    github = MagicMock()
    github.create_issue = AsyncMock(return_value={"number": 42, **overrides})
    return github


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


def _make_agent(browser: MagicMock | None = None, **kwargs: Any) -> TesterAgent:
    return TesterAgent(
        browser=browser or _make_browser(),
        github=_make_github(),
        event_bus=_make_event_bus(),
        staging_url="https://staging.example.com",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Data-class: TestResult defaults
# ---------------------------------------------------------------------------


def test_test_result_defaults() -> None:
    result = TestResult(name="test_foo", passed=True, url="https://example.com")
    assert result.passed is True
    assert result.error is None
    assert result.console_errors == []
    assert isinstance(result.timestamp, datetime)
    assert result.timestamp.tzinfo is not None  # timezone-aware


# ---------------------------------------------------------------------------
# 2. Data-class: TestReport success_rate
# ---------------------------------------------------------------------------


def test_test_report_success_rate() -> None:
    results = [
        TestResult(name="a", passed=True, url="https://x.com"),
        TestResult(name="b", passed=True, url="https://x.com"),
        TestResult(name="c", passed=False, url="https://x.com"),
    ]
    report = TestReport(total=3, passed=2, failed=1, results=results)
    assert pytest.approx(report.success_rate) == 2 / 3


def test_test_report_success_rate_empty() -> None:
    report = TestReport(total=0, passed=0, failed=0)
    assert report.success_rate == 0.0


# ---------------------------------------------------------------------------
# 3. Data-class: PageSnapshot
# ---------------------------------------------------------------------------


def test_page_snapshot_defaults() -> None:
    snap = PageSnapshot(url="https://a.com", title="A", accessibility_tree="tree")
    assert snap.links == []
    assert snap.status == 200


# ---------------------------------------------------------------------------
# 4. Data-class: HealthResult
# ---------------------------------------------------------------------------


def test_health_result_defaults() -> None:
    hr = HealthResult(url="https://a.com", status=200)
    assert hr.healthy is True
    assert hr.console_errors == []
    assert hr.error is None


# ---------------------------------------------------------------------------
# 5. run_scenarios — happy path, all pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scenarios_all_pass() -> None:
    browser = _make_browser()
    agent = _make_agent(browser=browser)

    scenarios = [
        TestScenario(name="home", url="https://staging.example.com"),
        TestScenario(name="about", url="https://staging.example.com/about"),
    ]
    report = await agent.run_scenarios(scenarios)

    assert report.total == 2
    assert report.passed == 2
    assert report.failed == 0
    assert len(report.results) == 2
    assert all(r.passed for r in report.results)


# ---------------------------------------------------------------------------
# 6. run_scenarios — failure on console errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scenarios_fails_on_console_errors() -> None:
    browser = _make_browser(console_errors=["TypeError: Cannot read property"])
    agent = _make_agent(browser=browser)

    scenarios = [TestScenario(name="buggy_page", url="https://staging.example.com")]
    report = await agent.run_scenarios(scenarios)

    assert report.failed == 1
    assert not report.results[0].passed
    assert "TypeError" in (report.results[0].error or "")


# ---------------------------------------------------------------------------
# 7. run_scenarios — exception during navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scenarios_navigate_raises() -> None:
    browser = _make_browser()
    browser.navigate = AsyncMock(side_effect=RuntimeError("network error"))
    agent = _make_agent(browser=browser)

    scenarios = [TestScenario(name="unreachable", url="https://unreachable.local")]
    report = await agent.run_scenarios(scenarios)

    assert report.failed == 1
    assert "network error" in report.results[0].error  # type: ignore[operator]


# ---------------------------------------------------------------------------
# 8. test_navigation — collects links and checks health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_navigation_checks_all_links() -> None:
    snapshot = PageSnapshot(
        url="https://staging.example.com",
        title="Home",
        accessibility_tree="",
        links=[
            "https://staging.example.com/about",
            "https://staging.example.com/contact",
        ],
        status=200,
    )
    browser = _make_browser(navigate_snapshot=snapshot)
    agent = _make_agent(browser=browser)

    results = await agent.test_navigation("https://staging.example.com")

    # Should check home + 2 linked pages = 3 total health checks
    assert len(results) == 3
    assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# 9. test_navigation — unhealthy page is reported as failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_navigation_reports_404() -> None:
    snapshot = PageSnapshot(
        url="https://staging.example.com",
        title="Home",
        accessibility_tree="",
        links=["https://staging.example.com/missing"],
        status=200,
    )

    def health_side_effect(url: str) -> HealthResult:
        if "missing" in url:
            return HealthResult(url=url, status=404, healthy=False)
        return HealthResult(url=url, status=200, healthy=True)

    browser = _make_browser(navigate_snapshot=snapshot)
    browser.check_page_health = AsyncMock(side_effect=health_side_effect)
    agent = _make_agent(browser=browser)

    results = await agent.test_navigation("https://staging.example.com")
    failed = [r for r in results if not r.passed]

    assert len(failed) == 1
    assert "missing" in failed[0].url


# ---------------------------------------------------------------------------
# 10. test_api_health — uses httpx mock, success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_api_health_success() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    agent = _make_agent()

    with patch("autodev.agents.tester.httpx.AsyncClient", return_value=mock_client):
        results = await agent.test_api_health("https://staging.example.com")

    assert len(results) == 5
    assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# 11. test_api_health — handles connection error gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_api_health_connection_error() -> None:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

    agent = _make_agent()

    with patch("autodev.agents.tester.httpx.AsyncClient", return_value=mock_client):
        results = await agent.test_api_health("https://staging.example.com")

    assert all(not r.passed for r in results)
    assert all("Connection refused" in (r.error or "") for r in results)


# ---------------------------------------------------------------------------
# 12. report_bugs — creates GitHub issue for each failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_bugs_creates_issues() -> None:
    github = _make_github()
    agent = TesterAgent(
        browser=_make_browser(),
        github=github,
        event_bus=_make_event_bus(),
        staging_url="https://staging.example.com",
    )

    results = [
        TestResult(name="test_a", passed=False, url="https://x.com", error="500 error"),
        TestResult(name="test_b", passed=False, url="https://x.com", error="Timeout"),
        TestResult(name="test_c", passed=True, url="https://x.com"),
    ]
    await agent.report_bugs(results)

    # Only 2 failures → 2 issues created
    assert github.create_issue.call_count == 2


# ---------------------------------------------------------------------------
# 13. report_bugs — does nothing when all tests pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_bugs_no_calls_on_pass() -> None:
    github = _make_github()
    agent = TesterAgent(
        browser=_make_browser(),
        github=github,
        event_bus=_make_event_bus(),
        staging_url="https://staging.example.com",
    )

    results = [
        TestResult(name="test_a", passed=True, url="https://x.com"),
    ]
    await agent.report_bugs(results)

    github.create_issue.assert_not_called()


# ---------------------------------------------------------------------------
# 14. test_crud_flow — happy path returns 4 results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_crud_flow_happy_path() -> None:
    browser = _make_browser()
    agent = _make_agent(browser=browser)

    results = await agent.test_crud_flow("https://staging.example.com/items")

    # create / read / edit / delete = 4 steps
    assert len(results) == 4
    assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# 15. TestScenario with steps is executed in order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scenarios_executes_steps() -> None:
    browser = _make_browser()
    agent = _make_agent(browser=browser)

    scenario = TestScenario(
        name="login",
        url="https://staging.example.com/login",
        steps=[
            {"type": "type", "selector": "#username", "text": "admin"},
            {"type": "type", "selector": "#password", "text": "secret"},
            {"type": "click", "selector": "#submit"},
        ],
    )
    report = await agent.run_scenarios([scenario])

    assert report.total == 1
    assert browser.type_text.call_count == 2
    assert browser.click.call_count == 1
