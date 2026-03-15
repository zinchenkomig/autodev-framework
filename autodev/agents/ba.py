"""Business Analyst (BA) agent — UX analysis via browser automation.

Receives staging URLs, performs UX evaluations via Playwright, checks page
health, navigation, and new features. Generates structured reports and
creates GitHub Issues for discovered problems.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from datetime import datetime

from autodev.core.events import EventBus, EventTypes
from autodev.core.models import Event as DomainEvent
from autodev.core.queue import QueuedTask
from autodev.core.runner import BaseAgent
from autodev.integrations.browser import BrowserTester, PageSnapshot
from autodev.integrations.github import GitHubClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default navigation pages to check
# ---------------------------------------------------------------------------

DEFAULT_PAGES: list[tuple[str, str]] = [
    ("/", "Home"),
    ("/login", "Login"),
    ("/dashboard", "Dashboard"),
    ("/about", "About"),
    ("/contact", "Contact"),
]

# UX heuristics: accessibility-tree patterns that suggest empty states
EMPTY_STATE_PATTERNS = [
    "no items",
    "no results",
    "nothing here",
    "empty",
    "no data",
    "no content",
    "0 items",
    "list is empty",
]

# Patterns in accessibility tree that indicate UX problems
UX_ISSUE_PATTERNS = [
    ("broken image", "Broken image detected"),
    ("undefined", "Undefined value rendered on page"),
    ("null", "Null value rendered on page"),
    ("error", "Error message visible to user"),
    ("404", "404 reference found in page content"),
    ("lorem ipsum", "Placeholder text (lorem ipsum) left in page"),
    ("todo", "TODO text found in rendered page"),
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UXIssue:
    """A single UX problem found on a page.

    Attributes:
        page_name: Human-readable page name where the issue was found.
        url: URL of the page.
        severity: ``"critical"``, ``"high"``, ``"medium"``, or ``"low"``.
        description: Human-readable description of the issue.
        details: Optional additional technical context.
    """

    page_name: str
    url: str
    severity: str  # critical | high | medium | low
    description: str
    details: str = ""


@dataclass
class PageEvaluation:
    """Result of evaluating a single page.

    Attributes:
        page_name: Human-readable page name.
        url: Evaluated URL.
        loaded: True when the page returned HTTP < 400.
        status_code: HTTP status code received during navigation.
        console_errors: JavaScript console error messages.
        has_empty_state: True when an empty-state pattern was detected.
        ux_issues: List of UX issues discovered on this page.
        snapshot: Optional raw page snapshot.
        error: Exception message if the evaluation itself failed.
    """

    page_name: str
    url: str
    loaded: bool
    status_code: int
    console_errors: list[str] = field(default_factory=list)
    has_empty_state: bool = False
    ux_issues: list[UXIssue] = field(default_factory=list)
    snapshot: PageSnapshot | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        """Return True when the page is healthy with no UX issues."""
        return (
            self.loaded
            and not self.console_errors
            and not self.has_empty_state
            and not self.ux_issues
            and self.error is None
        )


@dataclass
class FeatureEvaluation:
    """Result of evaluating a specific feature.

    Attributes:
        feature: Feature name / identifier.
        base_url: Base URL that was checked.
        page_evaluations: Per-page evaluations performed for this feature.
        found: True when the feature was found / reachable on the page.
        notes: Free-form evaluation notes.
    """

    feature: str
    base_url: str
    page_evaluations: list[PageEvaluation] = field(default_factory=list)
    found: bool = False
    notes: str = ""

    @property
    def passed(self) -> bool:
        """Return True when the feature was found and all evaluations passed."""
        return self.found and all(e.passed for e in self.page_evaluations)


@dataclass
class BAReport:
    """Aggregated UX evaluation report.

    Attributes:
        staging_url: Base staging URL that was evaluated.
        page_evaluations: Evaluations for each visited page.
        feature_evaluations: Evaluations for each tested feature.
        total_issues: Total count of UX issues discovered.
        critical_issues: Count of critical-severity issues.
        summary: Human-readable summary string.
        created_at: UTC timestamp of report creation.
        github_issue_numbers: Issue numbers created in GitHub for this report.
    """

    staging_url: str
    page_evaluations: list[PageEvaluation] = field(default_factory=list)
    feature_evaluations: list[FeatureEvaluation] = field(default_factory=list)
    total_issues: int = 0
    critical_issues: int = 0
    summary: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(_dt.UTC))
    github_issue_numbers: list[int] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return True when no critical issues were found."""
        return self.critical_issues == 0


