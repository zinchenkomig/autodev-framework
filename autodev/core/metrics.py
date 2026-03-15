"""Metrics and analytics for the AutoDev Framework.

Provides cost, speed, and quality metrics collected from the database,
aggregated over configurable time periods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text

from autodev.core.models import Agent, AgentRun, AgentRunStatus, Task, TaskStatus

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DailyMetric:
    """A single day's aggregated metric value."""

    date: str          # ISO-8601 date string, e.g. "2026-03-15"
    value: float       # numeric metric value for that day


@dataclass
class CostSummary:
    """Aggregated cost metrics over a period."""

    total_cost_usd: float
    cost_by_agent: dict[str, float]        # agent_id → total USD
    cost_by_day: list[DailyMetric]         # daily spend
    total_tokens: int
    avg_cost_per_task: float
    period_days: int


@dataclass
class SpeedMetrics:
    """Aggregated speed / throughput metrics over a period."""

    avg_issue_to_pr_hours: float           # avg hours from task creation to PR
    avg_pr_to_merge_hours: float           # avg hours from PR to task done
    throughput_tasks_per_day: float        # completed tasks per day
    tasks_completed: int
    period_days: int
    daily_throughput: list[DailyMetric]    # completed tasks per day over period


@dataclass
class QualityMetrics:
    """Aggregated quality metrics over a period."""

    agent_success_rate: float              # fraction of runs that succeeded
    bugs_found_by_tester: int             # FAILED runs by tester agents
    code_churn: int                        # total tasks that were re-run (>1 run)
    total_runs: int
    failed_runs: int
    period_days: int
    success_rate_by_agent: dict[str, float]   # agent_id → success_rate


@dataclass
class AgentStats:
    """Statistics for a specific agent."""

    agent_id: str
    role: str
    status: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    avg_duration_seconds: float
    total_cost_usd: float
    total_tokens: int
    last_run_at: str | None


