const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type Priority = 'critical' | 'high' | 'normal' | 'low'
export type TaskStatus = 'queued' | 'assigned' | 'in_progress' | 'review' | 'done' | 'failed'
export type AgentStatus = 'idle' | 'running' | 'failed'
export type ReleaseStatus = 'draft' | 'staging' | 'approved' | 'deployed'

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
}

export interface Event {
  id: string
  type: string
  payload: Record<string, unknown>
  source: string
  created_at: string
  description?: string
}

export interface Release {
  id: string
  version: string
  status: ReleaseStatus
  tasks: string[]
  release_notes: string
  staging_deployed_at: string | null
  production_deployed_at: string | null
  approved_by: string | null
  created_at: string
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

// Mock data
const MOCK_TASKS: Task[] = [
  { id: '1', title: 'Implement user authentication', description: '', source: 'github_issue', priority: 'high', status: 'in_progress', assigned_to: 'developer', repo: 'backend', issue_number: 12, pr_number: null, created_by: 'pm', created_at: '2026-03-15T10:00:00Z', updated_at: '2026-03-15T12:00:00Z' },
  { id: '2', title: 'Fix login page styling', description: '', source: 'agent_created', priority: 'normal', status: 'queued', assigned_to: null, repo: 'frontend', issue_number: null, pr_number: null, created_by: 'tester', created_at: '2026-03-15T09:00:00Z', updated_at: '2026-03-15T09:00:00Z' },
  { id: '3', title: 'Add rate limiting to API', description: '', source: 'manual', priority: 'critical', status: 'review', assigned_to: 'developer', repo: 'backend', issue_number: 10, pr_number: 25, created_by: 'user', created_at: '2026-03-14T15:00:00Z', updated_at: '2026-03-15T11:00:00Z' },
  { id: '4', title: 'Write unit tests for TaskQueue', description: '', source: 'github_issue', priority: 'normal', status: 'done', assigned_to: 'tester', repo: 'backend', issue_number: 8, pr_number: 22, created_by: 'pm', created_at: '2026-03-14T08:00:00Z', updated_at: '2026-03-14T18:00:00Z' },
  { id: '5', title: 'Setup CI/CD pipeline', description: '', source: 'manual', priority: 'high', status: 'done', assigned_to: 'developer', repo: 'backend', issue_number: 5, pr_number: 18, created_by: 'user', created_at: '2026-03-13T10:00:00Z', updated_at: '2026-03-14T10:00:00Z' },
  { id: '6', title: 'Database migration script', description: '', source: 'github_issue', priority: 'critical', status: 'in_progress', assigned_to: 'developer', repo: 'backend', issue_number: 15, pr_number: null, created_by: 'pm', created_at: '2026-03-15T08:00:00Z', updated_at: '2026-03-15T13:00:00Z' },
  { id: '7', title: 'E2E tests for checkout flow', description: '', source: 'agent_created', priority: 'high', status: 'assigned', assigned_to: 'tester', repo: 'frontend', issue_number: null, pr_number: null, created_by: 'developer', created_at: '2026-03-15T07:00:00Z', updated_at: '2026-03-15T07:30:00Z' },
  { id: '8', title: 'Update API documentation', description: '', source: 'manual', priority: 'low', status: 'queued', assigned_to: null, repo: 'backend', issue_number: null, pr_number: null, created_by: 'pm', created_at: '2026-03-15T06:00:00Z', updated_at: '2026-03-15T06:00:00Z' },
  { id: '9', title: 'Optimize database queries', description: '', source: 'github_issue', priority: 'normal', status: 'queued', assigned_to: null, repo: 'backend', issue_number: 20, pr_number: null, created_by: 'ba', created_at: '2026-03-14T16:00:00Z', updated_at: '2026-03-14T16:00:00Z' },
  { id: '10', title: 'Mobile responsive navbar', description: '', source: 'github_issue', priority: 'normal', status: 'failed', assigned_to: 'developer', repo: 'frontend', issue_number: 18, pr_number: null, created_by: 'user', created_at: '2026-03-14T12:00:00Z', updated_at: '2026-03-15T09:00:00Z' },
]

const MOCK_AGENTS: Agent[] = [
  { id: 'developer', role: 'Developer', status: 'running', current_task_id: '1', current_task_title: 'Implement user authentication', last_run_at: '2026-03-15T12:00:00Z', total_runs: 42, total_failures: 2 },
  { id: 'tester', role: 'Tester', status: 'running', current_task_id: '7', current_task_title: 'E2E tests for checkout flow', last_run_at: '2026-03-15T07:30:00Z', total_runs: 38, total_failures: 5 },
  { id: 'pm', role: 'Product Manager', status: 'idle', current_task_id: null, current_task_title: null, last_run_at: '2026-03-15T06:00:00Z', total_runs: 15, total_failures: 0 },
  { id: 'ba', role: 'Business Analyst', status: 'idle', current_task_id: null, current_task_title: null, last_run_at: '2026-03-14T18:00:00Z', total_runs: 8, total_failures: 1 },
]

const MOCK_EVENTS: Event[] = [
  { id: '1', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-15T13:00:00Z', description: 'Task "Database migration script" assigned to developer' },
  { id: '2', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-15T12:30:00Z', description: 'PR #26 created for "Add rate limiting"' },
  { id: '3', type: 'agent.idle', payload: {}, source: 'orchestrator', created_at: '2026-03-15T12:00:00Z', description: 'Agent pm is now idle' },
  { id: '4', type: 'deploy.staging', payload: {}, source: 'ci', created_at: '2026-03-15T11:00:00Z', description: 'Release v1.2.0-rc1 deployed to staging' },
  { id: '5', type: 'pr.ci.passed', payload: {}, source: 'github', created_at: '2026-03-15T10:30:00Z', description: 'CI passed for PR #25' },
  { id: '6', type: 'bug.found', payload: {}, source: 'tester', created_at: '2026-03-15T09:00:00Z', description: 'Bug found in login page styling' },
  { id: '7', type: 'task.created', payload: {}, source: 'pm', created_at: '2026-03-15T08:30:00Z', description: 'New task created: "Database migration script"' },
  { id: '8', type: 'pr.merged', payload: {}, source: 'github', created_at: '2026-03-15T08:00:00Z', description: 'PR #22 merged: Write unit tests for TaskQueue' },
  { id: '9', type: 'review.passed', payload: {}, source: 'tester', created_at: '2026-03-14T18:00:00Z', description: 'Review passed for "Write unit tests"' },
  { id: '10', type: 'release.ready', payload: {}, source: 'orchestrator', created_at: '2026-03-14T17:00:00Z', description: 'Release v1.2.0-rc1 is ready for approval' },
]

const MOCK_RELEASES: Release[] = [
  { id: '1', version: 'v1.2.0-rc1', status: 'staging', tasks: ['4', '5'], release_notes: 'Unit tests and CI/CD improvements', staging_deployed_at: '2026-03-15T11:00:00Z', production_deployed_at: null, approved_by: null, created_at: '2026-03-14T17:00:00Z' },
  { id: '2', version: 'v1.1.0', status: 'deployed', tasks: ['5'], release_notes: 'CI/CD setup', staging_deployed_at: '2026-03-13T10:00:00Z', production_deployed_at: '2026-03-14T10:00:00Z', approved_by: 'user', created_at: '2026-03-13T08:00:00Z' },
]

const MOCK_STATS: DashboardStats = {
  active_tasks: 4,
  running_agents: 2,
  open_prs: 3,
  latest_release: 'v1.2.0-rc1',
  task_trend: 12,
  agent_trend: 0,
  pr_trend: -1,
}

// API functions (return mock data for now)
export async function getTasks(): Promise<Task[]> {
  // TODO: return await fetch(`${BASE_URL}/api/tasks`).then(r => r.json())
  void BASE_URL
  return MOCK_TASKS
}

export async function getAgents(): Promise<Agent[]> {
  // TODO: return await fetch(`${BASE_URL}/api/agents`).then(r => r.json())
  return MOCK_AGENTS
}

export async function getEvents(): Promise<Event[]> {
  // TODO: return await fetch(`${BASE_URL}/api/events`).then(r => r.json())
  return MOCK_EVENTS
}

export async function getReleases(): Promise<Release[]> {
  // TODO: return await fetch(`${BASE_URL}/api/releases`).then(r => r.json())
  return MOCK_RELEASES
}

export async function getStats(): Promise<DashboardStats> {
  // TODO: return await fetch(`${BASE_URL}/api/dashboard/stats`).then(r => r.json())
  return MOCK_STATS
}
