"""GitHub integration — REST API client and webhook helpers.

Provides methods for interacting with GitHub repositories: creating issues,
opening pull requests, managing releases, and verifying webhook signatures.

TODO: Implement GitHub App authentication (JWT + installation token).
TODO: Add GraphQL client for complex queries.
TODO: Add retry logic with exponential backoff for rate limit handling.
TODO: Add webhook signature verification utility.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Async GitHub REST API client.

    Args:
        token: Personal access token or installation token.
        repo: Repository in ``owner/name`` format.

    TODO: Add GraphQL support.
    TODO: Add automatic pagination helper.
    """

    def __init__(self, token: str, repo: str) -> None:
        self.repo = repo
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def create_issue(
        self, title: str, body: str = "", labels: list[str] | None = None,
    ) -> dict:
        """Create a GitHub Issue.

        TODO: Add assignees support.
        TODO: Add milestone support.
        """
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        response = await self._client.post(f"/repos/{self.repo}/issues", json=payload)
        response.raise_for_status()
        return response.json()

    async def create_pull_request(
        self,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
    ) -> dict:
        """Open a pull request.

        TODO: Add draft PR support.
        TODO: Add auto-merge flag.
        """
        payload = {"title": title, "head": head, "base": base, "body": body}
        response = await self._client.post(f"/repos/{self.repo}/pulls", json=payload)
        response.raise_for_status()
        return response.json()

    async def create_release(self, tag: str, name: str, body: str = "") -> dict:
        """Create a GitHub Release.

        TODO: Add asset upload support.
        """
        payload = {"tag_name": tag, "name": name, "body": body}
        response = await self._client.post(f"/repos/{self.repo}/releases", json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


def verify_webhook_signature(payload: bytes, secret: str, signature: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    Args:
        payload: Raw request body bytes.
        secret: Configured webhook secret.
        signature: Value of ``X-Hub-Signature-256`` header.

    Returns:
        True if the signature is valid.

    TODO: Raise specific exception on invalid signature instead of returning False.
    """
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
