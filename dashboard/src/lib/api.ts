const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? ''

export type Priority = 'critical' | 'high' | 'normal' | 'low'
export type TaskStatus = 'queued' | 'assigned' | 'in_progress' | 'autoreview' | 'review' | 'ready_to_release' | 'staging' | 'released' | 'failed'
export type AgentStatus = 'idle' | 'running' | 'failed'
export type ReleaseStatus = 'draft' | 'staging' | 'testing' | 'pending_approval' | 'approved' | 'deployed' | 'failed' | 'cancelled' | 'reverted'

export interface Task {
  id: string
  title: string
  description: string
  source: string
  priority: Priority
  status: TaskStatus
  assigned_to: string | null
  repo: string
  issue_number: number | null
  pr_number: number | null
  pr_url: string | null
  branch: string | null
  depends_on: string[] | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface Agent {
  id: string
  role: string
  status: AgentStatus
  current_task_id: string | null
  current_task_title?: string | null
  last_run_at: string | null
  total_runs: number
  total_failures: number
  enabled: boolean
}

export interface Event {
  id: string
  type: string
  payload: Record<string, unknown>
  source: string
  created_at: string
  description?: string
  related_id?: string
  related_type?: 'task' | 'release' | 'pr'
}

export interface ReleasePR {
  number: number
  title: string
  author: string
  url: string
  merged_at: string | null
}

export interface MergeResult {
  task_id?: string
  pr_url?: string
  branch?: string
  repo?: string
  pr_number?: number
  success: boolean
  error?: string
}

export interface Release {
  id: string
  version: string
  status: ReleaseStatus
  tasks: string[]
  prs: ReleasePR[]
  release_notes: string
  testing_plan: string
  ba_report: string | null
  tester_report: string | null
  staging_deployed_at: string | null
  production_deployed_at: string | null
  approved_by: string | null
  reverted_at: string | null
  reverted_by: string | null
  previous_status: string | null
  created_at: string
  merge_results?: MergeResult[]
}

export interface DashboardStats {
  active_tasks: number
  running_agents: number
  open_prs: number
  latest_release: string | null
  task_trend: number
  agent_trend: number
  pr_trend: number
}

export type AgentMonitorStatus = 'idle' | 'working' | 'failed'

export interface AgentMonitor {
  id: string
  role: string
  status: AgentMonitorStatus
  current_task_id: string | null
  current_task_title?: string | null
  last_run_at: string | null
  total_runs: number
  total_failures: number
  avg_time: string
  enabled: boolean
}

export type AgentRunStatus = 'success' | 'failed' | 'running' | 'cancelled'

export interface AgentRun {
  id: string
  agent_id: string
  agent_role: string
  task_title: string
  run_status: AgentRunStatus
  duration: string | null
  tokens: number | null
  cost: number | null
  started_at: string
  finished_at: string | null
}

export type AgentLogLevel = 'info' | 'warning' | 'error'

export interface AgentLog {
  id: string
  agent_id: string
  task_id: string | null
  level: AgentLogLevel
  message: string
  details: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// Generic fetch helper — returns null on error, no mock fallback
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
    if (!res.ok) {
      console.warn(`[api] ${path} returned ${res.status}`)
      return null
    }
    return (await res.json()) as T
  } catch (err) {
    console.warn(`[api] ${path} failed (${err})`)
    return null
  }
}

// ---------------------------------------------------------------------------
// API functions — real endpoints, empty array / null on error
// ---------------------------------------------------------------------------

export async function getTasks(): Promise<Task[]> {
  return (await apiFetch<Task[]>('/api/tasks/')) ?? []
}

export async function getAgents(): Promise<Agent[]> {
  return (await apiFetch<Agent[]>('/api/agents/')) ?? []
}

export async function getEvents(): Promise<Event[]> {
  return (await apiFetch<Event[]>('/api/events/')) ?? []
}

export async function getReleases(): Promise<Release[]> {
  return (await apiFetch<Release[]>('/api/releases/')) ?? []
}

export async function getRelease(id: string): Promise<Release | null> {
  return apiFetch<Release>(`/api/releases/${id}`)
}

export async function getStats(): Promise<DashboardStats | null> {
  return apiFetch<DashboardStats>('/api/stats')
}

export async function getAgentMonitors(): Promise<AgentMonitor[]> {
  const agents = await apiFetch<Agent[]>('/api/agents/')
  if (!agents) return []
  return agents.map(a => ({
    id: a.id,
    role: a.role,
    status: (a.status === 'running' ? 'working' : a.status) as AgentMonitorStatus,
    current_task_id: a.current_task_id,
    current_task_title: a.current_task_title ?? null,
    last_run_at: a.last_run_at,
    total_runs: a.total_runs,
    total_failures: a.total_failures,
    avg_time: '',
    enabled: a.enabled,
  }))
}

export async function getAgentRuns(): Promise<AgentRun[]> {
  return (await apiFetch<AgentRun[]>('/api/agents/runs/')) ?? []
}

