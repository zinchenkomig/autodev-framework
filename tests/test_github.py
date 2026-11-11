"""GitHubClient against mocked httpx responses."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from autodev.integrations.github import GitHubClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_response(status_code: int = 200, data: Any = None) -> httpx.Response:
    """Create a mock httpx.Response with a dummy request attached."""
    request = httpx.Request("GET", "https://api.github.com/")
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data or {}).encode(),
        headers={"content-type": "application/json"},
        request=request,
    )


def make_client(default_repo: str = "owner/repo") -> GitHubClient:
    return GitHubClient(token="test-token", default_repo=default_repo)


# GitHubClient — create_pr


class TestCreatePR:
    async def test_create_pr(self):
        gh = make_client()
        data = {"number": 10, "title": "Add feature", "state": "open"}
        mock = AsyncMock(return_value=make_response(201, data))
        with patch.object(gh._client, "post", new_callable=AsyncMock, side_effect=mock):
            result = await gh.create_pr(title="Add feature", head="feature/x", base="main")
        assert result["number"] == 10


# GitHubClient — merge_pr


class TestMergePR:
    async def test_merge_pr_squash(self):
        gh = make_client()
        data = {"merged": True, "sha": "abc123", "message": "PR merged"}
        mock_put = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "put", new_callable=AsyncMock, side_effect=mock_put):
            result = await gh.merge_pr(pr_number=10)
        assert result["merged"] is True
        body = mock_put.call_args[1]["json"]
        assert body["merge_method"] == "squash"


# GitHubClient — list_prs / get_pr


class TestListAndGetPR:
    async def test_get_pr(self):
        gh = make_client()
        data = {"number": 10, "title": "My PR"}
        mock = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "get", new_callable=AsyncMock, side_effect=mock):
            result = await gh.get_pr(pr_number=10)
        assert result["title"] == "My PR"


# ===========================================================================
# PR lookup, compare, workflow runs
# ===========================================================================


class TestDeliveryHelpers:
    async def test_find_open_pr_uses_owner_prefixed_head(self):
        client = make_client("acme/shop")
        with patch.object(
            client._client, "get", new=AsyncMock(return_value=make_response(200, [{"number": 3}]))
        ) as get:
            pr = await client.find_open_pr("autodev/1-x", "stage")
        assert pr == {"number": 3}
        assert get.call_args.kwargs["params"]["head"] == "acme:autodev/1-x"

    async def test_find_open_pr_none(self):
        client = make_client("acme/shop")
        with patch.object(client._client, "get", new=AsyncMock(return_value=make_response(200, []))):
            assert await client.find_open_pr("b", "stage") is None

    @pytest.mark.parametrize(
        ("status", "expected"), [("ahead", True), ("identical", True), ("behind", False), ("diverged", False)]
    )
    async def test_contains_commit(self, status, expected):
        client = make_client("acme/shop")
        with patch.object(
            client._client, "get", new=AsyncMock(return_value=make_response(200, {"status": status}))
        ) as get:
            assert await client.contains_commit("stage", "abc") is expected
        assert get.call_args.args[0] == "/repos/acme/shop/compare/abc...stage"

    async def test_merge_pr_commit_title(self):
        client = make_client("acme/shop")
        with patch.object(client._client, "put", new=AsyncMock(return_value=make_response(200, {"sha": "m"}))) as put:
            await client.merge_pr(5, commit_title="Add search (#5)")
        assert put.call_args.kwargs["json"] == {"merge_method": "squash", "commit_title": "Add search (#5)"}