@dataclass
class DashboardStats:
    """Summary statistics for the main dashboard page."""

    total_cost_usd: float
    cost_this_month: float
    avg_task_duration_hours: float
    overall_success_rate: float
    tasks_completed_this_week: int
    active_agents: int
    top_agent_by_cost: str | None
    top_agent_by_runs: str | None
    daily_cost_last_7_days: list[DailyMetric] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Collects and aggregates metrics from the database.

    Parameters
    ----------
    session_factory:
        An async callable that returns an :class:`AsyncSession`.
        Typically ``async_sessionmaker(engine)``.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_cost_summary(self, period_days: int = 30) -> CostSummary:
        """Return cost breakdown for the given period.

        Parameters
        ----------
        period_days:
            Number of days to look back from now.
        """
        since = datetime.now(UTC) - timedelta(days=period_days)

        async with self._session_factory() as session:
            # Total cost + tokens
            total_row = await session.execute(
                select(
                    func.coalesce(func.sum(AgentRun.cost_usd), 0).label("total_cost"),
                    func.coalesce(func.sum(AgentRun.tokens_used), 0).label("total_tokens"),
                    func.count(AgentRun.id).label("run_count"),
                ).where(AgentRun.started_at >= since)
            )
            total = total_row.one()

            # Cost per agent
            agent_rows = await session.execute(
                select(
                    AgentRun.agent_id,
                    func.coalesce(func.sum(AgentRun.cost_usd), 0).label("agent_cost"),
                ).where(AgentRun.started_at >= since)
                .group_by(AgentRun.agent_id)
            )
            cost_by_agent: dict[str, float] = {
                row.agent_id: float(row.agent_cost)
                for row in agent_rows
                if row.agent_id is not None
            }

            # Daily costs
            daily_rows = await session.execute(
                select(
                    func.date(AgentRun.started_at).label("day"),
                    func.coalesce(func.sum(AgentRun.cost_usd), 0).label("day_cost"),
                ).where(AgentRun.started_at >= since)
                .group_by(func.date(AgentRun.started_at))
                .order_by(text("day"))
            )
            cost_by_day = [
                DailyMetric(date=str(row.day), value=float(row.day_cost))
                for row in daily_rows
            ]

            total_cost = float(total.total_cost)
            run_count = int(total.run_count)
            avg_cost_per_task = total_cost / run_count if run_count > 0 else 0.0

        return CostSummary(
            total_cost_usd=total_cost,
            cost_by_agent=cost_by_agent,
            cost_by_day=cost_by_day,
            total_tokens=int(total.total_tokens),
            avg_cost_per_task=avg_cost_per_task,
            period_days=period_days,
        )

    async def get_speed_metrics(self, period_days: int = 30) -> SpeedMetrics:
        """Return speed / throughput metrics for the given period.

        Parameters
        ----------
        period_days:
            Number of days to look back from now.
        """
        since = datetime.now(UTC) - timedelta(days=period_days)

        async with self._session_factory() as session:
            # Tasks completed in period
            completed_rows = await session.execute(
                select(Task).where(
                    Task.status == TaskStatus.DONE,
                    Task.updated_at >= since,
                )
            )
            completed_tasks = list(completed_rows.scalars().all())

            # avg issue→PR (created_at → updated_at for done tasks, in hours)
            if completed_tasks:
                durations = [
                    (
                        t.updated_at.replace(tzinfo=UTC) - t.created_at.replace(tzinfo=UTC)
                    ).total_seconds() / 3600
                    for t in completed_tasks
                ]
                avg_issue_to_pr = sum(durations) / len(durations)
            else:
                avg_issue_to_pr = 0.0

            # avg PR→merge: use AgentRun duration for runs with DONE tasks
            run_rows = await session.execute(
                select(AgentRun).where(
                    AgentRun.status == AgentRunStatus.SUCCESS,
                    AgentRun.started_at >= since,
                    AgentRun.finished_at.isnot(None),
                )
            )
            runs = list(run_rows.scalars().all())
            if runs:
                run_durations = [
                    (
                        r.finished_at.replace(tzinfo=UTC) - r.started_at.replace(tzinfo=UTC)
                    ).total_seconds() / 3600
                    for r in runs
                    if r.finished_at and r.started_at
                ]
                avg_pr_to_merge = sum(run_durations) / len(run_durations) if run_durations else 0.0
            else:
                avg_pr_to_merge = 0.0

            throughput = len(completed_tasks) / period_days if period_days > 0 else 0.0

            # Daily throughput
            daily_map: dict[str, int] = {}
            for t in completed_tasks:
                day = t.updated_at.date().isoformat()
                daily_map[day] = daily_map.get(day, 0) + 1
            daily_throughput = [
                DailyMetric(date=day, value=float(count))
                for day, count in sorted(daily_map.items())
            ]

        return SpeedMetrics(
            avg_issue_to_pr_hours=avg_issue_to_pr,
            avg_pr_to_merge_hours=avg_pr_to_merge,
            throughput_tasks_per_day=throughput,
            tasks_completed=len(completed_tasks),
            period_days=period_days,
            daily_throughput=daily_throughput,
        )

    async def get_quality_metrics(self, period_days: int = 30) -> QualityMetrics:
        """Return quality metrics for the given period.

        Parameters
        ----------
        period_days:
            Number of days to look back from now.
        """
        since = datetime.now(UTC) - timedelta(days=period_days)

        async with self._session_factory() as session:
            # All runs in period
            all_runs_rows = await session.execute(
                select(AgentRun).where(AgentRun.started_at >= since)
            )
            all_runs = list(all_runs_rows.scalars().all())

            total_runs = len(all_runs)
            failed_runs = sum(1 for r in all_runs if r.status == AgentRunStatus.FAILED)
            success_rate = (total_runs - failed_runs) / total_runs if total_runs > 0 else 0.0

            # Bugs found by tester (failed tester runs joined via agent role)
            tester_runs_rows = await session.execute(
                select(AgentRun)
                .join(Agent, AgentRun.agent_id == Agent.id)
                .where(
                    AgentRun.started_at >= since,
                    Agent.role == "tester",
                    AgentRun.status == AgentRunStatus.FAILED,
                )
            )
            bugs_found = len(list(tester_runs_rows.scalars().all()))

            # Code churn: tasks with >1 run
            churn_rows = await session.execute(
                select(AgentRun.task_id, func.count(AgentRun.id).label("run_count"))
                .where(AgentRun.started_at >= since)
                .group_by(AgentRun.task_id)
                .having(func.count(AgentRun.id) > 1)
            )
            code_churn = len(list(churn_rows.all()))

            # Per-agent success rates
            agent_runs_rows = await session.execute(
                select(
                    AgentRun.agent_id,
                    AgentRun.status,
                    func.count(AgentRun.id).label("cnt"),
                )
                .where(AgentRun.started_at >= since)
                .group_by(AgentRun.agent_id, AgentRun.status)
            )
            agent_totals: dict[str, int] = {}
            agent_successes: dict[str, int] = {}
            for row in agent_runs_rows:
                aid = row.agent_id or "unknown"
                agent_totals[aid] = agent_totals.get(aid, 0) + row.cnt
                if row.status == AgentRunStatus.SUCCESS:
                    agent_successes[aid] = agent_successes.get(aid, 0) + row.cnt
            success_rate_by_agent = {
                aid: agent_successes.get(aid, 0) / total
                for aid, total in agent_totals.items()
                if total > 0
            }

        return QualityMetrics(
            agent_success_rate=success_rate,
            bugs_found_by_tester=bugs_found,
            code_churn=code_churn,
            total_runs=total_runs,
            failed_runs=failed_runs,
            period_days=period_days,
            success_rate_by_agent=success_rate_by_agent,
        )

    async def get_agent_stats(self, agent_id: str) -> AgentStats:
        """Return statistics for a specific agent.

        Parameters
        ----------
        agent_id:
            The agent's string identifier.

        Raises
        ------
        ValueError
            If no agent with the given ID exists.
        """
        async with self._session_factory() as session:
            agent_row = await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = agent_row.scalar_one_or_none()
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' not found")

            runs_rows = await session.execute(
                select(AgentRun).where(AgentRun.agent_id == agent_id)
            )
            runs = list(runs_rows.scalars().all())

            total_runs = len(runs)
            successful_runs = sum(1 for r in runs if r.status == AgentRunStatus.SUCCESS)
            failed_runs = sum(1 for r in runs if r.status == AgentRunStatus.FAILED)
            success_rate = successful_runs / total_runs if total_runs > 0 else 0.0

            durations = [
                (
                    r.finished_at.replace(tzinfo=UTC) - r.started_at.replace(tzinfo=UTC)
                ).total_seconds()
                for r in runs
                if r.started_at and r.finished_at
            ]
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            total_cost = float(sum(r.cost_usd or Decimal("0") for r in runs))
            total_tokens = sum(r.tokens_used or 0 for r in runs)

            last_run_at = (
                agent.last_run_at.isoformat()
                if agent.last_run_at
                else None
            )

        return AgentStats(
            agent_id=agent_id,
            role=agent.role,
            status=agent.status,
            total_runs=total_runs,
            successful_runs=successful_runs,
            failed_runs=failed_runs,
            success_rate=success_rate,
            avg_duration_seconds=avg_duration,
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            last_run_at=last_run_at,
        )

    async def get_dashboard_stats(self) -> DashboardStats:
        """Return a high-level summary for the main dashboard page."""
        since_month = datetime.now(UTC) - timedelta(days=30)
        since_week = datetime.now(UTC) - timedelta(days=7)
        since_7d = datetime.now(UTC) - timedelta(days=7)

        async with self._session_factory() as session:
            # All-time total cost
            total_cost_row = await session.execute(
                select(func.coalesce(func.sum(AgentRun.cost_usd), 0).label("total"))
            )
            total_cost = float(total_cost_row.scalar_one())

            # This-month cost
            month_cost_row = await session.execute(
                select(func.coalesce(func.sum(AgentRun.cost_usd), 0).label("total"))
                .where(AgentRun.started_at >= since_month)
            )
            cost_this_month = float(month_cost_row.scalar_one())

            # Avg task duration (hours) — from done tasks in last 30 days
            done_tasks_rows = await session.execute(
                select(Task).where(
                    Task.status == TaskStatus.DONE,
                    Task.updated_at >= since_month,
                )
            )
            done_tasks = list(done_tasks_rows.scalars().all())
            if done_tasks:
                durations_h = [
                    (
                        t.updated_at.replace(tzinfo=UTC) - t.created_at.replace(tzinfo=UTC)
                    ).total_seconds() / 3600
                    for t in done_tasks
                ]
                avg_task_duration = sum(durations_h) / len(durations_h)
            else:
                avg_task_duration = 0.0

            # Overall success rate (last 30 days)
            runs_month_rows = await session.execute(
                select(AgentRun).where(AgentRun.started_at >= since_month)
            )
            runs_month = list(runs_month_rows.scalars().all())
            total_r = len(runs_month)
            failed_r = sum(1 for r in runs_month if r.status == AgentRunStatus.FAILED)
            overall_success = (total_r - failed_r) / total_r if total_r > 0 else 0.0

            # Tasks completed this week
            week_tasks_row = await session.execute(
                select(func.count(Task.id)).where(
                    Task.status == TaskStatus.DONE,
                    Task.updated_at >= since_week,
                )
            )
            tasks_this_week = int(week_tasks_row.scalar_one())

            # Active agents
            active_statuses = ["working", "busy", "assigned"]
            active_row = await session.execute(
                select(func.count(Agent.id)).where(Agent.status.in_(active_statuses))
            )
            active_agents = int(active_row.scalar_one())

            # Top agent by cost
            top_cost_row = await session.execute(
                select(AgentRun.agent_id)
                .where(AgentRun.agent_id.isnot(None))
                .group_by(AgentRun.agent_id)
                .order_by(func.sum(AgentRun.cost_usd).desc())
                .limit(1)
            )
            top_agent_cost = top_cost_row.scalar_one_or_none()

            # Top agent by runs
            top_runs_row = await session.execute(
                select(AgentRun.agent_id)
                .where(AgentRun.agent_id.isnot(None))
                .group_by(AgentRun.agent_id)
                .order_by(func.count(AgentRun.id).desc())
                .limit(1)
            )
            top_agent_runs = top_runs_row.scalar_one_or_none()

            # Daily cost last 7 days
            daily_cost_rows = await session.execute(
                select(
                    func.date(AgentRun.started_at).label("day"),
                    func.coalesce(func.sum(AgentRun.cost_usd), 0).label("day_cost"),
                )
                .where(AgentRun.started_at >= since_7d)
                .group_by(func.date(AgentRun.started_at))
                .order_by(text("day"))
            )
            daily_cost = [
                DailyMetric(date=str(row.day), value=float(row.day_cost))
                for row in daily_cost_rows
            ]

        return DashboardStats(
            total_cost_usd=total_cost,
            cost_this_month=cost_this_month,
            avg_task_duration_hours=avg_task_duration,
            overall_success_rate=overall_success,
            tasks_completed_this_week=tasks_this_week,
            active_agents=active_agents,
            top_agent_by_cost=top_agent_cost,
            top_agent_by_runs=top_agent_runs,
            daily_cost_last_7_days=daily_cost,
        )
