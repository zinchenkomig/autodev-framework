"""Tests for BAAgent and related dataclasses.

Uses mock objects to avoid requiring a running browser or GitHub API.
Minimum 10 test cases covering:
- Dataclass construction and properties
- BAAgent.check_page (success, load failure, console errors, UX issues)
- BAAgent.evaluate_navigation
- BAAgent.evaluate_new_features
- BAAgent.generate_report
- BAAgent.report_issues
- BAAgent.evaluate_staging (integration)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from autodev.agents.ba import (
    BAAgent,
    BAReport,
    FeatureEvaluation,
    PageEvaluation,
    UXIssue,
)
from autodev.integrations.browser import BrowserTester, PageSnapshot

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BASE_URL = "https://staging.example.com"


def _make_snapshot(
    *,
    url: str = BASE_URL,
    title: str = "Test Page",
    tree: str = "Button[name='Submit'] Link[name='Home']",
    links: list[str] | None = None,
    status: int = 200,
) -> PageSnapshot:
    return PageSnapshot(
        url=url,
        title=title,
        accessibility_tree=tree,
        links=links or [],
        status=status,
    )


def _make_browser(
    *,
    snapshot: PageSnapshot | None = None,
    console_errors: list[str] | None = None,
    navigate_raises: Exception | None = None,
) -> MagicMock:
    """Return a fully-mocked BrowserTester."""
    browser = MagicMock(spec=BrowserTester)
    snap = snapshot or _make_snapshot()

    if navigate_raises:
        browser.navigate = AsyncMock(side_effect=navigate_raises)
    else:
        browser.navigate = AsyncMock(return_value=snap)

    browser.snapshot = AsyncMock(return_value=snap)
    browser.screenshot = AsyncMock(return_value="/tmp/test.png")
    browser.get_console_errors = AsyncMock(return_value=console_errors or [])
    browser.start = AsyncMock()
    browser.stop = AsyncMock()
    return browser


def _make_github(**overrides: Any) -> MagicMock:
    github = MagicMock()
    github.create_issue = AsyncMock(return_value={"number": 42, **overrides})
    return github


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit = AsyncMock(return_value=MagicMock())
    return bus


def _make_agent(
    browser: MagicMock | None = None,
    github: MagicMock | None = None,
    event_bus: MagicMock | None = None,
    config: dict | None = None,
) -> BAAgent:
    return BAAgent(
        browser=browser or _make_browser(),
        github=github or _make_github(),
        event_bus=event_bus or _make_event_bus(),
        config=config or {},
    )


# ---------------------------------------------------------------------------
# 1. Dataclass: UXIssue defaults
# ---------------------------------------------------------------------------


def test_ux_issue_fields() -> None:
    issue = UXIssue(
        page_name="Home",
        url=BASE_URL,
        severity="high",
        description="Console error detected",
    )
    assert issue.severity == "high"
    assert issue.details == ""
    assert issue.page_name == "Home"


# ---------------------------------------------------------------------------
# 2. Dataclass: PageEvaluation.passed
# ---------------------------------------------------------------------------


def test_page_evaluation_passed_when_clean() -> None:
    ev = PageEvaluation(
        page_name="Home",
        url=BASE_URL,
        loaded=True,
        status_code=200,
    )
    assert ev.passed is True


def test_page_evaluation_failed_with_console_errors() -> None:
    ev = PageEvaluation(
        page_name="Home",
        url=BASE_URL,
        loaded=True,
        status_code=200,
        console_errors=["Uncaught ReferenceError: x is not defined"],
    )
    assert ev.passed is False


def test_page_evaluation_failed_when_not_loaded() -> None:
    ev = PageEvaluation(
        page_name="Home",
        url=BASE_URL,
        loaded=False,
        status_code=404,
    )
    assert ev.passed is False


# ---------------------------------------------------------------------------
# 3. Dataclass: FeatureEvaluation.passed
# ---------------------------------------------------------------------------


def test_feature_evaluation_passed() -> None:
    page = PageEvaluation(page_name="Feature", url=BASE_URL, loaded=True, status_code=200)
    feat = FeatureEvaluation(
        feature="search",
        base_url=BASE_URL,
        page_evaluations=[page],
        found=True,
    )
    assert feat.passed is True


def test_feature_evaluation_failed_not_found() -> None:
    feat = FeatureEvaluation(feature="search", base_url=BASE_URL, found=False)
    assert feat.passed is False


# ---------------------------------------------------------------------------
# 4. Dataclass: BAReport.passed
# ---------------------------------------------------------------------------


def test_ba_report_passed_no_critical() -> None:
    report = BAReport(staging_url=BASE_URL, total_issues=1, critical_issues=0)
    assert report.passed is True


def test_ba_report_failed_with_critical() -> None:
    report = BAReport(staging_url=BASE_URL, total_issues=2, critical_issues=1)
    assert report.passed is False


# ---------------------------------------------------------------------------
# 5. check_page — healthy page, no issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_page_healthy() -> None:
    browser = _make_browser()
    agent = _make_agent(browser=browser)

    result = await agent.check_page(BASE_URL + "/", "Home")

    assert result.loaded is True
    assert result.status_code == 200
    assert result.console_errors == []
    assert result.ux_issues == []
    assert result.error is None
    assert result.passed is True


# ---------------------------------------------------------------------------
# 6. check_page — HTTP 404 produces critical UX issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_page_404_is_critical() -> None:
    snap = _make_snapshot(status=404)
    browser = _make_browser(snapshot=snap)
    agent = _make_agent(browser=browser)

    result = await agent.check_page(BASE_URL + "/missing", "Missing")

    assert result.loaded is False
    assert result.status_code == 404
    critical_issues = [i for i in result.ux_issues if i.severity == "critical"]
    assert len(critical_issues) >= 1


# ---------------------------------------------------------------------------
# 7. check_page — console errors are captured and create high-severity issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_page_console_errors() -> None:
    browser = _make_browser(console_errors=["Uncaught TypeError: Cannot read property 'x'"])
    agent = _make_agent(browser=browser)

    result = await agent.check_page(BASE_URL + "/", "Home")

    assert result.console_errors == ["Uncaught TypeError: Cannot read property 'x'"]
    high_issues = [i for i in result.ux_issues if i.severity == "high"]
    assert len(high_issues) >= 1
    assert result.passed is False


# ---------------------------------------------------------------------------
# 8. check_page — empty-state pattern detected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_page_empty_state_detected() -> None:
    snap = _make_snapshot(tree="Heading[name='Dashboard'] Text[name='No items found']")
    browser = _make_browser(snapshot=snap)
    agent = _make_agent(browser=browser)

    result = await agent.check_page(BASE_URL + "/dashboard", "Dashboard")

    assert result.has_empty_state is True
    empty_issues = [i for i in result.ux_issues if "empty" in i.description.lower()]
    assert len(empty_issues) >= 1


# ---------------------------------------------------------------------------
# 9. check_page — exception during navigation is handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_page_navigate_exception() -> None:
    browser = _make_browser(navigate_raises=ConnectionError("Timeout"))
    agent = _make_agent(browser=browser)

    result = await agent.check_page(BASE_URL + "/", "Home")

    assert result.loaded is False
    assert result.error is not None
    assert "Timeout" in result.error
    assert any(i.severity == "critical" for i in result.ux_issues)


# ---------------------------------------------------------------------------
# 10. evaluate_navigation — visits configured pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_navigation_custom_pages() -> None:
    browser = _make_browser()
    config = {
        "navigation_pages": [
            ("/", "Home"),
            ("/about", "About"),
            ("/contact", "Contact"),
        ]
    }
    agent = _make_agent(browser=browser, config=config)

    results = await agent.evaluate_navigation(BASE_URL)

    assert len(results) == 3
    assert results[0].page_name == "Home"
    assert results[1].page_name == "About"
    assert results[2].page_name == "Contact"
    # browser.navigate called 3 times
    assert browser.navigate.call_count == 3


# ---------------------------------------------------------------------------
# 11. evaluate_navigation — uses DEFAULT_PAGES when config absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_navigation_default_pages() -> None:
    from autodev.agents.ba import DEFAULT_PAGES

    browser = _make_browser()
    agent = _make_agent(browser=browser, config={})

    results = await agent.evaluate_navigation(BASE_URL)

    assert len(results) == len(DEFAULT_PAGES)


# ---------------------------------------------------------------------------
# 12. evaluate_new_features — found via link on home page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_new_features_found_via_link() -> None:
    home_snap = _make_snapshot(
        links=[BASE_URL + "/search", BASE_URL + "/about"],
    )
    feature_snap = _make_snapshot(url=BASE_URL + "/search", title="Search")

    browser = MagicMock(spec=BrowserTester)
    browser.navigate = AsyncMock(side_effect=[home_snap, feature_snap])
    browser.get_console_errors = AsyncMock(return_value=[])

    agent = _make_agent(browser=browser)
    results = await agent.evaluate_new_features(BASE_URL, ["search"])

    assert len(results) == 1
    assert results[0].feature == "search"
    assert results[0].found is True


# ---------------------------------------------------------------------------
# 13. evaluate_new_features — guesses path when link not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_new_features_guessed_path() -> None:
    home_snap = _make_snapshot(links=[])  # no matching links
    guessed_snap = _make_snapshot(url=BASE_URL + "/dashboard", status=200)

    browser = MagicMock(spec=BrowserTester)
    browser.navigate = AsyncMock(side_effect=[home_snap, guessed_snap])
    browser.get_console_errors = AsyncMock(return_value=[])

    agent = _make_agent(browser=browser)
    results = await agent.evaluate_new_features(BASE_URL, ["dashboard"])

    assert len(results) == 1
    assert results[0].feature == "dashboard"
    assert results[0].found is True
    assert "guessed" in results[0].notes


# ---------------------------------------------------------------------------
# 14. generate_report — aggregates counts correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_report_counts() -> None:
    page1 = PageEvaluation(
        page_name="Home",
        url=BASE_URL,
        loaded=True,
        status_code=200,
        ux_issues=[
            UXIssue(page_name="Home", url=BASE_URL, severity="critical", description="Critical!"),
            UXIssue(page_name="Home", url=BASE_URL, severity="medium", description="Medium"),
        ],
    )
    page2 = PageEvaluation(page_name="About", url=BASE_URL + "/about", loaded=True, status_code=200)
    agent = _make_agent()

    report = await agent.generate_report([page1, page2])

    assert report.total_issues == 2
    assert report.critical_issues == 1
    assert "2 issue" in report.summary


# ---------------------------------------------------------------------------
# 15. generate_report — empty evaluations produce clean summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_report_no_issues() -> None:
    page = PageEvaluation(page_name="Home", url=BASE_URL, loaded=True, status_code=200)
    agent = _make_agent()

    report = await agent.generate_report([page])

    assert report.total_issues == 0
    assert report.critical_issues == 0
    assert "passed" in report.summary.lower()


# ---------------------------------------------------------------------------
# 16. report_issues — creates GitHub issue for each UX issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_issues_creates_github_issues() -> None:
    github = _make_github()
    config = {"github_repo": "owner/repo", "issue_labels": ["bug"]}
    agent = _make_agent(github=github, config=config)

    report = BAReport(
        staging_url=BASE_URL,
        page_evaluations=[
            PageEvaluation(
                page_name="Home",
                url=BASE_URL,
                loaded=True,
                status_code=200,
                ux_issues=[
                    UXIssue(
                        page_name="Home",
                        url=BASE_URL,
                        severity="high",
                        description="Console error",
                    ),
                    UXIssue(
                        page_name="Home",
                        url=BASE_URL,
                        severity="medium",
                        description="Empty state",
                    ),
                ],
            )
        ],
        total_issues=2,
    )

    issue_numbers = await agent.report_issues(report)

    assert github.create_issue.call_count == 2
    assert all(n == 42 for n in issue_numbers)


# ---------------------------------------------------------------------------
# 17. report_issues — skips low-severity unless report_all_issues=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_issues_skips_low_severity() -> None:
    github = _make_github()
    config = {"github_repo": "owner/repo", "report_all_issues": False}
    agent = _make_agent(github=github, config=config)

    report = BAReport(
        staging_url=BASE_URL,
        page_evaluations=[
            PageEvaluation(
                page_name="Home",
                url=BASE_URL,
                loaded=True,
                status_code=200,
                ux_issues=[
                    UXIssue(page_name="Home", url=BASE_URL, severity="low", description="Minor"),
                ],
            )
        ],
        total_issues=1,
    )

    issue_numbers = await agent.report_issues(report)

    assert github.create_issue.call_count == 0
    assert issue_numbers == []


# ---------------------------------------------------------------------------
# 18. evaluate_staging — full integration flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_staging_full_flow() -> None:
    browser = _make_browser()
    github = _make_github()
    event_bus = _make_event_bus()
    config = {
        "navigation_pages": [("/", "Home")],
        "github_repo": "owner/repo",
    }
    agent = _make_agent(browser=browser, github=github, event_bus=event_bus, config=config)

    report = await agent.evaluate_staging(BASE_URL)

    assert isinstance(report, BAReport)
    assert report.staging_url == BASE_URL
    assert len(report.page_evaluations) == 1
    # event_bus.emit should have been called
    event_bus.emit.assert_called_once()


# ---------------------------------------------------------------------------
# 19. evaluate_staging — issues filed when total_issues > 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_staging_files_issues_on_errors() -> None:
    snap = _make_snapshot(status=200)
    browser = _make_browser(snapshot=snap, console_errors=["JS error"])
    github = _make_github()
    event_bus = _make_event_bus()
    config = {
        "navigation_pages": [("/", "Home")],
        "github_repo": "owner/repo",
    }
    agent = _make_agent(browser=browser, github=github, event_bus=event_bus, config=config)

    report = await agent.evaluate_staging(BASE_URL)

    assert report.total_issues > 0
    assert github.create_issue.called
    assert len(report.github_issue_numbers) > 0


# ---------------------------------------------------------------------------
# 20. generate_report — FeatureEvaluation items are handled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_report_with_feature_evaluations() -> None:
    page = PageEvaluation(page_name="Search", url=BASE_URL + "/search", loaded=True, status_code=200)
    feat = FeatureEvaluation(
        feature="search",
        base_url=BASE_URL,
        page_evaluations=[page],
        found=True,
    )
    agent = _make_agent()

    report = await agent.generate_report([feat])

    assert len(report.feature_evaluations) == 1
    assert len(report.page_evaluations) == 1
    assert report.total_issues == 0
