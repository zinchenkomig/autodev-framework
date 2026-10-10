"""Stage smoke check: open pages in headless Chromium, collect problems and screenshots.

Deterministic on purpose — it answers "does stage still load, and what does
the change look like", cheaply, after every deploy. Needs the ``qa`` extra
(``playwright``) and a Chromium build (``playwright install chromium``); without
them the check is skipped, never failed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

MAX_PAGES = 4
PAGE_TIMEOUT_MS = 30_000


@dataclass
class PageResult:
    url: str
    status: int | None
    problems: list[str] = field(default_factory=list)
    screenshot: bytes | None = None


@dataclass
class QAResult:
    pages: list[PageResult]
    skipped: str | None = None  # why QA didn't run

    @property
    def ok(self) -> bool:
        return self.skipped is not None or all(not p.problems for p in self.pages)

    @property
    def problems(self) -> list[str]:
        return [f"{p.url}: {problem}" for p in self.pages for problem in p.problems]


def page_urls(stage_url: str, check_paths: list[str], smoke_paths: list[str]) -> list[str]:
    """Pages to visit: where the change is visible first, then the project's smoke pages."""
    base = stage_url if stage_url.endswith("/") else stage_url + "/"
    urls: list[str] = []
    for path in [*check_paths, *(smoke_paths or ["/"])]:
        path = path.strip()
        if not path:
            continue
        url = path if path.startswith(("http://", "https://")) else urljoin(base, path.lstrip("/"))
        if url not in urls:
            urls.append(url)
    return urls[:MAX_PAGES]


async def check_stage(urls: list[str]) -> QAResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return QAResult(pages=[], skipped="playwright is not installed")

    pages: list[PageResult] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                context = await browser.new_context(
                    viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True
                )
                for url in urls:
                    pages.append(await _check_page(context, url))
            finally:
                await browser.close()
    except Exception as exc:  # browser missing, sandbox issues…
        logger.warning("QA skipped: %s", exc)
        return QAResult(pages=pages, skipped=f"browser unavailable: {str(exc).splitlines()[0][:200]}")
    return QAResult(pages=pages)


async def _check_page(context, url: str) -> PageResult:
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"JS error: {str(exc).splitlines()[0][:300]}"))
    result = PageResult(url=url, status=None)
    try:
        response = await page.goto(url, wait_until="load", timeout=PAGE_TIMEOUT_MS)
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass  # long-polling pages never go idle; the load event is enough
        result.status = response.status if response else None
        if result.status is not None and result.status >= 400:
            result.problems.append(f"HTTP {result.status}")
        result.screenshot = await page.screenshot(type="png")
    except Exception as exc:
        result.problems.append(f"failed to load: {str(exc).splitlines()[0][:300]}")
    finally:
        result.problems.extend(errors)
        await page.close()
    return result
