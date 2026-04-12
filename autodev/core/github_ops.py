"""GitHub operations for release management."""

import os
import re
import subprocess
import tempfile

import httpx

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = "zinchenkomig"


def _repo_name(repo: str) -> str:
    """Extract bare repo name, stripping org prefix if present."""
    return repo.split("/")[-1] if "/" in repo else repo


async def merge_pr(repo: str, pr_number: int) -> bool:
    """Merge a PR via GitHub API."""
    repo = _repo_name(repo)
    url = f"https://api.github.com/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}/merge"
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            url,
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={"merge_method": "squash"},
        )
        return resp.status_code == 200


async def create_stage_to_main_pr(repo: str, version: str) -> dict | None:
    """Create a PR from stage to main for a release.

    Returns ``{"repo": ..., "pr_number": ..., "pr_url": ...}`` on success,
    or ``None`` if the PR could not be created.
    """
    repo = _repo_name(repo)
    url = f"https://api.github.com/repos/{GITHUB_ORG}/{repo}/pulls"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={
                "title": f"Release {version}: stage → main",
                "head": "stage",
                "base": "main",
                "body": (
                    f"Автоматический релизный PR для версии **{version}**.\n\nСоздан autodev-framework Release Manager."
                ),
            },
            timeout=30.0,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {
                "repo": repo,
                "pr_number": data["number"],
                "pr_url": data["html_url"],
            }

        # 422 usually means PR already exists — find the existing one
        if resp.status_code == 422:
            existing = await client.get(
                url,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                },
                params={"state": "open", "head": f"{GITHUB_ORG}:stage", "base": "main"},
                timeout=15.0,
            )
            if existing.status_code == 200:
                prs = existing.json()
                if prs:
                    pr = prs[0]
                    return {
                        "repo": repo,
                        "pr_number": pr["number"],
                        "pr_url": pr["html_url"],
                    }

        return None


async def merge_release_pr(repo: str, pr_number: int) -> bool:
    """Merge a release PR (stage→main) for production deploy."""
    return await merge_pr(_repo_name(repo), pr_number)


async def revert_pr_merge(repo: str, pr_number: int) -> dict:
    """Revert a merged PR on develop branch via GitHub API.

    Creates a revert commit on develop that undoes the PR merge.
    Returns {"success": bool, "revert_sha": str | None, "error": str | None}.
    """
    repo = _repo_name(repo)
    # First, get the merge commit SHA from the PR
    async with httpx.AsyncClient() as client:
        # Get PR details to find merge commit
        resp = await client.get(
            f"https://api.github.com/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            return {
                "success": False,
                "revert_sha": None,
                "error": f"Failed to get PR: {resp.status_code}",
            }

        pr_data = resp.json()
        merge_commit_sha = pr_data.get("merge_commit_sha")
        if not merge_commit_sha:
            return {"success": False, "revert_sha": None, "error": "PR has no merge commit"}
        if pr_data.get("state") != "closed" or not pr_data.get("merged"):
            return {"success": False, "revert_sha": None, "error": "PR is not merged"}

    # Use git to revert the merge commit on develop
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_ORG}/{repo}.git"
        try:
            subprocess.run(
                ["git", "clone", "--branch", "stage", clone_url, tmpdir],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.email", "autodev@bot"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.name", "AutoDev Bot"],
                check=True,
                capture_output=True,
            )
            # Revert the merge commit (parent 1 = develop, parent 2 = feature branch)
            result = subprocess.run(
                ["git", "-C", tmpdir, "revert", "-m", "1", "--no-edit", merge_commit_sha],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return {
                    "success": False,
                    "revert_sha": None,
                    "error": f"git revert failed: {result.stderr.strip()}",
                }
            # Get the revert commit SHA
            sha_result = subprocess.run(
                ["git", "-C", tmpdir, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            revert_sha = sha_result.stdout.strip()
            # Push
            subprocess.run(
                ["git", "-C", tmpdir, "push", "origin", "stage"],
                check=True,
                capture_output=True,
            )
            return {"success": True, "revert_sha": revert_sha, "error": None}
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "revert_sha": None,
                "error": f"Git error: {e.stderr.decode() if isinstance(e.stderr, bytes) else str(e)}",
            }


def extract_pr_info(pr_url: str) -> tuple[str, int] | None:
    """Extract repo and PR number from URL like https://github.com/org/repo/pull/123"""
    match = re.match(r"https://github\.com/[^/]+/([^/]+)/pull/(\d+)", pr_url)
    if match:
        return match.group(1), int(match.group(2))
    return None
