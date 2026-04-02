"""Release Manager agent — versioning, changelogs, and deployments.

Monitors completed tasks, determines when a release is ready, creates
GitHub releases, and coordinates deployment pipelines.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from autodev.core.config import ReleaseConfig, RepoConfig
from autodev.core.events import EventBus, EventTypes
from autodev.integrations.github import GitHubClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PRInfo:
    """Information about a pull request ready for release consideration.

    Attributes:
        pr_number: GitHub PR number.
        title: PR title.
        repo: Repository in ``owner/name`` format.
        branch: Head branch name.
        author: GitHub login of the PR author.
        issue_number: Associated issue number (None if unknown).
        pr_type: ``"backend"`` or ``"frontend"`` classification.
        labels: List of label names applied to the PR.
        approved: True if the PR has at least one approving review with no
            outstanding change requests.
        ci_green: True if all CI check suites passed.
        body: PR description (Markdown).
    """

    pr_number: int
    title: str
    repo: str
    branch: str
    author: str
    issue_number: int | None = None
    pr_type: str = "backend"  # "backend" or "frontend"
    labels: list[str] = field(default_factory=list)
    approved: bool = False
    ci_green: bool = False
    body: str = ""


@dataclass
class PRGroup:
    """A group of PRs associated with a single GitHub issue.

    Attributes:
        issue_number: The GitHub issue number (0 = uncategorised).
        issue_title: Human-readable issue title.
        prs: All :class:`PRInfo` objects in this group.
    """

    issue_number: int
    issue_title: str
    prs: list[PRInfo] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when the group contains both a backend *and* frontend PR."""
        types = {pr.pr_type for pr in self.prs}
        return "backend" in types and "frontend" in types

    @property
    def has_conflicts(self) -> bool:
        """True when multiple PRs of the same type exist in the group."""
        types = [pr.pr_type for pr in self.prs]
        return len(types) != len(set(types))


@dataclass
class MergeResult:
    """Outcome of a batch PR merge operation.

    Attributes:
        merged: PRs that were merged successfully.
        failed: PRs that could not be merged.
        success: True if every PR was merged without error.
        message: Human-readable summary.
    """

    merged: list[PRInfo] = field(default_factory=list)
    failed: list[PRInfo] = field(default_factory=list)
    success: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# ReleaseManagerAgent
# ---------------------------------------------------------------------------


