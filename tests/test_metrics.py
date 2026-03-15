"""Tests for autodev.core.metrics — MetricsCollector and dataclasses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from autodev.core.metrics import (
    AgentStats,
    CostSummary,
    DailyMetric,
    DashboardStats,
    MetricsCollector,
    QualityMetrics,
    SpeedMetrics,
)
from autodev.core.models import (
    Agent,
    AgentRun,
    AgentRunStatus,
    AgentStatus,
    Base,
    Task,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# In-memory SQLite engine for tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def create_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="module")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(scope="module")
def collector(session_factory):
    return MetricsCollector(session_factory)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_data(session_factory):
    """Insert a minimal set of agents, tasks, and runs for metric tests."""
    now = datetime.now(UTC)

    async with session_factory() as session:
        # Agents
        dev = Agent(id="developer-1", role="developer", status=AgentStatus.IDLE)
        tester = Agent(id="tester-1", role="tester", status=AgentStatus.IDLE)
        session.add_all([dev, tester])
        await session.flush()

        # Tasks
        t1 = Task(
            id=uuid.uuid4(),
            title="Fix bug #1",
            status=TaskStatus.DONE,
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(days=4),
        )
        t2 = Task(
            id=uuid.uuid4(),
            title="Feature #2",
            status=TaskStatus.DONE,
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=2),
        )
        t3 = Task(
            id=uuid.uuid4(),
            title="Task #3",
            status=TaskStatus.IN_PROGRESS,
            created_at=now - timedelta(days=1),
            updated_at=now,
        )
        session.add_all([t1, t2, t3])
        await session.flush()

        # Runs
        r1 = AgentRun(
            id=uuid.uuid4(),
            agent_id="developer-1",
            task_id=t1.id,
            status=AgentRunStatus.SUCCESS,
            started_at=now - timedelta(days=5),
            finished_at=now - timedelta(days=5, hours=-2),
            tokens_used=1000,
            cost_usd=Decimal("0.0500"),
        )
        r2 = AgentRun(
            id=uuid.uuid4(),
            agent_id="developer-1",
            task_id=t1.id,  # second run on same task → churn
            status=AgentRunStatus.FAILED,
            started_at=now - timedelta(days=4),
            finished_at=now - timedelta(days=4, hours=-1),
            tokens_used=500,
            cost_usd=Decimal("0.0250"),
        )
        r3 = AgentRun(
            id=uuid.uuid4(),
            agent_id="tester-1",
            task_id=t2.id,
            status=AgentRunStatus.FAILED,  # tester bug found
            started_at=now - timedelta(days=3),
            finished_at=now - timedelta(days=3, hours=-1),
            tokens_used=300,
            cost_usd=Decimal("0.0150"),
        )
        r4 = AgentRun(
            id=uuid.uuid4(),
            agent_id="tester-1",
            task_id=t2.id,
            status=AgentRunStatus.SUCCESS,
            started_at=now - timedelta(days=2),
            finished_at=now - timedelta(days=2, hours=-1),
            tokens_used=200,
            cost_usd=Decimal("0.0100"),
        )
        session.add_all([r1, r2, r3, r4])
        await session.commit()

    return {"t1": t1, "t2": t2, "t3": t3}


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_daily_metric_fields(self):
        dm = DailyMetric(date="2026-03-15", value=1.23)
        assert dm.date == "2026-03-15"
        assert dm.value == pytest.approx(1.23)

    def test_cost_summary_defaults(self):
        cs = CostSummary(
            total_cost_usd=0.0,
            cost_by_agent={},
            cost_by_day=[],
            total_tokens=0,
            avg_cost_per_task=0.0,
            period_days=30,
        )
        assert cs.period_days == 30
        assert cs.cost_by_agent == {}
        assert cs.cost_by_day == []

    def test_speed_metrics_fields(self):
        sm = SpeedMetrics(
            avg_issue_to_pr_hours=2.5,
            avg_pr_to_merge_hours=1.0,
            throughput_tasks_per_day=0.5,
            tasks_completed=15,
            period_days=30,
            daily_throughput=[],
        )
        assert sm.avg_issue_to_pr_hours == pytest.approx(2.5)
        assert sm.tasks_completed == 15

    def test_quality_metrics_fields(self):
        qm = QualityMetrics(
            agent_success_rate=0.9,
            bugs_found_by_tester=3,
            code_churn=2,
            total_runs=40,
            failed_runs=4,
            period_days=30,
            success_rate_by_agent={"dev": 0.9},
        )
        assert qm.bugs_found_by_tester == 3
        assert qm.success_rate_by_agent["dev"] == pytest.approx(0.9)

    def test_agent_stats_fields(self):
        ags = AgentStats(
            agent_id="dev-1",
            role="developer",
            status="idle",
            total_runs=10,
            successful_runs=8,
            failed_runs=2,
            success_rate=0.8,
            avg_duration_seconds=120.0,
            total_cost_usd=0.5,
            total_tokens=5000,
            last_run_at=None,
        )
        assert ags.success_rate == pytest.approx(0.8)
        assert ags.last_run_at is None

    def test_dashboard_stats_fields(self):
        ds = DashboardStats(
            total_cost_usd=10.0,
            cost_this_month=2.5,
            avg_task_duration_hours=4.0,
            overall_success_rate=0.85,
            tasks_completed_this_week=5,
            active_agents=3,
            top_agent_by_cost="dev-1",
            top_agent_by_runs="dev-1",
        )
        assert ds.daily_cost_last_7_days == []


# ---------------------------------------------------------------------------
# MetricsCollector integration tests (SQLite in-memory)
# ---------------------------------------------------------------------------


class TestMetricsCollectorEmpty:
    """Tests against an empty database — verifies zero-value returns."""

    @pytest.mark.asyncio
    async def test_cost_summary_empty(self, collector):
        result = await collector.get_cost_summary(period_days=30)
        assert isinstance(result, CostSummary)
        assert result.total_cost_usd == pytest.approx(0.0)
        assert result.total_tokens == 0
        assert result.cost_by_agent == {}
        assert result.cost_by_day == []

    @pytest.mark.asyncio
    async def test_speed_metrics_empty(self, collector):
        result = await collector.get_speed_metrics(period_days=30)
        assert isinstance(result, SpeedMetrics)
        assert result.tasks_completed == 0
        assert result.throughput_tasks_per_day == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_quality_metrics_empty(self, collector):
        result = await collector.get_quality_metrics(period_days=30)
        assert isinstance(result, QualityMetrics)
        assert result.total_runs == 0
        assert result.agent_success_rate == pytest.approx(0.0)
        assert result.success_rate_by_agent == {}

    @pytest.mark.asyncio
    async def test_dashboard_stats_empty(self, collector):
        result = await collector.get_dashboard_stats()
        assert isinstance(result, DashboardStats)
        assert result.total_cost_usd == pytest.approx(0.0)
        assert result.active_agents == 0

    @pytest.mark.asyncio
    async def test_get_agent_stats_not_found(self, collector):
        with pytest.raises(ValueError, match="not found"):
            await collector.get_agent_stats("nonexistent-agent")


class TestMetricsCollectorWithData:
    """Tests against a seeded database."""

    @pytest_asyncio.fixture(autouse=True, scope="module")
    async def seed(self, session_factory):
        await _seed_data(session_factory)

    @pytest.mark.asyncio
    async def test_cost_summary_nonzero(self, collector):
        result = await collector.get_cost_summary(period_days=30)
        assert result.total_cost_usd > 0
        assert result.total_tokens > 0
        assert "developer-1" in result.cost_by_agent
        assert "tester-1" in result.cost_by_agent
        assert len(result.cost_by_day) > 0

    @pytest.mark.asyncio
    async def test_cost_summary_by_agent_sum(self, collector):
        result = await collector.get_cost_summary(period_days=30)
        agent_sum = sum(result.cost_by_agent.values())
        assert agent_sum == pytest.approx(result.total_cost_usd, rel=1e-4)

    @pytest.mark.asyncio
    async def test_speed_metrics_completed_tasks(self, collector):
        result = await collector.get_speed_metrics(period_days=30)
        # t1 and t2 are DONE
        assert result.tasks_completed >= 2
        assert result.avg_issue_to_pr_hours > 0

    @pytest.mark.asyncio
    async def test_quality_metrics_bugs_found(self, collector):
        result = await collector.get_quality_metrics(period_days=30)
        # tester-1 had 1 FAILED run
        assert result.bugs_found_by_tester >= 1

    @pytest.mark.asyncio
    async def test_quality_metrics_code_churn(self, collector):
        result = await collector.get_quality_metrics(period_days=30)
        # t1 had 2 runs → churn
        assert result.code_churn >= 1

    @pytest.mark.asyncio
    async def test_quality_metrics_failed_runs(self, collector):
        result = await collector.get_quality_metrics(period_days=30)
        assert result.failed_runs >= 1
        assert result.total_runs >= result.failed_runs

    @pytest.mark.asyncio
    async def test_agent_stats_developer(self, collector):
        result = await collector.get_agent_stats("developer-1")
        assert result.agent_id == "developer-1"
        assert result.role == "developer"
        assert result.total_runs >= 2
        assert result.failed_runs >= 1
        assert 0.0 <= result.success_rate <= 1.0
        assert result.total_cost_usd > 0

    @pytest.mark.asyncio
    async def test_agent_stats_tester(self, collector):
        result = await collector.get_agent_stats("tester-1")
        assert result.agent_id == "tester-1"
        assert result.role == "tester"
        assert result.total_runs >= 2

    @pytest.mark.asyncio
    async def test_dashboard_stats_with_data(self, collector):
        result = await collector.get_dashboard_stats()
        assert result.total_cost_usd > 0
        assert result.cost_this_month > 0

    @pytest.mark.asyncio
    async def test_metrics_period_filter(self, collector):
        # period of 1 day should return fewer/zero results for older data
        result_30 = await collector.get_cost_summary(period_days=30)
        result_1 = await collector.get_cost_summary(period_days=1)
        # 30d should have >= costs than 1d
        assert result_30.total_cost_usd >= result_1.total_cost_usd