export async function getAgentLogs(agentId: string, limit = 50, taskId?: string): Promise<AgentLog[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (taskId) params.set('task_id', taskId)
  return (await apiFetch<AgentLog[]>(`/api/agents/${agentId}/logs?${params}`)) ?? []
}

// ---------------------------------------------------------------------------
// Write operations
// ---------------------------------------------------------------------------

export async function createTask(data: Partial<Task>): Promise<Task> {
  const res = await fetch(`${BASE_URL}/api/tasks/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create task: ${res.status}`)
  return res.json()
}

export async function updateTask(id: string, data: Partial<Task>): Promise<Task> {
  const res = await fetch(`${BASE_URL}/api/tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to update task: ${res.status}`)
  return res.json()
}

export async function createRelease(data: { version: string; release_notes?: string; tasks?: string[] }): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/releases/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create release: ${res.status}`)
  return res.json()
}

export async function approveRelease(id: string, approvedBy = 'user'): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/releases/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved_by: approvedBy }),
  })
  if (!res.ok) throw new Error(`Failed to approve release: ${res.status}`)
  return res.json()
}

export async function updateRelease(id: string, data: { status?: string }): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/releases/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to update release: ${res.status}`)
  return res.json()
}

export async function triggerAgent(agentId: string): Promise<{ event_id: string; agent_id: string; message: string }> {
  const res = await fetch(`${BASE_URL}/api/agents/${agentId}/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`Failed to trigger agent: ${res.status}`)
  return res.json()
}

export async function deleteTask(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/tasks/${id}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`Failed to delete task: ${res.status}`)
}

export async function unapproveRelease(id: string): Promise<Release> {
  const res = await fetch(`${BASE_URL}/releases/${id}/unapprove`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to unapprove release: ${res.statusText}`)
  return res.json()
}

export async function rollbackRelease(id: string): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/releases/${id}/rollback`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to rollback release: ${res.statusText}`)
  return res.json()
}

export async function cancelRelease(id: string): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/releases/${id}/cancel`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to cancel release: ${res.statusText}`)
  return res.json()
}

export async function revertRelease(id: string): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/releases/${id}/revert`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to revert release: ${res.statusText}`)
  return res.json()
}


export async function toggleAgent(agentId: string): Promise<Agent> {
  const res = await fetch(`${BASE_URL}/api/agents/${agentId}/toggle`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to toggle agent: ${res.status}`)
  return res.json()
}

export async function cancelDeveloperTask(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE_URL}/api/agents/developer/cancel`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to cancel task: ${res.status}`)
  return res.json()
}

// Task Logs
export interface TaskLog {
  id: string
  agent_id: string
  level: 'info' | 'warning' | 'error'
  message: string
  details: string | null
  created_at: string
}

export async function getTaskLogs(taskId: string, limit: number = 100): Promise<TaskLog[]> {
  return (await apiFetch<TaskLog[]>(`/api/tasks/${taskId}/logs?limit=${limit}`)) ?? []
}

// Restart task (delete branch, close PR, requeue)
export interface RestartResult {
  task_id: string
  status: string
  actions: string[]
}

export async function restartTask(taskId: string): Promise<RestartResult> {
  const res = await fetch(`${BASE_URL}/api/tasks/${taskId}/restart`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to restart task: ${res.status}`)
  return res.json()
}

// Alerts
export interface Alert {
  id: string
  type: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  title: string
  message: string | null
  source: string | null
  resolved: boolean
  resolved_at: string | null
  resolved_by: string | null
  notified: boolean
  created_at: string
}

export interface AlertStats {
  total: number
  unresolved: number
  critical: number
  high: number
  by_type: Record<string, number>
}

export async function getAlerts(unresolvedOnly: boolean = false): Promise<Alert[]> {
  const params = unresolvedOnly ? '?unresolved_only=true' : ''
  return (await apiFetch<Alert[]>(`/api/alerts${params}`)) ?? []
}

export async function getAlertStats(): Promise<AlertStats> {
  return (await apiFetch<AlertStats>('/api/alerts/stats')) ?? { total: 0, unresolved: 0, critical: 0, high: 0, by_type: {} }
}

export async function resolveAlert(alertId: string, resolvedBy: string = 'user'): Promise<Alert> {
  const res = await fetch(`${BASE_URL}/api/alerts/${alertId}/resolve?resolved_by=${resolvedBy}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to resolve alert: ${res.status}`)
  return res.json()
}

export async function deleteAlert(alertId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/alerts/${alertId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete alert: ${res.status}`)
}

// Request changes on a task (creates follow-up task)
export async function requestChanges(taskId: string, comment: string): Promise<{ status: string; followup_task_id: string; followup_title: string }> {
  const res = await fetch(`${BASE_URL}/api/tasks/${taskId}/request-changes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ comment })
  })
  if (!res.ok) throw new Error(`Failed: ${res.status}`)
  return res.json()
}
