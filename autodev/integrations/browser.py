"""Browser automation integration via Playwright.

Provides a high-level async interface for web scraping, UI testing,
and research tasks performed by agents.

TODO: Add screenshot capture and storage.
TODO: Add PDF export support.
TODO: Add proxy rotation for scraping.
TODO: Add stealth mode to avoid bot detection.
TODO: Integrate with vector store for research caching.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class BrowserClient:
    """Async browser automation client wrapping Playwright.

    Uses Playwright's async API with Chromium by default.

    TODO: Add Firefox / WebKit support.
    TODO: Add session / cookie persistence.
    TODO: Add request interception for mocking in tests.

    Example::

        async with BrowserClient() as browser:
            content = await browser.get_text("https://example.com")
    """

    def __init__(self, headless: bool = True) -> None:
        """Initialise the browser client.

        Args:
            headless: Run browser in headless mode (default True).
        """
        self.headless = headless
        self._browser = None
        self._playwright = None

    async def start(self) -> None:
        """Launch the Playwright browser.

        TODO: Add browser launch options (proxy, viewport, locale).
        """
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
        """Navigate to a URL and return visible text content.

        Args:
            url: URL to navigate to.

        Returns:
            Visible page text.

        TODO: Add wait_for selector support.
        TODO: Add JavaScript evaluation support.
        """
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")

        page = await self._browser.new_page()
        try:
            await page.goto(url)
            text = await page.inner_text("body")
            return text
        finally:
            await page.close()

    async def screenshot(self, url: str, path: str) -> None:
        """Take a full-page screenshot.

        Args:
            url: URL to capture.
            path: File path to save the PNG screenshot.

        TODO: Add viewport size configuration.
        """
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
