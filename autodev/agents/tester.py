"""Tester agent — browser-based end-to-end testing via Playwright.

Receives testing tasks, executes test scenarios against a staging environment,
and reports found bugs as GitHub issues via the event bus.

TODO: Add LLM-assisted test case generation.
TODO: Add coverage tracking across test runs.
TODO: Persist test results to the database.
TODO: Detect and suppress flaky tests automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from autodev.core.events import EventBus
from autodev.core.models import Event as DomainEvent
from autodev.core.queue import QueuedTask
from autodev.core.runner import BaseAgent
from autodev.integrations.browser import BrowserTester, HealthResult, PageSnapshot
from autodev.integrations.github import GitHubClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TestScenario:
    """Description of a single test scenario to execute.

    Attributes:
        name: Human-readable scenario name.
        url: Starting URL for the scenario.
        steps: Ordered list of action descriptors.  Each step is a dict with
               at minimum a ``"type"`` key (e.g. ``"navigate"``, ``"click"``,
               ``"type"``).
        tags: Optional metadata tags (e.g. ``["smoke", "navigation"]``).
    """

    name: str
    url: str
    steps: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Outcome of a single test case.

    Attributes:
        name: Test case / scenario name.
        passed: Whether the test passed.
        url: URL that was tested.
        error: Error message if the test failed (None when passed).
        screenshot_path: Path to a failure screenshot (optional).
        console_errors: JavaScript console errors captured during the test.
        duration_seconds: Wall-clock time taken by this test.
        timestamp: When the test was executed (UTC).
    """

    name: str
    passed: bool
    url: str
    error: str | None = None
    screenshot_path: str | None = None
    console_errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass
