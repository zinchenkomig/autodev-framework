"""Stage QA: URL selection and a real headless-Chromium check against a local server."""

from __future__ import annotations

import http.server
import threading

import pytest

from autodev.worker import qa


def test_page_urls() -> None:
    urls = qa.page_urls("https://stage.app", ["/settings", "users?tab=1"], ["/", "/settings"])
    assert urls == ["https://stage.app/settings", "https://stage.app/users?tab=1", "https://stage.app/"]
    assert qa.page_urls("https://x.dev/sub/", [], []) == ["https://x.dev/sub/"]
    assert len(qa.page_urls("https://x", [f"/{i}" for i in range(10)], [])) == qa.MAX_PAGES


def test_result_ok_semantics() -> None:
    assert qa.QAResult(pages=[], skipped="no browser").ok
    bad = qa.QAResult(pages=[qa.PageResult(url="u", status=500, problems=["HTTP 500"])])
    assert not bad.ok and bad.problems == ["u: HTTP 500"]


PAGES = {
    "/": b"<html><body><h1>ok</h1></body></html>",
    "/broken": b"<html><body><script>throw new Error('boom')</script></body></html>",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGES.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body or b"not found")

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


async def test_check_stage_real_browser(site) -> None:
    pytest.importorskip("playwright")
    result = await qa.check_stage([f"{site}/", f"{site}/broken", f"{site}/missing"])
    if result.skipped:
        pytest.skip(result.skipped)
    ok, broken, missing = result.pages
    assert ok.problems == [] and ok.status == 200 and ok.screenshot.startswith(b"\x89PNG")
    assert any("boom" in p for p in broken.problems)
    assert missing.problems == ["HTTP 404"]
    assert not result.ok
