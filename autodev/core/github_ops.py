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


def extract_pr_info(pr_url: str) -> tuple[str, int] | None:
    """Extract repo and PR number from URL like https://github.com/org/repo/pull/123"""
    match = re.match(r"https://github\.com/[^/]+/([^/]+)/pull/(\d+)", pr_url)
    if match:
        return match.group(1), int(match.group(2))
    return None
