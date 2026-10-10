"""Per-task git checkout."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from autodev.core import shell

# Build/test junk that must never end up in an agent's commit, even if the
# repo's .gitignore forgets it.
LOCAL_EXCLUDES = [
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".venv/",
    "node_modules/",
    ".next/",
    "coverage/",
    ".coverage",
    "playwright-report/",
    "test-results/",
]


def branch_name(ticket: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    return f"autodev/{ticket}-{slug}" if slug else f"autodev/{ticket}"


class Workspace:
    """A fresh clone of one repo for one task at ``<root>/tasks/<task_id>``.

    The path is stable per task so a resumed Claude session (which is keyed by
    its working directory) finds its history again.
    """

    def __init__(self, root: str, task_id: str, repo: str, env: dict[str, str]) -> None:
        self.path = str(Path(root) / "tasks" / task_id)
        self.repo = repo
        self.env = env
        self.url = f"https://github.com/{repo}.git"

    async def git(self, *args: str, check: bool = True, timeout: float = 120) -> str:
        return await shell.run("git", *args, cwd=self.path, env=self.env, check=check, timeout=timeout)

    async def prepare(self, base: str, branch: str, existing: bool) -> None:
        """Clone and check out *branch*: the existing remote branch, or a new one from *base*."""
        self.cleanup()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        start = branch if existing else base
        await shell.run(
            "git", "clone", "--filter=blob:none", "-b", start, self.url, self.path, env=self.env, timeout=600
        )
        exclude = Path(self.path, ".git", "info", "exclude")
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as f:
            f.write("\n".join(LOCAL_EXCLUDES) + "\n")
        if existing:
            await self.git("fetch", "origin", base)
        else:
            await self.git("checkout", "-b", branch)

    async def merge_base(self, base: str) -> bool:
        """Merge origin/<base> into the branch. Returns False if it left conflicts."""
        out = await self.git("merge", "--no-edit", f"origin/{base}", check=False)
        return "CONFLICT" not in out and "Automatic merge failed" not in out

    async def run_setup(self, script: str) -> str:
        env = {**self.env, "AUTODEV_WORKDIR": self.path}
        return await shell.sh(script, cwd=self.path, env=env, timeout=1200)

    async def commit_leftovers(self, message: str) -> bool:
        """Commit anything the agent left uncommitted. Returns True if a commit was made."""
        if not (await self.git("status", "--porcelain")).strip():
            return False
        await self.git("add", "-A")
        await self.git("commit", "-m", message)
        return True

    async def commits_ahead(self, base: str) -> int:
        return int((await self.git("rev-list", "--count", f"origin/{base}..HEAD")).strip() or 0)

    async def in_merge(self) -> bool:
        return Path(self.path, ".git", "MERGE_HEAD").exists()

    async def push(self, branch: str) -> None:
        await self.git("push", "--force-with-lease", "-u", "origin", f"HEAD:refs/heads/{branch}", timeout=300)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
