/**
 * Metrics API client for the AutoDev Framework dashboard.
 * Fetches cost, speed, quality and agent metrics from /api/metrics/*.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface DailyMetric {
  date: string
  value: number
}

export interface CostSummary {
  total_cost_usd: number
  cost_by_agent: Record<string, number>
  cost_by_day: DailyMetric[]
  total_tokens: number
  avg_cost_per_task: number
  period_days: number
}

export interface SpeedMetrics {
  avg_issue_to_pr_hours: number
  avg_pr_to_merge_hours: number
  throughput_tasks_per_day: number
  tasks_completed: number
  period_days: number
  daily_throughput: DailyMetric[]
}

export interface QualityMetrics {
  agent_success_rate: number
  bugs_found_by_tester: number
  code_churn: number
  total_runs: number
  failed_runs: number
  period_days: number
  success_rate_by_agent: Record<string, number>
}

export interface AgentStats {
  agent_id: string
  role: string
  status: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
  avg_duration_seconds: number
  total_cost_usd: number
  total_tokens: number
  last_run_at: string | null
}

export interface MetricsDashboardStats {
  total_cost_usd: number
  cost_this_month: number
  avg_task_duration_hours: number
  overall_success_rate: number
  tasks_completed_this_week: number
  active_agents: number
  top_agent_by_cost: string | null
  top_agent_by_runs: string | null
  daily_cost_last_7_days: DailyMetric[]
}

// ---------------------------------------------------------------------------
// Mock data (used until the API is wired up)
// ---------------------------------------------------------------------------

const MOCK_COST: CostSummary = {
  total_cost_usd: 1.2345,
  cost_by_agent: {
    'developer-1': 0.45,
    'tester-1': 0.32,
    'ba-1': 0.25,
    'pm-1': 0.21,
  },
  cost_by_day: [
    { date: '2026-03-09', value: 0.04 },
    { date: '2026-03-10', value: 0.06 },
    { date: '2026-03-11', value: 0.09 },
    { date: '2026-03-12', value: 0.12 },
    { date: '2026-03-13', value: 0.08 },
    { date: '2026-03-14', value: 0.10 },
    { date: '2026-03-15', value: 0.07 },
  ],
  total_tokens: 48320,
  avg_cost_per_task: 0.0617,
  period_days: 30,
}

const MOCK_SPEED: SpeedMetrics = {
  avg_issue_to_pr_hours: 3.7,
  avg_pr_to_merge_hours: 1.2,
  throughput_tasks_per_day: 0.67,
  tasks_completed: 20,
  period_days: 30,
  daily_throughput: [
    { date: '2026-03-09', value: 1 },
    { date: '2026-03-10', value: 2 },
    { date: '2026-03-11', value: 0 },
    { date: '2026-03-12', value: 3 },
    { date: '2026-03-13', value: 1 },
    { date: '2026-03-14', value: 2 },
    { date: '2026-03-15', value: 1 },
  ],
}

const MOCK_QUALITY: QualityMetrics = {
  agent_success_rate: 0.87,
  bugs_found_by_tester: 4,
  code_churn: 3,
  total_runs: 54,
  failed_runs: 7,
  period_days: 30,
  success_rate_by_agent: {
    'developer-1': 0.91,
    'tester-1': 0.78,
    'ba-1': 0.95,
    'pm-1': 0.88,
  },
}

const MOCK_DASHBOARD: MetricsDashboardStats = {
  total_cost_usd: 4.5678,
  cost_this_month: 1.2345,
  avg_task_duration_hours: 4.2,
  overall_success_rate: 0.87,
  tasks_completed_this_week: 5,
  active_agents: 2,
  top_agent_by_cost: 'developer-1',
  top_agent_by_runs: 'developer-1',
  daily_cost_last_7_days: MOCK_COST.cost_by_day,
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function getMetricsCost(days = 30): Promise<CostSummary> {
  // TODO: return await fetch(`${BASE_URL}/api/metrics/cost?days=${days}`).then(r => r.json())
  void BASE_URL
  void days
  return MOCK_COST
}

export async function getMetricsSpeed(days = 30): Promise<SpeedMetrics> {
  // TODO: return await fetch(`${BASE_URL}/api/metrics/speed?days=${days}`).then(r => r.json())
  void days
  return MOCK_SPEED
}

export async function getMetricsQuality(days = 30): Promise<QualityMetrics> {
  // TODO: return await fetch(`${BASE_URL}/api/metrics/quality?days=${days}`).then(r => r.json())
  void days
  return MOCK_QUALITY
}

export async function getMetricsAgentStats(agentId: string): Promise<AgentStats> {
  return await fetch(`${BASE_URL}/api/metrics/agents/${agentId}`).then(r => r.json())
}

export async function getMetricsDashboard(): Promise<MetricsDashboardStats> {
  // TODO: return await fetch(`${BASE_URL}/api/metrics/dashboard`).then(r => r.json())
  return MOCK_DASHBOARD
}
