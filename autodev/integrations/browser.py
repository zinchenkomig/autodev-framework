"""Browser automation integration via Playwright.

Provides a high-level async interface for web scraping, UI testing,
and research tasks performed by agents.

TODO: Add PDF export support.
TODO: Add proxy rotation for scraping.
TODO: Add stealth mode to avoid bot detection.
TODO: Integrate with vector store for research caching.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PageSnapshot:
    """Snapshot of a page's accessibility tree and metadata.

    Attributes:
        url: Current page URL.
        title: Page title.
        accessibility_tree: Serialised accessibility tree as a string.
        links: Absolute href values of all ``<a>`` elements found on the page.
        status: HTTP status code of the navigation response (0 if unknown).
    """

    url: str
    title: str
    accessibility_tree: str
    links: list[str] = field(default_factory=list)
    status: int = 200


@dataclass
class HealthResult:
    """Result of a page health check.

    Attributes:
        url: Checked URL.
        status: HTTP status code returned during navigation.
        console_errors: List of JavaScript console error messages.
        healthy: True when status < 400 and no console errors present.
        error: Optional exception message if the check itself failed.
    """

    url: str
    status: int
    console_errors: list[str] = field(default_factory=list)
    healthy: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# BrowserTester
# ---------------------------------------------------------------------------


class BrowserTester:
    """Async browser testing client wrapping Playwright.

    Uses Playwright's async API with Chromium by default.  Tracks console
    errors on every open page so that callers can inspect them at any time.

    TODO: Add Firefox / WebKit support.
    TODO: Add session / cookie persistence.
    TODO: Add request interception for mocking in tests.

    Example::

        async with BrowserTester() as browser:
            snapshot = await browser.navigate("https://example.com")
            errors = await browser.get_console_errors()
    """

    def __init__(self, headless: bool = True) -> None:
        """Initialise the browser tester.

        Args:
            headless: Run browser in headless mode (default True).
        """
        self.headless = headless
        self._browser = None
        self._playwright = None
        self._page = None
        self._console_errors: list[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the Playwright browser and open a new page.

        TODO: Add browser launch options (proxy, viewport, locale).
        """
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._page = await self._browser.new_page()
        self._console_errors = []
        self._page.on("console", self._handle_console)
        logger.info("BrowserTester launched (headless=%s)", self.headless)

    async def stop(self) -> None:
        """Close the browser and Playwright instance."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        logger.info("BrowserTester closed")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> BrowserTester:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_console(self, msg: object) -> None:
        """Capture console error / warning messages from the active page."""
        msg_type = getattr(msg, "type", "")
        if msg_type in ("error", "warning"):
            text = getattr(msg, "text", str(msg))
            self._console_errors.append(text)

    def _require_page(self) -> object:
        """Return the active page or raise RuntimeError."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def _build_snapshot(self, page: object) -> PageSnapshot:
        """Construct a PageSnapshot from the given Playwright page."""
        url: str = page.url  # type: ignore[attr-defined]
        title: str = await page.title()  # type: ignore[attr-defined]

        # Grab accessibility tree as serialised text
        try:
            snapshot_str: str = await page.accessibility.snapshot() or ""  # type: ignore[attr-defined]
            if not isinstance(snapshot_str, str):
                snapshot_str = str(snapshot_str)
        except Exception:  # noqa: BLE001
            snapshot_str = ""

        # Collect all links present on the page
        try:
            hrefs: list[str] = await page.eval_on_selector_all(  # type: ignore[attr-defined]
                "a[href]",
                "els => els.map(e => e.href)",
            )
        except Exception:  # noqa: BLE001
            hrefs = []

        return PageSnapshot(
            url=url,
            title=title,
            accessibility_tree=snapshot_str,
            links=hrefs,
        )

    # ------------------------------------------------------------------
    # Navigation & interaction
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> PageSnapshot:
        """Navigate the browser to *url* and return a page snapshot.

        Args:
            url: Target URL.

        Returns:
            PageSnapshot containing the accessibility tree and metadata.
        """
        page = self._require_page()
        self._console_errors = []  # reset per navigation
        response = await page.goto(url)  # type: ignore[attr-defined]
        status = response.status if response else 0
        snapshot = await self._build_snapshot(page)
        snapshot.status = status
        return snapshot

    async def snapshot(self) -> PageSnapshot:
        """Return an accessibility tree snapshot for the current page.

        Returns:
            PageSnapshot for the currently loaded page.

        Raises:
            RuntimeError: If the browser has not been started.
        """
        page = self._require_page()
        return await self._build_snapshot(page)

    async def screenshot(self, path: str) -> str:
        """Take a full-page screenshot and save it to *path*.

        Args:
            path: Filesystem path (PNG) to write the screenshot to.

        Returns:
            The resolved *path* that was written.

        Raises:
            RuntimeError: If the browser has not been started.
        """
        page = self._require_page()
        await page.screenshot(path=path, full_page=True)  # type: ignore[attr-defined]
        logger.debug("Screenshot saved to %s", path)
        return path

    async def click(self, selector_or_ref: str) -> None:
        """Click an element identified by a CSS selector or ARIA ref.

        Args:
            selector_or_ref: CSS selector (e.g. ``"button#submit"``) or
                accessible label / role reference.

        Raises:
            RuntimeError: If the browser has not been started.
        """
        page = self._require_page()
        await page.click(selector_or_ref)  # type: ignore[attr-defined]
        logger.debug("Clicked %s", selector_or_ref)

    async def type_text(self, selector_or_ref: str, text: str) -> None:
        """Type *text* into the element identified by *selector_or_ref*.

        Args:
            selector_or_ref: CSS selector or accessible label / role reference.
            text: String to type into the element.

        Raises:
            RuntimeError: If the browser has not been started.
        """
        page = self._require_page()
        await page.fill(selector_or_ref, text)  # type: ignore[attr-defined]
        logger.debug("Typed into %s", selector_or_ref)

    async def get_console_errors(self) -> list[str]:
        """Return JavaScript console error messages captured since the last navigation.

        Returns:
            List of error/warning strings (may be empty).
        """
        return list(self._console_errors)

    async def check_page_health(self, url: str) -> HealthResult:
        """Load *url*, capture HTTP status and console errors.

        Args:
            url: Page URL to check.

        Returns:
            HealthResult describing the page's status and any console errors.
        """
        try:
            snapshot = await self.navigate(url)
            errors = await self.get_console_errors()
            healthy = snapshot.status < 400 and not errors
            return HealthResult(
                url=url,
                status=snapshot.status,
                console_errors=errors,
                healthy=healthy,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Health check failed for %s: %s", url, exc)
            return HealthResult(
                url=url,
                status=0,
                console_errors=[],
                healthy=False,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# BrowserClient — backwards-compatible helper kept for existing code
# ---------------------------------------------------------------------------


class BrowserClient:
    """Async browser automation client wrapping Playwright.

    Uses Playwright's async API with Chromium by default.

    .. deprecated::
        Prefer :class:`BrowserTester` for testing workloads.

    TODO: Add Firefox / WebKit support.
    TODO: Add session / cookie persistence.
    TODO: Add request interception for mocking in tests.

    Example::

        async with BrowserClient() as browser:
            content = await browser.get_text("https://example.com")
    """

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._browser = None
        self._playwright = None

    async def start(self) -> None:
        """Launch the Playwright browser."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        logger.info("Browser launched (headless=%s)", self.headless)

    async def stop(self) -> None:
        """Close the browser and Playwright instance."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    async def get_text(self, url: str) -> str:
        """Navigate to *url* and return visible text content."""
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")
        page = await self._browser.new_page()
        try:
            await page.goto(url)
            return await page.inner_text("body")
        finally:
            await page.close()

    async def screenshot(self, url: str, path: str) -> None:
        """Take a full-page screenshot of *url* and write it to *path*."""
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")
        page = await self._browser.new_page()
        try:
            await page.goto(url)
            await page.screenshot(path=path, full_page=True)
        finally:
            await page.close()

    async def __aenter__(self) -> BrowserClient:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()


@asynccontextmanager
async def browser_session(headless: bool = True) -> AsyncGenerator[BrowserClient, None]:
    """Context manager helper for one-shot browser sessions.

    Example::

        async with browser_session() as browser:
            text = await browser.get_text("https://example.com")
    """
    client = BrowserClient(headless=headless)
    await client.start()
    try:
        yield client
    finally:
        await client.stop()
