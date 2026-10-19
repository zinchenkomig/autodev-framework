"""GitHub integration — REST API client and webhook helpers.

Provides methods for interacting with GitHub repositories: creating issues,
opening pull requests, managing releases, and verifying webhook signatures.

TODO: Implement GitHub App authentication (JWT + installation token).
TODO: Add GraphQL client for complex queries.
TODO: Add retry logic with exponential backoff for rate limit handling.
"""

from __future__ import annotations

import base64
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

    async def add_comment(self, issue_number: int, body: str, repo: str | None = None) -> dict:
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
        commit_title: str | None = None,
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
        payload: dict = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        response = await self._client.put(f"/repos/{resolved}/pulls/{pr_number}/merge", json=payload)
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

    async def get_pr_reviews(self, pr_number: int, repo: str | None = None) -> list[dict]:
        """List all reviews for a pull request.

        Args:
            pr_number: PR number.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            List of review dicts from GitHub API, each containing ``state``
            (``"APPROVED"``, ``"CHANGES_REQUESTED"``, ``"COMMENTED"``, etc.)
            and a ``user`` sub-dict.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.get(
            f"/repos/{resolved}/pulls/{pr_number}/reviews",
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Git refs / branches
    # ------------------------------------------------------------------

    async def get_branch_sha(self, branch: str, repo: str | None = None) -> str:
        """Return the HEAD commit SHA of *branch*.

        Args:
            branch: Branch name (e.g. ``"main"``, ``"develop"``).
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            40-character commit SHA string.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.get(
            f"/repos/{resolved}/git/ref/heads/{branch}",
        )
        response.raise_for_status()
        data = response.json()
        return data["object"]["sha"]

    async def create_ref(
        self,
        ref: str,
        sha: str,
        repo: str | None = None,
    ) -> dict:
        """Create a new Git ref (branch or tag).

        Args:
            ref: Full ref name, e.g. ``"refs/heads/release/1.0.0"``.
            sha: The commit SHA the new ref should point to.
            repo: ``owner/name``. Falls back to *default_repo*.

        Returns:
            Created ref dict from GitHub API.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.post(
            f"/repos/{resolved}/git/refs",
            json={"ref": ref, "sha": sha},
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    async def create_repo(self, full_name: str, *, private: bool = True, description: str = "") -> dict:
        """Create ``owner/name`` with an initial commit on its default branch.

        *owner* is the token's own account or an organization the token can create repos in.
        """
        owner, name = full_name.split("/", 1)
        me = await self._client.get("/user")
        me.raise_for_status()
        path = "/user/repos" if me.json()["login"].lower() == owner.lower() else f"/orgs/{owner}/repos"
        payload = {"name": name, "private": private, "description": description, "auto_init": True}
        response = await self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    async def put_file(self, path: str, content: str, message: str, branch: str, repo: str | None = None) -> str:
        """Create *path* on *branch* in one commit. Returns the commit SHA."""
        resolved = self._resolve_repo(repo)
        payload = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch}
        response = await self._client.put(f"/repos/{resolved}/contents/{path}", json=payload)
        response.raise_for_status()
        return response.json()["commit"]["sha"]

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

    async def get_check_runs(self, ref: str, repo: str | None = None) -> list[dict]:
        """Return individual check-runs for a git ref.

        Each run includes ``name``, ``status``, ``conclusion``, ``html_url``,
        ``started_at`` and ``completed_at`` fields.
        """
        resolved = self._resolve_repo(repo)
        response = await self._client.get(
            f"/repos/{resolved}/commits/{ref}/check-runs",
            params={"per_page": 100},
        )
        response.raise_for_status()
        return response.json().get("check_runs", [])

    async def find_open_pr(self, head: str, base: str, repo: str | None = None) -> dict | None:
        """Return the open PR from branch *head* into *base*, if any."""
        resolved = self._resolve_repo(repo)
        owner = resolved.split("/")[0]
        response = await self._client.get(
            f"/repos/{resolved}/pulls", params={"state": "open", "head": f"{owner}:{head}", "base": base}
        )
        response.raise_for_status()
        prs = response.json()
        return prs[0] if prs else None

    async def close_pr(self, pr_number: int, repo: str | None = None) -> dict:
        resolved = self._resolve_repo(repo)
        response = await self._client.patch(f"/repos/{resolved}/pulls/{pr_number}", json={"state": "closed"})
        response.raise_for_status()
        return response.json()

    async def compare(self, base: str, head: str, repo: str | None = None) -> dict:
        """Compare two refs. ``status`` is ahead / behind / identical / diverged (head relative to base)."""
        resolved = self._resolve_repo(repo)
        response = await self._client.get(f"/repos/{resolved}/compare/{base}...{head}", params={"per_page": 1})
        response.raise_for_status()
        return response.json()

    async def contains_commit(self, ref: str, sha: str, repo: str | None = None) -> bool:
        """True if commit *sha* is part of *ref*'s history."""
        status = (await self.compare(sha, ref, repo)).get("status")
        return status in ("ahead", "identical")

    async def dispatch_workflow(self, workflow: str, ref: str, repo: str | None = None) -> None:
        """Start *workflow* (file name or id) on *ref*; it needs a ``workflow_dispatch`` trigger."""
        resolved = self._resolve_repo(repo)
        response = await self._client.post(
            f"/repos/{resolved}/actions/workflows/{workflow}/dispatches", json={"ref": ref}
        )
        response.raise_for_status()

    async def list_workflow_runs(
        self,
        repo: str | None = None,
        *,
        branch: str | None = None,
        head_sha: str | None = None,
        event: str | None = None,
        per_page: int = 30,
    ) -> list[dict]:
        resolved = self._resolve_repo(repo)
        params: dict = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        if head_sha:
            params["head_sha"] = head_sha
        if event:
            params["event"] = event
        response = await self._client.get(f"/repos/{resolved}/actions/runs", params=params)
        response.raise_for_status()
        return response.json().get("workflow_runs", [])

    # ------------------------------------------------------------------
    # Releases (kept from original stub)
    # ------------------------------------------------------------------

    async def create_release(self, tag: str, name: str, body: str = "", repo: str | None = None) -> dict:
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