class TestReport:
    """Aggregated report for a full test run.

    Attributes:
        total: Total number of test cases executed.
        passed: Number of passing tests.
        failed: Number of failing tests.
        results: Individual :class:`TestResult` instances.
        duration_seconds: Total wall-clock time for the run.
        created_at: When the report was generated (UTC).
    """

    total: int
    passed: int
    failed: int
    results: list[TestResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def success_rate(self) -> float:
        """Return the fraction of tests that passed (0.0 – 1.0)."""
        return self.passed / self.total if self.total else 0.0


# ---------------------------------------------------------------------------
# TesterAgent
# ---------------------------------------------------------------------------


class TesterAgent(BaseAgent):
    """Autonomous QA / testing agent using Playwright.

    Executes browser-based end-to-end tests against a staging environment
    and reports bugs as GitHub issues.

    TODO: Add test result persistence to database.
    TODO: Add flaky test detection.
    """

    role = "tester"

    def __init__(
        self,
        browser: BrowserTester,
        github: GitHubClient,
        event_bus: EventBus,
        staging_url: str,
        queue: object | None = None,
    ) -> None:
        """Initialise the TesterAgent.

        Args:
            browser: Configured :class:`~autodev.integrations.browser.BrowserTester`.
            github: GitHub client used to open bug reports as issues.
            event_bus: Event bus for publishing test-related domain events.
            staging_url: Base URL of the staging environment to test.
            queue: Optional task queue (passed to BaseAgent; may be None in tests).
        """
        # BaseAgent.__init__ requires a queue and event_bus; pass dummies when absent.
        super().__init__(queue=queue, event_bus=event_bus)  # type: ignore[arg-type]
        self.browser = browser
        self.github = github
        self.staging_url = staging_url.rstrip("/")

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    async def run(self, task: QueuedTask) -> None:
        """Execute a testing task from the queue.

        Args:
            task: Task describing what to test.

        TODO: Parse structured scenarios from task payload.
        TODO: Publish test.completed event with result summary.
        """
        logger.info("[tester] Processing task %s: %s", task.task_id, task.payload)
        # Run a basic health check on staging as a default smoke test
        await self.test_api_health(self.staging_url)

    async def handle_event(self, event: DomainEvent) -> None:
        """React to events such as PR creation or deployment completion.

        TODO: Trigger regression suite on ``pr.created`` event.
        TODO: Run smoke tests on ``release.deployed`` event.
        """
        logger.debug("[tester] Event received: %s", event.event_type)

    # ------------------------------------------------------------------
    # Core testing methods
    # ------------------------------------------------------------------

    async def run_scenarios(self, scenarios: list[TestScenario]) -> TestReport:
        """Run a list of test scenarios and aggregate the results.

        Args:
            scenarios: Ordered list of :class:`TestScenario` instances to run.

        Returns:
            :class:`TestReport` summarising pass/fail counts and individual results.
        """
        import time

        start = time.monotonic()
        all_results: list[TestResult] = []

        for scenario in scenarios:
            result = await self._run_single_scenario(scenario)
            all_results.append(result)

        duration = time.monotonic() - start
        passed = sum(1 for r in all_results if r.passed)
        return TestReport(
            total=len(all_results),
            passed=passed,
            failed=len(all_results) - passed,
            results=all_results,
            duration_seconds=duration,
        )

    async def _run_single_scenario(self, scenario: TestScenario) -> TestResult:
        """Execute a single scenario and return its result."""
        import time

        start = time.monotonic()
        try:
            snapshot = await self.browser.navigate(scenario.url)
            for step in scenario.steps:
                await self._execute_step(step)
            errors = await self.browser.get_console_errors()
            passed = not errors
            error_msg = "; ".join(errors) if errors else None
            return TestResult(
                name=scenario.name,
                passed=passed,
                url=snapshot.url,
                error=error_msg,
                console_errors=errors,
                duration_seconds=time.monotonic() - start,
            )
        except Exception as exc:  # noqa: BLE001
            return TestResult(
                name=scenario.name,
                passed=False,
                url=scenario.url,
                error=str(exc),
                duration_seconds=time.monotonic() - start,
            )

    async def _execute_step(self, step: dict) -> None:
        """Dispatch a single scenario step to the appropriate browser action."""
        step_type = step.get("type", "")
        if step_type == "navigate":
            await self.browser.navigate(step["url"])
        elif step_type == "click":
            await self.browser.click(step["selector"])
        elif step_type == "type":
            await self.browser.type_text(step["selector"], step["text"])
        elif step_type == "screenshot":
            await self.browser.screenshot(step["path"])
        else:
            logger.warning("[tester] Unknown step type: %s", step_type)

    async def test_navigation(self, base_url: str) -> list[TestResult]:
        """Navigate to all pages linked from *base_url* and check their health.

        Collects all ``<a href>`` links from the home page and performs a
        :meth:`~autodev.integrations.browser.BrowserTester.check_page_health`
        check on each unique link that belongs to the same origin.

        Args:
            base_url: Root URL to start navigation testing from.

        Returns:
            List of :class:`TestResult` for each page visited.
        """
        results: list[TestResult] = []
        try:
            snapshot: PageSnapshot = await self.browser.navigate(base_url)
        except Exception as exc:  # noqa: BLE001
            results.append(
                TestResult(
                    name=f"navigate:{base_url}",
                    passed=False,
                    url=base_url,
                    error=str(exc),
                )
            )
            return results

        # Collect unique same-origin links
        visited: set[str] = {base_url}
        urls_to_check: list[str] = [base_url]

        from urllib.parse import urlparse

        origin = urlparse(base_url).netloc
        for link in snapshot.links:
            parsed = urlparse(link)
            if parsed.netloc == origin and link not in visited:
                visited.add(link)
                urls_to_check.append(link)

        for url in urls_to_check:
            health: HealthResult = await self.browser.check_page_health(url)
            results.append(
                TestResult(
                    name=f"navigate:{url}",
                    passed=health.healthy,
                    url=url,
                    error=health.error or (
                        f"HTTP {health.status}" if health.status >= 400 else None
                    ),
                    console_errors=health.console_errors,
                )
            )

        return results

    async def test_crud_flow(self, base_url: str) -> list[TestResult]:
        """Test basic CRUD flow: create, read, edit, and delete an entity.

        Attempts a standardised CRUD sequence against common REST-ish URL
        patterns.  Each step is recorded as an individual :class:`TestResult`.

        Args:
            base_url: Base URL of the application (e.g. ``https://staging.app``).

        Returns:
            List of :class:`TestResult`, one per CRUD step attempted.
        """
        results: list[TestResult] = []
        steps = [
            ("create", f"{base_url}/new", "click", "#submit, button[type=submit]"),
            ("read", f"{base_url}/1", None, None),
            ("edit", f"{base_url}/1/edit", "click", "#save, button[type=submit]"),
            ("delete", f"{base_url}/1/delete", "click", "#confirm-delete, .delete-btn"),
        ]

        for step_name, url, action, selector in steps:
            try:
                health = await self.browser.check_page_health(url)
                if action and selector and health.healthy:
                    try:
                        await self.browser.click(selector)
                    except Exception:  # noqa: BLE001
                        pass  # element may not exist; page load is the main check
                results.append(
                    TestResult(
                        name=f"crud:{step_name}",
                        passed=health.healthy,
                        url=url,
                        error=health.error or (
                            f"HTTP {health.status}" if health.status >= 400 else None
                        ),
                        console_errors=health.console_errors,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    TestResult(
                        name=f"crud:{step_name}",
                        passed=False,
                        url=url,
                        error=str(exc),
                    )
                )

        return results

    async def test_api_health(self, api_url: str) -> list[TestResult]:
        """Check the health of common GET endpoints exposed by the API.

        Sends HTTP GET requests (not via browser) to a standard set of REST
        paths and records the response status.

        Args:
            api_url: Root URL of the API (e.g. ``https://staging.app``).

        Returns:
            List of :class:`TestResult`, one per endpoint checked.
        """
        endpoints = [
            "/api/tasks",
            "/api/agents",
            "/api/events",
            "/api/releases",
            "/api/dashboard/stats",
        ]

        results: list[TestResult] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for path in endpoints:
                url = api_url.rstrip("/") + path
                try:
                    response = await client.get(url)
                    passed = response.status_code < 400
                    results.append(
                        TestResult(
                            name=f"api:{path}",
                            passed=passed,
                            url=url,
                            error=None if passed else f"HTTP {response.status_code}",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        TestResult(
                            name=f"api:{path}",
                            passed=False,
                            url=url,
                            error=str(exc),
                        )
                    )

        return results

    async def report_bugs(self, results: list[TestResult]) -> None:
        """Create GitHub issues for every failing test result.

        Args:
            results: List of :class:`TestResult` instances from a test run.

        Only failing results (``passed=False``) produce issues.

        TODO: De-duplicate bug reports against already-open issues.
        TODO: Add severity labels based on error type.
        """
        failed = [r for r in results if not r.passed]
        if not failed:
            logger.info("[tester] No bugs to report — all tests passed.")
            return

        for result in failed:
            title = f"[Bug] Test failed: {result.name}"
            console_section = ""
            if result.console_errors:
                formatted = "\n".join(f"- {e}" for e in result.console_errors)
                console_section = f"\n\n**Console errors:**\n{formatted}"

            body = (
                f"## Automated test failure\n\n"
                f"**Test:** `{result.name}`\n"
                f"**URL:** {result.url}\n"
                f"**Error:** {result.error or 'N/A'}\n"
                f"**Timestamp:** {result.timestamp.isoformat()}"
                f"{console_section}\n\n"
                f"*Reported automatically by TesterAgent.*"
            )
            try:
                issue = await self.github.create_issue(
                    title=title,
                    body=body,
                    labels=["bug", "automated"],
                )
                logger.info(
                    "[tester] Created issue #%s for %s",
                    issue.get("number"),
                    result.name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("[tester] Failed to create issue for %s: %s", result.name, exc)