# ---------------------------------------------------------------------------
# BAAgent
# ---------------------------------------------------------------------------


class BAAgent(BaseAgent):
    """Autonomous Business Analyst agent for UX evaluation.

    Navigates staging environments using a headless browser, checks page
    health and UX quality, and files GitHub Issues for discovered problems.

    Args:
        browser: :class:`~autodev.integrations.browser.BrowserTester` instance.
        github: :class:`~autodev.integrations.github.GitHubClient` instance.
        event_bus: :class:`~autodev.core.events.EventBus` for publishing events.
        config: Configuration dict.  Recognised keys:

            - ``navigation_pages`` – list of ``(path, name)`` tuples to visit.
            - ``github_repo`` – ``owner/repo`` for issue creation.
            - ``issue_labels`` – labels to apply to created GitHub issues.
    """

    role = "ba"

    def __init__(
        self,
        browser: BrowserTester,
        github: GitHubClient,
        event_bus: EventBus,
        config: dict,
    ) -> None:
        self.browser = browser
        self.github = github
        self.event_bus = event_bus
        self.config = config

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    async def run(self, task: QueuedTask) -> None:
        """Run a BA evaluation task.

        Args:
            task: Task whose ``payload`` should contain ``staging_url``.
        """
        staging_url: str = task.payload.get("staging_url", "")
        if not staging_url:
            logger.warning("[ba] Task %s missing staging_url", task.task_id)
            return
        logger.info("[ba] Evaluating staging: %s", staging_url)
        report = await self.evaluate_staging(staging_url)
        logger.info(
            "[ba] Report ready: %d issues (%d critical) — %s",
            report.total_issues,
            report.critical_issues,
            report.summary,
        )

    async def handle_event(self, event: DomainEvent) -> None:
        """Handle domain events such as ``deploy.staging``.

        Args:
            event: Incoming domain event.
        """
        logger.debug("[ba] Event received: %s", event.event_type)
        if event.event_type == EventTypes.DEPLOY_STAGING:
            staging_url = (
                event.payload.get("staging_url", "") if event.payload else ""
            )
            if staging_url:
                await self.evaluate_staging(staging_url)

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    async def evaluate_staging(self, staging_url: str) -> BAReport:
        """Perform a full UX evaluation of a staging environment.

        Runs navigation evaluation, generates a report, and (if configured)
        files GitHub Issues for discovered problems.

        Args:
            staging_url: Base URL of the staging environment.

        Returns:
            Completed :class:`BAReport`.
        """
        logger.info("[ba] Starting staging evaluation: %s", staging_url)

        page_evaluations = await self.evaluate_navigation(staging_url)
        report = await self.generate_report(page_evaluations)
        report.staging_url = staging_url

        if report.total_issues > 0 and self.config.get("github_repo"):
            issue_numbers = await self.report_issues(report)
            report.github_issue_numbers = issue_numbers

        await self.event_bus.emit(
            EventTypes.BUG_FOUND if report.critical_issues else EventTypes.REVIEW_PASSED,
            payload={
                "staging_url": staging_url,
                "total_issues": report.total_issues,
                "critical_issues": report.critical_issues,
            },
            source="ba-agent",
        )
        return report

    async def check_page(self, url: str, page_name: str) -> PageEvaluation:
        """Open *url*, take a snapshot, and evaluate UX quality.

        Checks:
        - Whether the page loaded (HTTP < 400)
        - Console errors from JavaScript
        - Empty-state patterns in the accessibility tree
        - Known UX problem patterns

        Args:
            url: Full URL to check.
            page_name: Human-readable label for the page.

        Returns:
            :class:`PageEvaluation` with all findings.
        """
        logger.debug("[ba] Checking page '%s' at %s", page_name, url)
        try:
            snapshot = await self.browser.navigate(url)
            console_errors = await self.browser.get_console_errors()

            loaded = snapshot.status < 400
            issues: list[UXIssue] = []

            # Console errors → high severity issues
            for err in console_errors:
                issues.append(
                    UXIssue(
                        page_name=page_name,
                        url=url,
                        severity="high",
                        description="JavaScript console error",
                        details=err,
                    )
                )

            # Empty state detection
            tree_lower = (snapshot.accessibility_tree or "").lower()
            has_empty = any(pat in tree_lower for pat in EMPTY_STATE_PATTERNS)
            if has_empty:
                issues.append(
                    UXIssue(
                        page_name=page_name,
                        url=url,
                        severity="medium",
                        description="Empty state detected on page",
                        details="Page appears to show an empty state to the user.",
                    )
                )

            # UX pattern heuristics
            for pattern, description in UX_ISSUE_PATTERNS:
                if pattern in tree_lower:
                    issues.append(
                        UXIssue(
                            page_name=page_name,
                            url=url,
                            severity="medium",
                            description=description,
                            details=f"Pattern '{pattern}' found in accessibility tree.",
                        )
                    )

            # HTTP error → critical
            if not loaded:
                issues.append(
                    UXIssue(
                        page_name=page_name,
                        url=url,
                        severity="critical",
                        description=f"Page failed to load (HTTP {snapshot.status})",
                        details=f"Navigation to {url} returned status {snapshot.status}.",
                    )
                )

            return PageEvaluation(
                page_name=page_name,
                url=url,
                loaded=loaded,
                status_code=snapshot.status,
                console_errors=console_errors,
                has_empty_state=has_empty,
                ux_issues=issues,
                snapshot=snapshot,
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("[ba] Failed to check page %s: %s", url, exc)
            return PageEvaluation(
                page_name=page_name,
                url=url,
                loaded=False,
                status_code=0,
                error=str(exc),
                ux_issues=[
                    UXIssue(
                        page_name=page_name,
                        url=url,
                        severity="critical",
                        description="Page evaluation raised an exception",
                        details=str(exc),
                    )
                ],
            )

    async def evaluate_navigation(self, base_url: str) -> list[PageEvaluation]:
        """Visit all configured navigation pages and evaluate each.

        Pages are taken from ``config["navigation_pages"]`` (list of
        ``(path, name)`` tuples) or fall back to :data:`DEFAULT_PAGES`.

        Args:
            base_url: Base URL of the environment (scheme + host, no trailing slash).

        Returns:
            List of :class:`PageEvaluation` objects, one per page.
        """
        pages: list[tuple[str, str]] = self.config.get(
            "navigation_pages", DEFAULT_PAGES
        )
        evaluations: list[PageEvaluation] = []
        for path, name in pages:
            url = base_url.rstrip("/") + path
            evaluation = await self.check_page(url, name)
            evaluations.append(evaluation)
        return evaluations

    async def evaluate_new_features(
        self, base_url: str, features: list[str]
    ) -> list[FeatureEvaluation]:
        """Evaluate specific features by checking their dedicated pages.

        For each feature name the agent looks for a matching page path in the
        accessibility tree of the home page, then checks that page.  If no
        dedicated page is found the home page evaluation is used.

        Args:
            base_url: Base URL of the environment.
            features: List of feature names / identifiers to check.

        Returns:
            List of :class:`FeatureEvaluation` objects.
        """
        feature_evaluations: list[FeatureEvaluation] = []

        # Check home page once to collect available links
        home_eval = await self.check_page(base_url.rstrip("/") + "/", "Home")
        home_links: list[str] = home_eval.snapshot.links if home_eval.snapshot else []

        for feature in features:
            feature_lower = feature.lower().replace(" ", "-")
            # Try to find a link containing the feature name
            matching_links = [
                lnk
                for lnk in home_links
                if feature_lower in lnk.lower()
            ]

            page_evals: list[PageEvaluation] = []
            if matching_links:
                for link in matching_links[:3]:  # cap at 3 links per feature
                    eval_ = await self.check_page(link, f"{feature} page")
                    page_evals.append(eval_)
                found = any(e.loaded for e in page_evals)
                notes = f"Found {len(matching_links)} matching link(s) for '{feature}'."
            else:
                # Fall back to a guessed path
                guessed_url = base_url.rstrip("/") + f"/{feature_lower}"
                eval_ = await self.check_page(guessed_url, f"{feature} (guessed)")
                page_evals.append(eval_)
                found = eval_.loaded
                notes = (
                    f"No link found for '{feature}' on home page; "
                    f"guessed path /{feature_lower}."
                )

            feature_evaluations.append(
                FeatureEvaluation(
                    feature=feature,
                    base_url=base_url,
                    page_evaluations=page_evals,
                    found=found,
                    notes=notes,
                )
            )

        return feature_evaluations

    async def generate_report(self, evaluations: list) -> BAReport:
        """Generate a :class:`BAReport` from a list of evaluations.

        Accepts :class:`PageEvaluation` and :class:`FeatureEvaluation` objects
        (or a mix of both).

        Args:
            evaluations: List of evaluation objects.

        Returns:
            Completed :class:`BAReport`.
        """
        page_evals: list[PageEvaluation] = []
        feature_evals: list[FeatureEvaluation] = []

        for item in evaluations:
            if isinstance(item, PageEvaluation):
                page_evals.append(item)
            elif isinstance(item, FeatureEvaluation):
                feature_evals.append(item)
                page_evals.extend(item.page_evaluations)

        all_issues: list[UXIssue] = []
        for ev in page_evals:
            all_issues.extend(ev.ux_issues)

        total = len(all_issues)
        critical = sum(1 for i in all_issues if i.severity == "critical")

        pages_ok = sum(1 for e in page_evals if e.passed)
        pages_total = len(page_evals)

        if total == 0:
            summary = f"All {pages_total} page(s) passed UX evaluation with no issues."
        else:
            summary = (
                f"{pages_ok}/{pages_total} pages passed. "
                f"Found {total} issue(s) ({critical} critical)."
            )

        return BAReport(
            staging_url="",
            page_evaluations=page_evals,
            feature_evaluations=feature_evals,
            total_issues=total,
            critical_issues=critical,
            summary=summary,
        )

    async def report_issues(self, report: BAReport) -> list[int]:
        """Create GitHub issues for each UX problem in *report*.

        Skips low-severity issues unless ``config["report_all_issues"]`` is set.

        Args:
            report: Completed :class:`BAReport`.

        Returns:
            List of created GitHub Issue numbers.
        """
        repo = self.config.get("github_repo")
        labels: list[str] = self.config.get("issue_labels", ["bug", "ux"])
        report_all: bool = self.config.get("report_all_issues", False)
        issue_numbers: list[int] = []

        all_issues: list[UXIssue] = []
        for ev in report.page_evaluations:
            all_issues.extend(ev.ux_issues)

        for ux_issue in all_issues:
            if not report_all and ux_issue.severity == "low":
                continue

            sev = ux_issue.severity.upper()
            title = f"[BA] [{sev}] {ux_issue.description} — {ux_issue.page_name}"
            body = (
                f"**Page:** {ux_issue.page_name}\n"
                f"**URL:** {ux_issue.url}\n"
                f"**Severity:** {ux_issue.severity}\n\n"
                f"**Description:**\n{ux_issue.description}\n\n"
                f"**Details:**\n{ux_issue.details}\n\n"
                f"---\n"
                f"*Reported automatically by BAAgent on {report.created_at.isoformat()}*"
            )
            try:
                result = await self.github.create_issue(
                    title=title,
                    body=body,
                    labels=labels,
                    repo=repo,
                )
                issue_number: int = result.get("number", 0)
                if issue_number:
                    issue_numbers.append(issue_number)
                    logger.info("[ba] Created GitHub issue #%d: %s", issue_number, title)
            except Exception as exc:  # noqa: BLE001
                logger.error("[ba] Failed to create issue for '%s': %s", title, exc)

        return issue_numbers
