"""Metrics and analytics REST endpoints.

Exposes aggregated cost, speed, and quality metrics collected from the database.

Routes
------
GET /api/metrics/cost?days=30
GET /api/metrics/speed?days=30
GET /api/metrics/quality?days=30
GET /api/metrics/agents/{agent_id}
GET /api/metrics/dashboard
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from autodev.core.metrics import (
    AgentStats,
    CostSummary,
    DailyMetric,
    DashboardStats,
    MetricsCollector,
    QualityMetrics,
    SpeedMetrics,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic response schemas (convert dataclasses → JSON-serialisable models)
# ---------------------------------------------------------------------------


class DailyMetricResponse(BaseModel):
    date: str
    value: float


class CostSummaryResponse(BaseModel):
    total_cost_usd: float
    cost_by_agent: dict[str, float]
    cost_by_day: list[DailyMetricResponse]
    total_tokens: int
    avg_cost_per_task: float
    period_days: int


class SpeedMetricsResponse(BaseModel):
    avg_issue_to_pr_hours: float
    avg_pr_to_merge_hours: float
    throughput_tasks_per_day: float
    tasks_completed: int
    period_days: int
    daily_throughput: list[DailyMetricResponse]


class QualityMetricsResponse(BaseModel):
    agent_success_rate: float
    bugs_found_by_tester: int
    code_churn: int
    total_runs: int
    failed_runs: int
    period_days: int
    success_rate_by_agent: dict[str, float]


class AgentStatsResponse(BaseModel):
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


class DashboardStatsResponse(BaseModel):
    total_cost_usd: float
    cost_this_month: float
    avg_task_duration_hours: float
    overall_success_rate: float
    tasks_completed_this_week: int
    active_agents: int
    top_agent_by_cost: str | None
    top_agent_by_runs: str | None
    daily_cost_last_7_days: list[DailyMetricResponse]


# ---------------------------------------------------------------------------
# Dependency: get a MetricsCollector
# TODO: wire to real session_factory from app state / DI container
# ---------------------------------------------------------------------------


def _get_collector() -> MetricsCollector:
    """Return a MetricsCollector bound to the application session factory."""
    from autodev.api.database import SessionLocal

    return MetricsCollector(SessionLocal)


def _daily_metrics(items: list[DailyMetric]) -> list[DailyMetricResponse]:
    return [DailyMetricResponse(date=d.date, value=d.value) for d in items]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/cost", summary="Cost metrics", response_model=CostSummaryResponse)
async def get_cost_metrics(
    days: Annotated[int, Query(ge=1, le=365, description="Look-back window in days")] = 30,
) -> CostSummaryResponse:
    """Return cost breakdown (total, per-agent, per-day) for the past *days* days."""
    try:
        collector = _get_collector()
        summary: CostSummary = await collector.get_cost_summary(period_days=days)
    except Exception as exc:
        logger.exception("Failed to fetch cost metrics")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return CostSummaryResponse(
        total_cost_usd=summary.total_cost_usd,
        cost_by_agent=summary.cost_by_agent,
        cost_by_day=_daily_metrics(summary.cost_by_day),
        total_tokens=summary.total_tokens,
        avg_cost_per_task=summary.avg_cost_per_task,
        period_days=summary.period_days,
    )


@router.get("/speed", summary="Speed metrics", response_model=SpeedMetricsResponse)
async def get_speed_metrics(
    days: Annotated[int, Query(ge=1, le=365, description="Look-back window in days")] = 30,
) -> SpeedMetricsResponse:
    """Return speed metrics (avg time issue→PR, PR→merge, throughput) for the past *days* days."""
    try:
        collector = _get_collector()
        metrics: SpeedMetrics = await collector.get_speed_metrics(period_days=days)
    except Exception as exc:
        logger.exception("Failed to fetch speed metrics")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SpeedMetricsResponse(
        avg_issue_to_pr_hours=metrics.avg_issue_to_pr_hours,
        avg_pr_to_merge_hours=metrics.avg_pr_to_merge_hours,
        throughput_tasks_per_day=metrics.throughput_tasks_per_day,
        tasks_completed=metrics.tasks_completed,
        period_days=metrics.period_days,
        daily_throughput=_daily_metrics(metrics.daily_throughput),
    )


@router.get("/quality", summary="Quality metrics", response_model=QualityMetricsResponse)
async def get_quality_metrics(
    days: Annotated[int, Query(ge=1, le=365, description="Look-back window in days")] = 30,
) -> QualityMetricsResponse:
    """Return quality metrics (success rate, bugs, churn) for the past *days* days."""
    try:
        collector = _get_collector()
        metrics: QualityMetrics = await collector.get_quality_metrics(period_days=days)
    except Exception as exc:
        logger.exception("Failed to fetch quality metrics")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return QualityMetricsResponse(
        agent_success_rate=metrics.agent_success_rate,
        bugs_found_by_tester=metrics.bugs_found_by_tester,
        code_churn=metrics.code_churn,
        total_runs=metrics.total_runs,
        failed_runs=metrics.failed_runs,
        period_days=metrics.period_days,
        success_rate_by_agent=metrics.success_rate_by_agent,
    )


@router.get(
    "/agents/{agent_id}",
    summary="Agent statistics",
    response_model=AgentStatsResponse,
)
async def get_agent_stats(agent_id: str) -> AgentStatsResponse:
    """Return per-agent statistics (runs, cost, success rate) for *agent_id*."""
    try:
        collector = _get_collector()
        stats: AgentStats = await collector.get_agent_stats(agent_id=agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to fetch agent stats for %s", agent_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return AgentStatsResponse(
        agent_id=stats.agent_id,
        role=stats.role,
        status=stats.status,
        total_runs=stats.total_runs,
        successful_runs=stats.successful_runs,
        failed_runs=stats.failed_runs,
        success_rate=stats.success_rate,
        avg_duration_seconds=stats.avg_duration_seconds,
        total_cost_usd=stats.total_cost_usd,
        total_tokens=stats.total_tokens,
        last_run_at=stats.last_run_at,
    )


@router.get("/dashboard", summary="Dashboard summary", response_model=DashboardStatsResponse)
async def get_dashboard_stats() -> DashboardStatsResponse:
    """Return a high-level metrics summary for the main dashboard page."""
    try:
        collector = _get_collector()
        stats: DashboardStats = await collector.get_dashboard_stats()
    except Exception as exc:
        logger.exception("Failed to fetch dashboard stats")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DashboardStatsResponse(
        total_cost_usd=stats.total_cost_usd,
        cost_this_month=stats.cost_this_month,
        avg_task_duration_hours=stats.avg_task_duration_hours,
        overall_success_rate=stats.overall_success_rate,
        tasks_completed_this_week=stats.tasks_completed_this_week,
        active_agents=stats.active_agents,
        top_agent_by_cost=stats.top_agent_by_cost,
        top_agent_by_runs=stats.top_agent_by_runs,
        daily_cost_last_7_days=_daily_metrics(stats.daily_cost_last_7_days),
    )