class ReleaseManagerAgent:
    """Autonomous Release Manager agent.

    Orchestrates the full release lifecycle:

    1. Checks release readiness (enough approved/green PRs).
    2. Collects approved/green PRs from all configured repos.
    3. Groups PRs by associated GitHub issue.
    4. Selects a coherent, conflict-free release set.
    5. Merges PRs in the correct order (backend → frontend).
    6. Creates a ``release/{version}`` branch and PR to ``main``.
    7. Generates Russian-language release notes and a manual test plan.
    8. Emits the ``release.ready`` domain event.

    Args:
        github: An authenticated :class:`GitHubClient`.
        event_bus: Shared :class:`EventBus` for publishing domain events.
        config: Release strategy configuration (:class:`ReleaseConfig`).
        repos: List of repository configurations (:class:`RepoConfig`).
    """

    role = "release_manager"

    def __init__(
        self,
        github: GitHubClient,
        event_bus: EventBus,
        config: ReleaseConfig,
        repos: list[RepoConfig],
    ) -> None:
        self.github = github
        self.event_bus = event_bus
        self.config = config
        self.repos = repos

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_ready(self) -> bool:
        """Return True if the number of release-ready PRs meets the minimum.

        The minimum is defined by :attr:`ReleaseConfig.min_prs`.
        """
        prs = await self.collect_prs()
        ready = len(prs) >= self.config.min_prs
        logger.info(
            "[release_manager] check_ready: %d ready PRs (min=%d) → %s",
            len(prs),
            self.config.min_prs,
            ready,
        )
        return ready

    async def collect_prs(self) -> list[PRInfo]:
        """Collect approved and CI-green open PRs from all configured repos."""
        result: list[PRInfo] = []

        for repo in self.repos:
            try:
                raw_prs = await self.github.list_prs(state="open", repo=repo.url)
                for pr_data in raw_prs:
                    pr_info = await self._build_pr_info(pr_data, repo)
                    if pr_info.approved and pr_info.ci_green:
                        result.append(pr_info)
            except Exception as exc:
                logger.warning(
                    "[release_manager] Failed to collect PRs from %s: %s",
                    repo.url,
                    exc,
                )

        logger.info("[release_manager] Collected %d ready PRs total", len(result))
        return result

    async def group_by_issue(self, prs: list[PRInfo]) -> list[PRGroup]:
        """Group a list of PRs by their associated GitHub issue number.

        PRs without a linked issue are placed under issue ``0`` (uncategorised).
        """
        groups: dict[int, PRGroup] = {}

        for pr in prs:
            issue_num = pr.issue_number or 0
            if issue_num not in groups:
                issue_title = await self._get_issue_title(issue_num, pr.repo)
                groups[issue_num] = PRGroup(
                    issue_number=issue_num,
                    issue_title=issue_title,
                )
            groups[issue_num].prs.append(pr)

        result = list(groups.values())
        logger.info(
            "[release_manager] Grouped %d PRs into %d groups",
            len(prs),
            len(result),
        )
        return result

    async def select_release_set(self, groups: list[PRGroup]) -> list[PRGroup]:
        """Select a coherent, conflict-free subset of groups for release.

        A group is excluded if it contains multiple PRs of the same type
        (e.g. two backend PRs for the same issue), as this indicates
        unresolved ambiguity.

        Complete pairs (backend **and** frontend) are included first;
        single-type groups are still included as long as they have no
        internal conflicts.
        """
        coherent: list[PRGroup] = []

        for group in groups:
            if not group.prs:
                continue
            if group.has_conflicts:
                logger.warning(
                    "[release_manager] Skipping group for issue #%d — conflicting PR types",
                    group.issue_number,
                )
                continue
            coherent.append(group)

        # Sort: complete pairs first, then incomplete, stable by issue number
        coherent.sort(key=lambda g: (0 if g.complete else 1, g.issue_number))

        logger.info(
            "[release_manager] Selected %d/%d groups for release set",
            len(coherent),
            len(groups),
        )
        return coherent

    async def merge_prs(self, prs: list[PRInfo]) -> MergeResult:
        """Merge PRs using squash strategy: backend first, then frontend.

        The ordering guarantees that backend API changes land before the
        frontend clients that depend on them.
        """
        ordered = sorted(
            prs,
            key=lambda p: (0 if p.pr_type == "backend" else 1, p.pr_number),
        )

        merged: list[PRInfo] = []
        failed: list[PRInfo] = []

        for pr in ordered:
            try:
                await self.github.merge_pr(
                    pr.pr_number,
                    merge_method="squash",
                    repo=pr.repo,
                )
                merged.append(pr)
                logger.info(
                    "[release_manager] Merged PR #%d (%s) from %s",
                    pr.pr_number,
                    pr.pr_type,
                    pr.repo,
                )
            except Exception as exc:
                failed.append(pr)
                logger.error(
                    "[release_manager] Failed to merge PR #%d from %s: %s",
                    pr.pr_number,
                    pr.repo,
                    exc,
                )

        success = len(failed) == 0
        message = f"Merged {len(merged)} PRs successfully" if success else f"Merged {len(merged)}, failed {len(failed)}"
        return MergeResult(merged=merged, failed=failed, success=success, message=message)

    async def create_release_branch(self, version: str) -> dict:
        """Create a ``release/{version}`` branch and open a PR to ``main``.

        Returns a dict with keys:
        - ``branch_name``: The new branch name.
        - ``repo``: Repository where the branch was created.
        - ``pr_number``: Number of the opened PR.
        - ``pr_url``: HTML URL of the PR.
        """
        branch_name = f"release/{version}"
        primary_repo = self._get_primary_repo()

        # Branch off stage for releases.
        base_branch = "stage"

        try:
            sha = await self.github.get_branch_sha(base_branch, repo=primary_repo)
        except Exception:
            sha = await self.github.get_branch_sha("main", repo=primary_repo)

        await self.github.create_ref(
            ref=f"refs/heads/{branch_name}",
            sha=sha,
            repo=primary_repo,
        )

        now_str = datetime.now(UTC).strftime("%Y-%m-%d")
        pr = await self.github.create_pr(
            title=f"Release {version} — {now_str}",
            head=branch_name,
            base="main",
            body=(f"Автоматический релизный PR для версии **{version}**.\n\nСоздан агентом ReleaseManagerAgent."),
            repo=primary_repo,
        )

        result = {
            "branch_name": branch_name,
            "repo": primary_repo,
            "pr_number": pr.get("number"),
            "pr_url": pr.get("html_url", ""),
        }
        logger.info(
            "[release_manager] Created release branch %s, PR #%s",
            branch_name,
            pr.get("number"),
        )
        return result

    async def compose_release_notes(self, groups: list[PRGroup]) -> str:
        """Generate Russian-language release notes from PR groups."""
        today = datetime.now(UTC).strftime("%d.%m.%Y")
        lines: list[str] = [
            "# Примечания к релизу",
            "",
            f"Дата: {today}",
            "",
            "## Изменения",
            "",
        ]

        for group in groups:
            heading = (
                "Прочие изменения" if group.issue_number == 0 else f"Issue #{group.issue_number}: {group.issue_title}"
            )
            lines.append(f"### {heading}")
            for pr in group.prs:
                type_label = "бэкенд" if pr.pr_type == "backend" else "фронтенд"
                lines.append(f"- [{type_label}] {pr.title} (PR #{pr.pr_number}, автор: @{pr.author})")
            lines.append("")

        total_prs = sum(len(g.prs) for g in groups)
        complete_groups = sum(1 for g in groups if g.complete)
        lines.extend(
            [
                "## Статистика",
                "",
                f"- Всего задач: {len(groups)}",
                f"- Полных пар (бэкенд + фронтенд): {complete_groups}",
                f"- Всего PR: {total_prs}",
            ]
        )

        return "\n".join(lines)

    async def compose_test_plan(self, groups: list[PRGroup]) -> str:
        """Generate a Russian-language manual test plan from PR groups."""
        today = datetime.now(UTC).strftime("%d.%m.%Y")
        lines: list[str] = [
            "# План ручного тестирования",
            "",
            f"Дата: {today}",
            "",
            "## Тест-кейсы",
            "",
        ]

        for i, group in enumerate(groups, 1):
            heading = (
                "Прочие изменения" if group.issue_number == 0 else f"Issue #{group.issue_number}: {group.issue_title}"
            )
            lines.extend(
                [
                    f"### {i}. {heading}",
                    "",
                    "**Предусловия:**",
                    "- Окружение staging развёрнуто и доступно",
                    "- Пользователь авторизован в системе",
                    "",
                    "**Шаги тестирования:**",
                ]
            )

            step = 1
            for pr in group.prs:
                type_label = "бэкенд" if pr.pr_type == "backend" else "фронтенд"
                lines.append(f"{step}. Проверить изменения PR #{pr.pr_number} ({type_label}): {pr.title}")
                step += 1

            lines.extend(
                [
                    f"{step}. Убедиться в отсутствии регрессий в смежных функциях",
                    "",
                    "**Ожидаемый результат:**",
                    "- Функциональность работает согласно требованиям задачи",
                    "- Отсутствуют ошибки в консоли браузера и серверных логах",
                    "",
                ]
            )

        lines.extend(
            [
                "## Общие проверки",
                "",
                "- [ ] Smoke-тест основных пользовательских сценариев",
                "- [ ] Проверка производительности (время загрузки страниц < 2 сек)",
                "- [ ] Проверка на мобильных устройствах (для UI-изменений)",
                "- [ ] Проверка совместимости с предыдущими версиями API",
                "- [ ] Контроль уровня ошибок в Sentry после деплоя",
            ]
        )

        return "\n".join(lines)

    async def run(self) -> None:
        """Execute the full release cycle end-to-end.

        Steps (with early-exit conditions):

        1. :meth:`check_ready` — abort if not enough PRs are ready.
        2. :meth:`collect_prs` — gather approved/green PRs.
        3. :meth:`group_by_issue` — group by linked issue.
        4. :meth:`select_release_set` — filter conflicting groups.
        5. :meth:`merge_prs` — merge backend-first, then frontend.
        6. :meth:`create_release_branch` — create release branch + PR.
        7. :meth:`compose_release_notes` — generate release notes.
        8. :meth:`compose_test_plan` — generate test plan.
        9. Emit ``release.ready`` domain event.
        """
        logger.info("[release_manager] Starting release cycle")

        if not await self.check_ready():
            logger.info("[release_manager] Not enough PRs ready — aborting")
            return

        prs = await self.collect_prs()
        groups = await self.group_by_issue(prs)
        selected = await self.select_release_set(groups)

        if not selected:
            logger.info("[release_manager] No coherent groups to release")
            return

        all_prs = [pr for group in selected for pr in group.prs]
        merge_result = await self.merge_prs(all_prs)

        if not merge_result.success:
            logger.warning("[release_manager] Some merges failed: %s", merge_result.message)

        version = self._generate_version()

        try:
            branch_info = await self.create_release_branch(version)
        except Exception as exc:
            logger.error("[release_manager] Failed to create release branch: %s", exc)
            branch_info = {"branch_name": f"release/{version}", "pr_url": "", "pr_number": None}

        release_notes = await self.compose_release_notes(selected)
        test_plan = await self.compose_test_plan(selected)

        await self.event_bus.emit(
            EventTypes.RELEASE_READY,
            payload={
                "version": version,
                "branch": branch_info.get("branch_name"),
                "pr_url": branch_info.get("pr_url", ""),
                "groups_count": len(selected),
                "prs_merged": len(merge_result.merged),
                "prs_failed": len(merge_result.failed),
                "release_notes": release_notes,
                "test_plan": test_plan,
            },
            source=self.role,
        )

        logger.info("[release_manager] Release cycle complete — version %s", version)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _build_pr_info(self, pr_data: dict, repo: RepoConfig) -> PRInfo:
        """Construct a :class:`PRInfo` from a raw GitHub API PR dict."""
        pr_number = pr_data["number"]

        issue_number = self._extract_issue_number(
            pr_data.get("body") or "",
            pr_data.get("title") or "",
        )

        raw_labels: list[dict] = pr_data.get("labels", [])
        pr_type = self._determine_pr_type(repo.name, raw_labels)

        approved = await self._check_approved(pr_number, repo.url)

        head_sha: str = (pr_data.get("head") or {}).get("sha", "")
        ci_green = await self._check_ci(head_sha, repo.url) if head_sha else False

        return PRInfo(
            pr_number=pr_number,
            title=pr_data.get("title") or "",
            repo=repo.url,
            branch=(pr_data.get("head") or {}).get("ref", ""),
            author=(pr_data.get("user") or {}).get("login", ""),
            issue_number=issue_number,
            pr_type=pr_type,
            labels=[lbl.get("name", "") for lbl in raw_labels],
            approved=approved,
            ci_green=ci_green,
            body=pr_data.get("body") or "",
        )

    def _extract_issue_number(self, body: str, title: str) -> int | None:
        """Parse a linked issue number from PR body/title text.

        Recognises patterns:
        - ``Closes #123``, ``Fixes #123``, ``Resolves #123``, ``Refs #123``
        - ``(#123)``
        - Plain ``#123``
        """
        patterns = [
            r"(?:closes?|fixes?|resolves?|refs?)\s+#(\d+)",
            r"\(#(\d+)\)",
            r"#(\d+)",
        ]
        for text in (body, title):
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return int(match.group(1))
        return None

    def _determine_pr_type(self, repo_name: str, labels: list[dict]) -> str:
        """Return ``"frontend"`` or ``"backend"`` based on repo name and labels."""
        name_lower = repo_name.lower()
        if any(kw in name_lower for kw in ("frontend", "ui", "web", "client")):
            return "frontend"

        label_names = {(lbl.get("name") or "").lower() for lbl in labels}
        if label_names & {"frontend", "ui", "client"}:
            return "frontend"

        return "backend"

    async def _check_approved(self, pr_number: int, repo: str) -> bool:
        """Return True if a PR has approving reviews with no pending changes requested."""
        try:
            reviews: list[dict] = await self.github.get_pr_reviews(pr_number, repo=repo)
            approved_logins: set[str] = set()
            changes_requested: set[str] = set()

            for review in reviews:
                login: str = (review.get("user") or {}).get("login", "")
                state: str = review.get("state", "")
                if state == "APPROVED":
                    approved_logins.add(login)
                    changes_requested.discard(login)
                elif state == "CHANGES_REQUESTED":
                    changes_requested.add(login)
                    approved_logins.discard(login)

            return bool(approved_logins) and not changes_requested
        except Exception as exc:
            logger.warning(
                "[release_manager] Could not check reviews for PR #%d: %s",
                pr_number,
                exc,
            )
            return False

    async def _check_ci(self, ref: str, repo: str) -> bool:
        """Return True if all CI check suites for *ref* have passed."""
        try:
            status = await self.github.get_check_status(ref, repo=repo)
            suites: list[dict] = status.get("check_suites", [])
            if not suites:
                return True  # No checks configured — treat as passing
            return all(
                suite.get("conclusion") in ("success", "skipped", None) and suite.get("status") == "completed"
                for suite in suites
            )
        except Exception as exc:
            logger.warning(
                "[release_manager] Could not check CI for ref %s: %s",
                ref,
                exc,
            )
            return False

    async def _get_issue_title(self, issue_number: int, repo: str) -> str:
        """Fetch the title of a GitHub issue, falling back to a placeholder."""
        if issue_number == 0:
            return "Uncategorized"
        try:
            issues: list[dict] = await self.github.list_issues(state="all", repo=repo)
            for issue in issues:
                if issue.get("number") == issue_number:
                    return issue.get("title") or f"Issue #{issue_number}"
        except Exception:
            pass
        return f"Issue #{issue_number}"

    def _get_primary_repo(self) -> str:
        """Return the primary (backend) repo URL, or the first configured repo."""
        for repo in self.repos:
            if "backend" in repo.name.lower():
                return repo.url
        return self.repos[0].url if self.repos else ""

    def _generate_version(self) -> str:
        """Generate a CalVer-style version string: ``YYYY.MM.DD``."""
        now = datetime.now(UTC)
        return f"{now.year}.{now.month:02d}.{now.day:02d}"
