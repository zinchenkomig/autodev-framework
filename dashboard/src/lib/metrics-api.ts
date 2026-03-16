/**
 * Metrics API client for the AutoDev Framework dashboard.
 * Fetches cost, speed, quality and agent metrics from /api/metrics/*.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? ''

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
// Generic fetch helper — returns null on error
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`)
    if (!res.ok) {
      console.warn(`[metrics-api] ${path} returned ${res.status}`)
      return null
    }
    return (await res.json()) as T
  } catch (err) {
    console.warn(`[metrics-api] ${path} failed (${err})`)
    return null
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function getMetricsCost(days = 30): Promise<CostSummary | null> {
  return apiFetch<CostSummary>(`/api/metrics/cost?days=${days}`)
}

export async function getMetricsSpeed(days = 30): Promise<SpeedMetrics | null> {
  return apiFetch<SpeedMetrics>(`/api/metrics/speed?days=${days}`)
}

export async function getMetricsQuality(days = 30): Promise<QualityMetrics | null> {
  return apiFetch<QualityMetrics>(`/api/metrics/quality?days=${days}`)
}

export async function getMetricsAgentStats(agentId: string): Promise<AgentStats | null> {
  return apiFetch<AgentStats>(`/api/metrics/agents/${agentId}`)
}

export async function getMetricsDashboard(): Promise<MetricsDashboardStats | null> {
  return apiFetch<MetricsDashboardStats>('/api/metrics/dashboard')
}
