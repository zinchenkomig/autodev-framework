"""GitHub integration — REST API client and webhook helpers.

Provides methods for interacting with GitHub repositories: creating issues,
opening pull requests, managing releases, and verifying webhook signatures.

TODO: Implement GitHub App authentication (JWT + installation token).
TODO: Add GraphQL client for complex queries.
TODO: Add retry logic with exponential backoff for rate limit handling.
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
        default_repo: Default repository in ``owner/name`` format.

    TODO: Add GraphQL support.
    TODO: Add automatic pagination helper.
    """

    def __init__(self, token: str, default_repo: str | None = None) -> None:
        self.default_repo = default_repo
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _resolve_repo(self, repo: str | None) -> str:
        """Return *repo* if provided, else fall back to *default_repo*.

        Raises:
            ValueError: If neither *repo* nor *default_repo* is set.
        """
        resolved = repo or self.default_repo
        if not resolved:
            raise ValueError("repo must be provided or default_repo must be set")
        return resolved

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def create_issue(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        repo: str | None = None,
    ) -> dict:
        """Create a GitHub Issue.

        Args:
            title: Issue title.
            body: Issue body (Markdown).
            labels: Optional list of label names.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            GitHub API response as a dict.

        TODO: Add assignees support.
        TODO: Add milestone support.
        """
        resolved = self._resolve_repo(repo)
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        response = await self._client.post(f"/repos/{resolved}/issues", json=payload)
        response.raise_for_status()
        return response.json()

    async def close_issue(self, issue_number: int, repo: str | None = None) -> dict:
        """Close an existing GitHub Issue.

        Args:
            issue_number: Issue number to close.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            Updated issue dict from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.patch(
            f"/repos/{resolved}/issues/{issue_number}",
            json={"state": "closed"},
        )
        response.raise_for_status()
        return response.json()

    async def list_issues(
        self,
        state: str = "open",
        labels: list[str] | None = None,
        repo: str | None = None,
    ) -> list[dict]:
        """List issues in a repository.

        Args:
            state: ``"open"``, ``"closed"``, or ``"all"``.
            labels: Filter by label names.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            List of issue dicts from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        params: dict = {"state": state, "per_page": 100}
        if labels:
            params["labels"] = ",".join(labels)
        response = await self._client.get(f"/repos/{resolved}/issues", params=params)
        response.raise_for_status()
        return response.json()

    async def add_comment(
        self, issue_number: int, body: str, repo: str | None = None
    ) -> dict:
        """Add a comment to an issue or pull request.

        Args:
            issue_number: Issue or PR number.
            body: Comment body (Markdown).
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            Created comment dict from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.post(
            f"/repos/{resolved}/issues/{issue_number}/comments",
            json={"body": body},
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    async def create_pr(
        self,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
        repo: str | None = None,
    ) -> dict:
        """Open a pull request.

        Args:
            title: PR title.
            head: Head branch name.
            base: Base branch name (default: ``"main"``).
            body: PR description (Markdown).
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            Created PR dict from GitHub API.

        TODO: Add draft PR support.
        TODO: Add auto-merge flag.
        """
        resolved = self._resolve_repo(repo)
        payload = {"title": title, "head": head, "base": base, "body": body}
        response = await self._client.post(f"/repos/{resolved}/pulls", json=payload)
        response.raise_for_status()
        return response.json()

    async def merge_pr(
        self,
        pr_number: int,
        merge_method: str = "squash",
        repo: str | None = None,
    ) -> dict:
        """Merge a pull request.

        Args:
            pr_number: PR number to merge.
            merge_method: ``"merge"``, ``"squash"``, or ``"rebase"``.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            Merge result dict from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.put(
            f"/repos/{resolved}/pulls/{pr_number}/merge",
            json={"merge_method": merge_method},
        )
        response.raise_for_status()
        return response.json()

    async def list_prs(
        self,
        state: str = "open",
        base: str | None = None,
        repo: str | None = None,
    ) -> list[dict]:
        """List pull requests in a repository.

        Args:
            state: ``"open"``, ``"closed"``, or ``"all"``.
            base: Filter by base branch name.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            List of PR dicts from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        params: dict = {"state": state, "per_page": 100}
        if base:
            params["base"] = base
        response = await self._client.get(f"/repos/{resolved}/pulls", params=params)
        response.raise_for_status()
        return response.json()

    async def get_pr(self, pr_number: int, repo: str | None = None) -> dict:
        """Fetch a single pull request.

        Args:
            pr_number: PR number.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            PR dict from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.get(f"/repos/{resolved}/pulls/{pr_number}")
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # CI / Check Runs
    # ------------------------------------------------------------------

    async def get_check_status(self, ref: str, repo: str | None = None) -> dict:
        """Get combined CI check status for a git ref.

        Args:
            ref: Git ref (branch, tag, SHA).
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            Combined status dict from GitHub API (``check_suites`` endpoint).
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.get(
            f"/repos/{resolved}/commits/{ref}/check-suites",
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Releases (kept from original stub)
    # ------------------------------------------------------------------

    async def create_release(
        self, tag: str, name: str, body: str = "", repo: str | None = None
    ) -> dict:
        """Create a GitHub Release.

        TODO: Add asset upload support.
        """
        resolved = self._resolve_repo(repo)
        payload = {"tag_name": tag, "name": name, "body": body}
        response = await self._client.post(f"/repos/{resolved}/releases", json=payload)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


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
