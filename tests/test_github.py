"""Tests for GitHub integration — GitHubClient and webhook endpoint.

Covers:
- GitHubClient methods (mock httpx responses)
- Webhook signature verification
- Webhook event routing
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from autodev.integrations.github import GitHubClient, verify_webhook_signature

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


def sign_payload(payload: bytes, secret: str) -> str:
    """Return a valid X-Hub-Signature-256 header value."""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def make_client(default_repo: str = "owner/repo") -> GitHubClient:
    return GitHubClient(token="test-token", default_repo=default_repo)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# ===========================================================================
# 1. GitHubClient — create_issue
# ===========================================================================


class TestCreateIssue:
    async def test_create_issue_basic(self):
        gh = make_client()
        data = {"number": 42, "title": "Test issue", "state": "open"}
        mock = AsyncMock(return_value=make_response(201, data))
        with patch.object(gh._client, "post", new_callable=AsyncMock, side_effect=mock):
            result = await gh.create_issue(title="Test issue", body="body text")
        assert result["number"] == 42
        assert result["title"] == "Test issue"

    async def test_create_issue_with_labels(self):
        gh = make_client()
        data = {"number": 1, "title": "Bug", "labels": [{"name": "bug"}]}
        mock = AsyncMock(return_value=make_response(201, data))
        with patch.object(gh._client, "post", new_callable=AsyncMock, side_effect=mock):
            result = await gh.create_issue(title="Bug", labels=["bug"])
        assert result["labels"][0]["name"] == "bug"

    async def test_create_issue_uses_repo_override(self):
        gh = make_client(default_repo="default/repo")
        data = {"number": 5, "title": "T"}
        mock_post = AsyncMock(return_value=make_response(201, data))
        with patch.object(gh._client, "post", new_callable=AsyncMock, side_effect=mock_post):
            await gh.create_issue(title="T", repo="other/repo")
        call_args = mock_post.call_args
        assert "other/repo" in call_args[0][0]


# ===========================================================================
# 2. GitHubClient — close_issue
# ===========================================================================


class TestCloseIssue:
    async def test_close_issue(self):
        gh = make_client()
        data = {"number": 7, "state": "closed"}
        mock = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "patch", new_callable=AsyncMock, side_effect=mock):
            result = await gh.close_issue(issue_number=7)
        assert result["state"] == "closed"


# ===========================================================================
# 3. GitHubClient — list_issues
# ===========================================================================


class TestListIssues:
    async def test_list_issues_open(self):
        gh = make_client()
        data = [{"number": 1, "title": "A"}, {"number": 2, "title": "B"}]
        mock = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "get", new_callable=AsyncMock, side_effect=mock):
            result = await gh.list_issues(state="open")
        assert len(result) == 2

    async def test_list_issues_with_labels(self):
        gh = make_client()
        data = [{"number": 3, "title": "C"}]
        mock_get = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "get", new_callable=AsyncMock, side_effect=mock_get):
            result = await gh.list_issues(labels=["bug", "critical"])
        assert result == data
        params = mock_get.call_args[1]["params"]
        assert "bug,critical" in params.get("labels", "")


# ===========================================================================
# 4. GitHubClient — create_pr
# ===========================================================================


class TestCreatePR:
    async def test_create_pr(self):
        gh = make_client()
        data = {"number": 10, "title": "Add feature", "state": "open"}
        mock = AsyncMock(return_value=make_response(201, data))
        with patch.object(gh._client, "post", new_callable=AsyncMock, side_effect=mock):
            result = await gh.create_pr(title="Add feature", head="feature/x", base="main")
        assert result["number"] == 10


# ===========================================================================
# 5. GitHubClient — merge_pr
# ===========================================================================


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


# ===========================================================================
# 6. GitHubClient — list_prs / get_pr
# ===========================================================================


class TestListAndGetPR:
    async def test_list_prs(self):
        gh = make_client()
        data = [{"number": 10}, {"number": 11}]
        mock = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "get", new_callable=AsyncMock, side_effect=mock):
            result = await gh.list_prs(state="open")
        assert len(result) == 2

    async def test_get_pr(self):
        gh = make_client()
        data = {"number": 10, "title": "My PR"}
        mock = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "get", new_callable=AsyncMock, side_effect=mock):
            result = await gh.get_pr(pr_number=10)
        assert result["title"] == "My PR"


# ===========================================================================
# 7. GitHubClient — add_comment
# ===========================================================================


class TestAddComment:
    async def test_add_comment(self):
        gh = make_client()
        data = {"id": 99, "body": "LGTM"}
        mock = AsyncMock(return_value=make_response(201, data))
        with patch.object(gh._client, "post", new_callable=AsyncMock, side_effect=mock):
            result = await gh.add_comment(issue_number=7, body="LGTM")
        assert result["body"] == "LGTM"


# ===========================================================================
# 8. GitHubClient — get_check_status
# ===========================================================================


class TestGetCheckStatus:
    async def test_get_check_status(self):
        gh = make_client()
        data = {"total_count": 1, "check_suites": [{"conclusion": "success"}]}
        mock = AsyncMock(return_value=make_response(200, data))
        with patch.object(gh._client, "get", new_callable=AsyncMock, side_effect=mock):
            result = await gh.get_check_status(ref="main")
        assert result["total_count"] == 1

    async def test_no_default_repo_raises(self):
        gh = GitHubClient(token="tok")
        with pytest.raises(ValueError, match="repo"):
            await gh.create_issue(title="X")


# ===========================================================================
# 9. Webhook signature verification
# ===========================================================================


class TestVerifyWebhookSignature:
    def test_valid_signature(self):
        payload = b'{"action": "opened"}'
        secret = "my-secret"
        sig = sign_payload(payload, secret)
        assert verify_webhook_signature(payload, secret, sig) is True

    def test_invalid_signature(self):
        payload = b'{"action": "opened"}'
        assert verify_webhook_signature(payload, "secret", "sha256=bad") is False

    def test_tampered_payload(self):
        payload = b'{"action": "opened"}'
        sig = sign_payload(payload, "secret")
        tampered = b'{"action": "closed"}'
        assert verify_webhook_signature(tampered, "secret", sig) is False

    def test_wrong_secret(self):
        payload = b"hello"
        sig = sign_payload(payload, "correct-secret")
        assert verify_webhook_signature(payload, "wrong-secret", sig) is False


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
