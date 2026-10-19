"""Test doubles."""

from __future__ import annotations

import httpx


class FakeGitHub:
    """In-memory stand-in for GitHubClient (only what the worker uses)."""

    def __init__(self) -> None:
        self.prs: dict[int, dict] = {}
        self.check_runs: dict[str, list[dict]] = {}
        self.workflow_runs: list[dict] = []
        self.ancestry: set[tuple[str, str]] = set()  # (ref, sha): ref contains sha
        self.ahead_by: dict[str, int] = {}
        self.merged: list[tuple[int, str]] = []
        self.merge_error: int | None = None
        self.next_number = 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def add_pr(self, head_sha: str = "head1", **kw) -> dict:
        number = kw.pop("number", self.next_number)
        self.next_number = max(self.next_number, number + 1)
        pr = {
            "number": number,
            "html_url": f"https://github.com/acme/shop/pull/{number}",
            "state": "open",
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "head": {"sha": head_sha},
            **kw,
        }
        self.prs[number] = pr
        return pr

    async def create_pr(self, title, head, base="main", body="", repo=None):
        return self.add_pr(title=title, head_ref=head, base_ref=base, body=body, repo=repo)

    async def find_open_pr(self, head, base, repo=None):
        return next((p for p in self.prs.values() if p.get("head_ref") == head and p["state"] == "open"), None)

    async def get_pr(self, number, repo=None):
        return self.prs[number]

    async def get_check_runs(self, ref, repo=None):
        return self.check_runs.get(ref, [])

    async def merge_pr(self, number, merge_method="squash", repo=None, commit_title=None):
        if self.merge_error:
            request = httpx.Request("PUT", "https://api.github.com/x")
            raise httpx.HTTPStatusError(
                "nope", request=request, response=httpx.Response(self.merge_error, text="blocked", request=request)
            )
        self.merged.append((number, merge_method))
        self.prs[number].update(merged=True, state="closed", merge_commit_sha=f"merge{number}")
        return {"sha": f"merge{number}", "merged": True}

    async def dispatch_workflow(self, workflow, ref, repo=None):
        self.dispatched = [*getattr(self, "dispatched", []), (repo, workflow, ref)]

    async def compare(self, base, head, repo=None):
        return {"ahead_by": self.ahead_by.get(repo or "", 0), "status": "ahead"}

    async def contains_commit(self, ref, sha, repo=None):
        return ref == sha or (ref, sha) in self.ancestry

    async def list_workflow_runs(self, repo=None, *, branch=None, head_sha=None, event=None, per_page=30):
        return self.workflow_runs


def run(
    name: str, status: str = "completed", conclusion: str | None = "success", started: str = "2026-01-01T00:00:00Z"
) -> dict:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started,
        "html_url": f"https://ci/{name}",
    }
