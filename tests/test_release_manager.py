"""Tests for ReleaseManagerAgent.

Covers:
- PRInfo / PRGroup / MergeResult dataclass behaviour
- group_by_issue grouping logic
- select_release_set coherent-set selection
- merge_prs merge ordering (backend → frontend)
- compose_release_notes content
- compose_test_plan content
- check_ready threshold
- full run() cycle (happy path and not-ready short-circuit)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from autodev.agents.release_manager import (
    MergeResult,
    PRGroup,
    PRInfo,
    ReleaseManagerAgent,
)
from autodev.core.config import ReleaseConfig, RepoConfig
from autodev.core.events import EventBus, EventTypes

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_pr(
    pr_number: int = 1,
    title: str = "Fix something",
    repo: str = "org/backend",
    branch: str = "feature/fix",
    author: str = "dev1",
    issue_number: int | None = 42,
    pr_type: str = "backend",
    approved: bool = True,
    ci_green: bool = True,
) -> PRInfo:
    return PRInfo(
        pr_number=pr_number,
        title=title,
        repo=repo,
        branch=branch,
        author=author,
        issue_number=issue_number,
        pr_type=pr_type,
        approved=approved,
        ci_green=ci_green,
    )


def make_group(
    issue_number: int = 42,
    issue_title: str = "Some issue",
    prs: list[PRInfo] | None = None,
) -> PRGroup:
    return PRGroup(
        issue_number=issue_number,
        issue_title=issue_title,
        prs=prs or [],
    )


def make_agent(
    min_prs: int = 2,
    repos: list[RepoConfig] | None = None,
    github: MagicMock | None = None,
    event_bus: EventBus | None = None,
) -> ReleaseManagerAgent:
    if repos is None:
        repos = [
            RepoConfig(name="backend", url="org/backend"),
            RepoConfig(name="frontend", url="org/frontend"),
        ]
    if github is None:
        github = MagicMock()
    if event_bus is None:
        event_bus = EventBus()

    config = ReleaseConfig(min_prs=min_prs)
    return ReleaseManagerAgent(
        github=github,
        event_bus=event_bus,
        config=config,
        repos=repos,
    )


# ---------------------------------------------------------------------------
# 1. Dataclass behaviour
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_pr_group_complete_when_both_types_present(self) -> None:
        group = make_group(
            prs=[
                make_pr(pr_type="backend"),
                make_pr(pr_type="frontend"),
            ]
        )
        assert group.complete is True

    def test_pr_group_incomplete_with_only_backend(self) -> None:
        group = make_group(prs=[make_pr(pr_type="backend")])
        assert group.complete is False

    def test_pr_group_incomplete_with_only_frontend(self) -> None:
        group = make_group(prs=[make_pr(pr_type="frontend")])
        assert group.complete is False

    def test_pr_group_has_conflicts_with_duplicate_types(self) -> None:
        group = make_group(
            prs=[
                make_pr(pr_number=1, pr_type="backend"),
                make_pr(pr_number=2, pr_type="backend"),
            ]
        )
        assert group.has_conflicts is True

    def test_pr_group_no_conflicts_with_different_types(self) -> None:
        group = make_group(
            prs=[
                make_pr(pr_type="backend"),
                make_pr(pr_type="frontend"),
            ]
        )
        assert group.has_conflicts is False

    def test_merge_result_defaults_to_success(self) -> None:
        result = MergeResult()
        assert result.success is True
        assert result.merged == []
        assert result.failed == []


# ---------------------------------------------------------------------------
# 2. group_by_issue
# ---------------------------------------------------------------------------


class TestGroupByIssue:
    @pytest.mark.asyncio
    async def test_groups_prs_by_issue_number(self) -> None:
        agent = make_agent()
        agent._get_issue_title = AsyncMock(return_value="Test issue")  # type: ignore[method-assign]

        prs = [
            make_pr(pr_number=1, issue_number=10, pr_type="backend"),
            make_pr(pr_number=2, issue_number=10, pr_type="frontend"),
            make_pr(pr_number=3, issue_number=20, pr_type="backend"),
        ]

        groups = await agent.group_by_issue(prs)

        assert len(groups) == 2
        issue_map = {g.issue_number: g for g in groups}
        assert len(issue_map[10].prs) == 2
        assert len(issue_map[20].prs) == 1

    @pytest.mark.asyncio
    async def test_prs_without_issue_go_to_group_zero(self) -> None:
        agent = make_agent()
        agent._get_issue_title = AsyncMock(return_value="Uncategorized")  # type: ignore[method-assign]

        prs = [make_pr(pr_number=1, issue_number=None)]
        groups = await agent.group_by_issue(prs)

        assert len(groups) == 1
        assert groups[0].issue_number == 0

    @pytest.mark.asyncio
    async def test_empty_prs_returns_empty_groups(self) -> None:
        agent = make_agent()
        groups = await agent.group_by_issue([])
        assert groups == []


# ---------------------------------------------------------------------------
# 3. select_release_set
# ---------------------------------------------------------------------------


class TestSelectReleaseSet:
    @pytest.mark.asyncio
    async def test_excludes_conflicting_groups(self) -> None:
        agent = make_agent()
        conflicting = make_group(
            issue_number=1,
            prs=[
                make_pr(pr_number=1, pr_type="backend"),
                make_pr(pr_number=2, pr_type="backend"),
            ],
        )
        clean = make_group(
            issue_number=2,
            prs=[
                make_pr(pr_number=3, pr_type="frontend"),
            ],
        )

        result = await agent.select_release_set([conflicting, clean])

        assert len(result) == 1
        assert result[0].issue_number == 2

    @pytest.mark.asyncio
    async def test_complete_pairs_sorted_before_incomplete(self) -> None:
        agent = make_agent()
        complete = make_group(
            issue_number=10,
            prs=[
                make_pr(pr_type="backend"),
                make_pr(pr_type="frontend"),
            ],
        )
        incomplete = make_group(
            issue_number=5,
            prs=[make_pr(pr_type="backend")],
        )

        result = await agent.select_release_set([incomplete, complete])

        # complete pair should come first regardless of issue_number ordering
        assert result[0].issue_number == 10
        assert result[1].issue_number == 5

    @pytest.mark.asyncio
    async def test_empty_groups_are_skipped(self) -> None:
        agent = make_agent()
        empty = make_group(issue_number=1, prs=[])
        with_pr = make_group(issue_number=2, prs=[make_pr()])

        result = await agent.select_release_set([empty, with_pr])
        assert len(result) == 1
        assert result[0].issue_number == 2


# ---------------------------------------------------------------------------
# 4. merge_prs — ordering
# ---------------------------------------------------------------------------


class TestMergePRs:
    @pytest.mark.asyncio
    async def test_backend_merged_before_frontend(self) -> None:
        github = MagicMock()
        merge_calls: list[tuple[int, str]] = []

        async def mock_merge(
            pr_number: int, merge_method: str = "squash", repo: str | None = None
        ) -> dict:
            merge_calls.append((pr_number, repo or ""))
            return {"merged": True}

        github.merge_pr = mock_merge
        agent = make_agent(github=github)

        frontend_pr = make_pr(pr_number=1, pr_type="frontend", repo="org/frontend")
        backend_pr = make_pr(pr_number=2, pr_type="backend", repo="org/backend")

        result = await agent.merge_prs([frontend_pr, backend_pr])

        assert result.success is True
        assert len(result.merged) == 2
        # backend PR (#2) must be merged before frontend PR (#1)
        assert merge_calls[0][0] == 2
        assert merge_calls[1][0] == 1

    @pytest.mark.asyncio
    async def test_failed_merge_captured_in_result(self) -> None:
        github = MagicMock()

        async def mock_merge(
            pr_number: int, merge_method: str = "squash", repo: str | None = None
        ) -> dict:
            if pr_number == 99:
                raise RuntimeError("Merge conflict")
            return {"merged": True}

        github.merge_pr = mock_merge
        agent = make_agent(github=github)

        ok_pr = make_pr(pr_number=1, pr_type="backend")
        fail_pr = make_pr(pr_number=99, pr_type="frontend")

        result = await agent.merge_prs([ok_pr, fail_pr])

        assert result.success is False
        assert len(result.merged) == 1
        assert len(result.failed) == 1
        assert result.failed[0].pr_number == 99

    @pytest.mark.asyncio
    async def test_multiple_backends_sorted_by_pr_number(self) -> None:
        github = MagicMock()
        merge_order: list[int] = []

        async def mock_merge(
            pr_number: int, merge_method: str = "squash", repo: str | None = None
        ) -> dict:
            merge_order.append(pr_number)
            return {"merged": True}

        github.merge_pr = mock_merge
        agent = make_agent(github=github)

        prs = [
            make_pr(pr_number=5, pr_type="backend"),
            make_pr(pr_number=3, pr_type="backend"),
            make_pr(pr_number=10, pr_type="frontend"),
        ]

        await agent.merge_prs(prs)
        # Backends first, then frontend; within same type: ordered by pr_number
        assert merge_order == [3, 5, 10]


# ---------------------------------------------------------------------------
# 5. compose_release_notes
# ---------------------------------------------------------------------------


class TestComposeReleaseNotes:
    @pytest.mark.asyncio
    async def test_release_notes_contain_issue_numbers(self) -> None:
        agent = make_agent()
        groups = [
            make_group(
                issue_number=42,
                issue_title="Добавить авторизацию",
                prs=[
                    make_pr(pr_number=10, title="Backend auth", pr_type="backend", author="alice"),
                    make_pr(pr_number=11, title="Frontend login", pr_type="frontend", author="bob"),
                ],
            )
        ]

        notes = await agent.compose_release_notes(groups)

        assert "Issue #42" in notes
        assert "Добавить авторизацию" in notes
        assert "PR #10" in notes
        assert "PR #11" in notes
        assert "@alice" in notes
        assert "@bob" in notes

    @pytest.mark.asyncio
    async def test_release_notes_in_russian(self) -> None:
        agent = make_agent()
        groups = [make_group(prs=[make_pr()])]

        notes = await agent.compose_release_notes(groups)

        assert "Примечания к релизу" in notes
        assert "Изменения" in notes
        assert "Статистика" in notes

    @pytest.mark.asyncio
    async def test_release_notes_stats_are_correct(self) -> None:
        agent = make_agent()
        groups = [
            make_group(
                issue_number=1,
                prs=[
                    make_pr(pr_type="backend"),
                    make_pr(pr_type="frontend"),
                ],
            ),
            make_group(
                issue_number=2,
                prs=[make_pr(pr_type="backend")],
            ),
        ]

        notes = await agent.compose_release_notes(groups)

        assert "Всего задач: 2" in notes
        assert "Полных пар (бэкенд + фронтенд): 1" in notes
        assert "Всего PR: 3" in notes


# ---------------------------------------------------------------------------
# 6. compose_test_plan
# ---------------------------------------------------------------------------


class TestComposeTestPlan:
    @pytest.mark.asyncio
    async def test_test_plan_in_russian(self) -> None:
        agent = make_agent()
        groups = [make_group(prs=[make_pr()])]

        plan = await agent.compose_test_plan(groups)

        assert "План ручного тестирования" in plan
        assert "Тест-кейсы" in plan

    @pytest.mark.asyncio
    async def test_test_plan_contains_pr_references(self) -> None:
        agent = make_agent()
        groups = [
            make_group(
                issue_number=7,
                issue_title="Оплата",
                prs=[make_pr(pr_number=55, title="Payment integration", pr_type="backend")],
            )
        ]

        plan = await agent.compose_test_plan(groups)

        assert "PR #55" in plan
        assert "Payment integration" in plan

    @pytest.mark.asyncio
    async def test_test_plan_contains_common_checks(self) -> None:
        agent = make_agent()
        groups = [make_group(prs=[make_pr()])]

        plan = await agent.compose_test_plan(groups)

        assert "Smoke-тест" in plan


# ---------------------------------------------------------------------------
# 7. check_ready
# ---------------------------------------------------------------------------


class TestCheckReady:
    @pytest.mark.asyncio
    async def test_returns_true_when_enough_prs(self) -> None:
        agent = make_agent(min_prs=2)
        agent.collect_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=[make_pr(pr_number=1), make_pr(pr_number=2)]
        )

        assert await agent.check_ready() is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_enough_prs(self) -> None:
        agent = make_agent(min_prs=5)
        agent.collect_prs = AsyncMock(return_value=[make_pr()])  # type: ignore[method-assign]

        assert await agent.check_ready() is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_prs(self) -> None:
        agent = make_agent(min_prs=1)
        agent.collect_prs = AsyncMock(return_value=[])  # type: ignore[method-assign]

        assert await agent.check_ready() is False


# ---------------------------------------------------------------------------
# 8. Full run() cycle
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_run_aborts_when_not_ready(self) -> None:
        agent = make_agent()
        agent.check_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        agent.collect_prs = AsyncMock()  # type: ignore[method-assign]

        await agent.run()

        agent.collect_prs.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_emits_release_ready_event(self) -> None:
        event_bus = EventBus()
        received_events: list[dict] = []

        async def capture(event: object) -> None:
            from autodev.core.models import Event
            if isinstance(event, Event):
                received_events.append(event.payload)

        event_bus.subscribe(EventTypes.RELEASE_READY, capture)

        github = MagicMock()
        github.merge_pr = AsyncMock(return_value={"merged": True})
        github.create_pr = AsyncMock(return_value={"number": 99, "html_url": "https://github.com/org/backend/pull/99"})
        github.get_branch_sha = AsyncMock(return_value="abc123sha")
        github.create_ref = AsyncMock(return_value={"ref": "refs/heads/release/2025.01.01"})

        agent = make_agent(min_prs=1, event_bus=event_bus, github=github)

        prs = [make_pr(pr_number=10, pr_type="backend", issue_number=1)]
        groups = [make_group(issue_number=1, prs=prs)]

        agent.check_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        agent.collect_prs = AsyncMock(return_value=prs)  # type: ignore[method-assign]
        agent.group_by_issue = AsyncMock(return_value=groups)  # type: ignore[method-assign]
        agent.select_release_set = AsyncMock(return_value=groups)  # type: ignore[method-assign]

        await agent.run()

        assert len(received_events) == 1
        payload = received_events[0]
        assert "version" in payload
        assert payload["prs_merged"] == 1
        assert payload["groups_count"] == 1
