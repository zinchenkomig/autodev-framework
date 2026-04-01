"""GitHub operations for release management."""
import os
import re
import subprocess
import tempfile

import httpx

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = "zinchenkomig"


async def merge_pr(repo: str, pr_number: int) -> bool:
    """Merge a PR via GitHub API."""
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


async def merge_develop_to_main(repo: str) -> bool:
    """Merge develop branch into main."""
    # Use git directly for branch merge
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_ORG}/{repo}.git"
        try:
            subprocess.run(
                ["git", "clone", clone_url, tmpdir], check=True, capture_output=True
            )
            subprocess.run(
                ["git", "-C", tmpdir, "checkout", "main"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    tmpdir,
                    "merge",
                    "origin/develop",
                    "-m",
                    "Release: merge develop into main",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "push", "origin", "main"],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False


async def revert_pr_merge(repo: str, pr_number: int) -> dict:
    """Revert a merged PR on develop branch via GitHub API.
    
    Creates a revert commit on develop that undoes the PR merge.
    Returns {"success": bool, "revert_sha": str | None, "error": str | None}.
    """
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
            return {"success": False, "revert_sha": None, "error": f"Failed to get PR: {resp.status_code}"}
        
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
                ["git", "clone", "--branch", "develop", clone_url, tmpdir],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.email", "autodev@bot"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.name", "AutoDev Bot"],
                check=True, capture_output=True,
            )
            # Revert the merge commit (parent 1 = develop, parent 2 = feature branch)
            result = subprocess.run(
                ["git", "-C", tmpdir, "revert", "-m", "1", "--no-edit", merge_commit_sha],
                capture_output=True, text=True,
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
                capture_output=True, text=True, check=True,
            )
            revert_sha = sha_result.stdout.strip()
            # Push
            subprocess.run(
                ["git", "-C", tmpdir, "push", "origin", "develop"],
                check=True, capture_output=True,
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
