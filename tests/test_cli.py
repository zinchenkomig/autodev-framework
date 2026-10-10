"""CLI."""

from __future__ import annotations

from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from autodev.cli.main import app

runner = CliRunner()


def response(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data, request=httpx.Request("GET", "http://x"))


def test_task_add() -> None:
    with patch(
        "httpx.request", return_value=response({"ticket_number": 4, "title": "Fix", "project_id": "shop"})
    ) as req:
        result = runner.invoke(app, ["task", "add", "Fix", "-p", "shop"])
    assert result.exit_code == 0, result.output
    assert "#4" in result.output
    assert req.call_args.kwargs["json"]["project_id"] == "shop"


def test_task_list() -> None:
    rows = [{"ticket_number": 1, "status": "ci", "project_id": "shop", "title": "Fix", "pr_url": None}]
    with patch("httpx.request", return_value=response(rows)):
        result = runner.invoke(app, ["task", "list"])
    assert result.exit_code == 0 and "Fix" in result.output


def test_release() -> None:
    rel = {"version": "2026.01.01-1", "release_prs": [{"pr_url": "https://pr/1"}]}
    with patch("httpx.request", return_value=response(rel)):
        result = runner.invoke(app, ["release", "shop"])
    assert result.exit_code == 0 and "https://pr/1" in result.output


def test_api_error_exits_nonzero() -> None:
    with patch("httpx.request", return_value=response({"detail": "nope"}, 409)):
        result = runner.invoke(app, ["release", "shop"])
    assert result.exit_code == 1
