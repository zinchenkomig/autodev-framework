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

const MOCK_AGENT_MONITORS: AgentMonitor[] = [
  { id: 'pm', role: 'Product Manager', status: 'idle', current_task_id: null, current_task_title: null, last_run_at: '2026-03-15T06:00:00Z', total_runs: 15, total_failures: 0, avg_time: '3m 12s' },
  { id: 'developer', role: 'Developer', status: 'working', current_task_id: '1', current_task_title: 'Implement user authentication', last_run_at: '2026-03-15T12:00:00Z', total_runs: 42, total_failures: 2, avg_time: '18m 45s' },
  { id: 'tester', role: 'Tester', status: 'working', current_task_id: '7', current_task_title: 'E2E tests for checkout flow', last_run_at: '2026-03-15T07:30:00Z', total_runs: 38, total_failures: 5, avg_time: '12m 20s' },
  { id: 'ba', role: 'Business Analyst', status: 'idle', current_task_id: null, current_task_title: null, last_run_at: '2026-03-14T18:00:00Z', total_runs: 8, total_failures: 1, avg_time: '5m 05s' },
  { id: 'release_manager', role: 'Release Manager', status: 'failed', current_task_id: null, current_task_title: null, last_run_at: '2026-03-14T22:00:00Z', total_runs: 11, total_failures: 3, avg_time: '7m 30s' },
]

const MOCK_AGENT_RUNS: AgentRun[] = [
  { id: 'run-1', agent_id: 'developer', agent_role: 'Developer', task_title: 'Implement user authentication', run_status: 'running', duration: null, tokens: null, cost: null, started_at: '2026-03-15T12:00:00Z', finished_at: null },
  { id: 'run-2', agent_id: 'tester', agent_role: 'Tester', task_title: 'E2E tests for checkout flow', run_status: 'running', duration: null, tokens: null, cost: null, started_at: '2026-03-15T07:30:00Z', finished_at: null },
  { id: 'run-3', agent_id: 'release_manager', agent_role: 'Release Manager', task_title: 'Deploy v1.2.0-rc1 to staging', run_status: 'failed', duration: '2m 15s', tokens: 1200, cost: 0.0024, started_at: '2026-03-14T22:00:00Z', finished_at: '2026-03-14T22:02:15Z' },
  { id: 'run-4', agent_id: 'developer', agent_role: 'Developer', task_title: 'Add rate limiting to API', run_status: 'success', duration: '22m 10s', tokens: 8400, cost: 0.0168, started_at: '2026-03-15T09:00:00Z', finished_at: '2026-03-15T09:22:10Z' },
  { id: 'run-5', agent_id: 'tester', agent_role: 'Tester', task_title: 'Write unit tests for TaskQueue', run_status: 'success', duration: '14m 05s', tokens: 5200, cost: 0.0104, started_at: '2026-03-14T16:00:00Z', finished_at: '2026-03-14T16:14:05Z' },
  { id: 'run-6', agent_id: 'pm', agent_role: 'Product Manager', task_title: 'Create sprint backlog', run_status: 'success', duration: '3m 22s', tokens: 2100, cost: 0.0042, started_at: '2026-03-15T06:00:00Z', finished_at: '2026-03-15T06:03:22Z' },
  { id: 'run-7', agent_id: 'ba', agent_role: 'Business Analyst', task_title: 'Analyze checkout funnel metrics', run_status: 'success', duration: '5m 45s', tokens: 3100, cost: 0.0062, started_at: '2026-03-14T18:00:00Z', finished_at: '2026-03-14T18:05:45Z' },
  { id: 'run-8', agent_id: 'developer', agent_role: 'Developer', task_title: 'Setup CI/CD pipeline', run_status: 'success', duration: '31m 02s', tokens: 11200, cost: 0.0224, started_at: '2026-03-13T10:00:00Z', finished_at: '2026-03-13T10:31:02Z' },
  { id: 'run-9', agent_id: 'release_manager', agent_role: 'Release Manager', task_title: 'Release v1.1.0 to production', run_status: 'success', duration: '8m 17s', tokens: 3800, cost: 0.0076, started_at: '2026-03-14T10:00:00Z', finished_at: '2026-03-14T10:08:17Z' },
  { id: 'run-10', agent_id: 'tester', agent_role: 'Tester', task_title: 'Mobile responsive navbar tests', run_status: 'failed', duration: '9m 44s', tokens: 4500, cost: 0.009, started_at: '2026-03-15T09:00:00Z', finished_at: '2026-03-15T09:09:44Z' },
  { id: 'run-11', agent_id: 'pm', agent_role: 'Product Manager', task_title: 'Triage new GitHub issues', run_status: 'success', duration: '2m 58s', tokens: 1800, cost: 0.0036, started_at: '2026-03-14T09:00:00Z', finished_at: '2026-03-14T09:02:58Z' },
  { id: 'run-12', agent_id: 'developer', agent_role: 'Developer', task_title: 'Database migration script', run_status: 'success', duration: '19m 33s', tokens: 7600, cost: 0.0152, started_at: '2026-03-15T08:00:00Z', finished_at: '2026-03-15T08:19:33Z' },
  { id: 'run-13', agent_id: 'ba', agent_role: 'Business Analyst', task_title: 'Write user story: rate limiting', run_status: 'failed', duration: '4m 12s', tokens: 2400, cost: 0.0048, started_at: '2026-03-14T14:00:00Z', finished_at: '2026-03-14T14:04:12Z' },
  { id: 'run-14', agent_id: 'release_manager', agent_role: 'Release Manager', task_title: 'Prepare release notes v1.2.0', run_status: 'success', duration: '6m 50s', tokens: 3200, cost: 0.0064, started_at: '2026-03-14T17:00:00Z', finished_at: '2026-03-14T17:06:50Z' },
  { id: 'run-15', agent_id: 'tester', agent_role: 'Tester', task_title: 'Regression tests after auth PR', run_status: 'cancelled', duration: '1m 05s', tokens: 600, cost: 0.0012, started_at: '2026-03-15T11:00:00Z', finished_at: '2026-03-15T11:01:05Z' },
]

const MOCK_EVENTS: Event[] = [
  { id: '1', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-15T13:00:00Z', description: 'Task "Database migration script" assigned to developer', related_id: '6', related_type: 'task' },
  { id: '2', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-15T12:30:00Z', description: 'PR #26 created for "Add rate limiting"', related_id: '26', related_type: 'pr' },
  { id: '3', type: 'agent.idle', payload: {}, source: 'orchestrator', created_at: '2026-03-15T12:00:00Z', description: 'Agent pm transitioned to idle state' },
  { id: '4', type: 'deploy.staging', payload: {}, source: 'ci', created_at: '2026-03-15T11:00:00Z', description: 'Release v1.2.0-rc1 deployed to staging', related_id: '2', related_type: 'release' },
  { id: '5', type: 'pr.ci.passed', payload: {}, source: 'github', created_at: '2026-03-15T10:30:00Z', description: 'CI passed for PR #25', related_id: '25', related_type: 'pr' },
  { id: '6', type: 'bug.found', payload: {}, source: 'tester', created_at: '2026-03-15T09:00:00Z', description: 'Bug found: login page styling breaks on mobile', related_id: '2', related_type: 'task' },
  { id: '7', type: 'task.created', payload: {}, source: 'pm', created_at: '2026-03-15T08:30:00Z', description: 'New task created: "Database migration script"', related_id: '6', related_type: 'task' },
  { id: '8', type: 'pr.merged', payload: {}, source: 'github', created_at: '2026-03-15T08:00:00Z', description: 'PR #22 merged: Write unit tests for TaskQueue', related_id: '22', related_type: 'pr' },
  { id: '9', type: 'agent.running', payload: {}, source: 'orchestrator', created_at: '2026-03-15T07:30:00Z', description: 'Agent tester started task "E2E tests for checkout flow"' },
  { id: '10', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-15T07:25:00Z', description: 'Task "E2E tests for checkout flow" assigned to tester', related_id: '7', related_type: 'task' },
  { id: '11', type: 'pr.review_requested', payload: {}, source: 'developer', created_at: '2026-03-15T07:00:00Z', description: 'Review requested for PR #25 from tester', related_id: '25', related_type: 'pr' },
  { id: '12', type: 'task.in_progress', payload: {}, source: 'developer', created_at: '2026-03-15T06:30:00Z', description: 'Task "Database migration script" moved to in_progress', related_id: '6', related_type: 'task' },
  { id: '13', type: 'release.ready', payload: {}, source: 'orchestrator', created_at: '2026-03-14T17:00:00Z', description: 'Release v1.2.0-rc1 is ready for approval', related_id: '2', related_type: 'release' },
  { id: '14', type: 'deploy.production', payload: {}, source: 'ci', created_at: '2026-03-14T10:00:00Z', description: 'Release v1.1.0 deployed to production', related_id: '2', related_type: 'release' },
  { id: '15', type: 'release.approved', payload: {}, source: 'user', created_at: '2026-03-14T09:30:00Z', description: 'Release v1.1.0 approved by user', related_id: '2', related_type: 'release' },
  { id: '16', type: 'pr.ci.failed', payload: {}, source: 'github', created_at: '2026-03-14T09:00:00Z', description: 'CI failed for PR #20 — 3 tests failed', related_id: '20', related_type: 'pr' },
  { id: '17', type: 'bug.resolved', payload: {}, source: 'developer', created_at: '2026-03-14T08:30:00Z', description: 'Bug resolved: navbar overflow on small screens' },
  { id: '18', type: 'task.done', payload: {}, source: 'developer', created_at: '2026-03-14T08:00:00Z', description: 'Task "Setup CI/CD pipeline" marked done', related_id: '5', related_type: 'task' },
  { id: '19', type: 'pr.merged', payload: {}, source: 'github', created_at: '2026-03-14T07:45:00Z', description: 'PR #18 merged: Setup CI/CD pipeline', related_id: '18', related_type: 'pr' },
  { id: '20', type: 'agent.failed', payload: {}, source: 'developer', created_at: '2026-03-14T06:00:00Z', description: 'Agent developer failed on task "Mobile responsive navbar"' },
  { id: '21', type: 'bug.found', payload: {}, source: 'tester', created_at: '2026-03-13T18:00:00Z', description: 'Bug found: API rate limit not applied to /health endpoint', related_id: '3', related_type: 'task' },
  { id: '22', type: 'pr.ci.passed', payload: {}, source: 'github', created_at: '2026-03-13T17:00:00Z', description: 'CI passed for PR #18', related_id: '18', related_type: 'pr' },
  { id: '23', type: 'task.created', payload: {}, source: 'ba', created_at: '2026-03-13T16:00:00Z', description: 'New task created: "Optimize database queries"', related_id: '9', related_type: 'task' },
  { id: '24', type: 'deploy.staging', payload: {}, source: 'ci', created_at: '2026-03-13T15:00:00Z', description: 'Release v1.1.0 deployed to staging', related_id: '2', related_type: 'release' },
  { id: '25', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-13T14:00:00Z', description: 'PR #22 created: Write unit tests for TaskQueue', related_id: '22', related_type: 'pr' },
  { id: '26', type: 'agent.running', payload: {}, source: 'orchestrator', created_at: '2026-03-13T13:30:00Z', description: 'Agent tester started task "Write unit tests for TaskQueue"' },
  { id: '27', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-13T13:00:00Z', description: 'Task "Write unit tests for TaskQueue" assigned to tester', related_id: '4', related_type: 'task' },
  { id: '28', type: 'task.created', payload: {}, source: 'pm', created_at: '2026-03-13T12:00:00Z', description: 'New task created: "Write unit tests for TaskQueue"', related_id: '4', related_type: 'task' },
  { id: '29', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-13T11:00:00Z', description: 'PR #18 created: Setup CI/CD pipeline', related_id: '18', related_type: 'pr' },
  { id: '30', type: 'task.in_progress', payload: {}, source: 'developer', created_at: '2026-03-13T10:30:00Z', description: 'Task "Setup CI/CD pipeline" moved to in_progress', related_id: '5', related_type: 'task' },
  { id: '31', type: 'release.created', payload: {}, source: 'pm', created_at: '2026-03-13T10:00:00Z', description: 'Release v1.1.0 created (draft)', related_id: '2', related_type: 'release' },
  { id: '32', type: 'agent.idle', payload: {}, source: 'orchestrator', created_at: '2026-03-13T09:00:00Z', description: 'Agent ba completed analysis and returned to idle' },
  { id: '33', type: 'bug.triaged', payload: {}, source: 'ba', created_at: '2026-03-12T17:00:00Z', description: 'Bug triaged: session token expiry too short — marked high priority' },
  { id: '34', type: 'deploy.production', payload: {}, source: 'ci', created_at: '2026-03-12T15:00:00Z', description: 'Release v1.0.2 deployed to production', related_id: '1', related_type: 'release' },
  { id: '35', type: 'release.approved', payload: {}, source: 'user', created_at: '2026-03-12T14:30:00Z', description: 'Release v1.0.2 approved by user', related_id: '1', related_type: 'release' },
]

const MOCK_RELEASES: Release[] = [
  {
    id: '1',
    version: 'v1.0.2',
    status: 'deployed',
    tasks: ['4', '5'],
    prs: [
      { number: 18, title: 'Setup CI/CD pipeline', author: 'developer', url: 'https://github.com/org/repo/pull/18', merged_at: '2026-03-12T12:00:00Z' },
      { number: 15, title: 'Fix session token expiry', author: 'developer', url: 'https://github.com/org/repo/pull/15', merged_at: '2026-03-11T10:00:00Z' },
    ],
    release_notes: `## v1.0.2 — Hotfix & CI Setup

### Bug Fixes
- Fixed session token expiry being too short (was 15 min, now 24h)
- Fixed CORS headers missing on /api/auth endpoint

### Infrastructure
- Setup GitHub Actions CI/CD pipeline
- Added automated test runs on every PR
- Added staging environment deployment on merge to main

### Dependencies
- Updated \`fastapi\` to 0.110.0
- Updated \`pydantic\` to 2.6.0`,
    testing_plan: `## Testing Plan for v1.0.2

### Smoke Tests
- [ ] Login flow works end-to-end
- [ ] Session persists for 24 hours
- [ ] API returns correct CORS headers

### Regression Tests
- [ ] All existing API endpoints respond correctly
- [ ] CI pipeline triggers on PR creation

### Sign-off
- Developer: self-review complete
- Tester: smoke tests passed`,
    ba_report: `## BA Report — v1.0.2

**Analysis Date:** 2026-03-11

### Business Impact
This hotfix addresses critical UX issues reported by early users. Session expiry at 15 minutes was causing productivity loss.

### Risk Assessment
- **Low risk:** Targeted hotfix, no new features
- All changes are backward-compatible

### Recommendation
Approved for production deployment.`,
    tester_report: `## QA Report — v1.0.2

**Test Date:** 2026-03-12
**Environment:** Staging

### Results
- ✅ 12/12 smoke tests passed
- ✅ 45/45 regression tests passed
- ✅ CORS headers verified in browser

### Sign-off
QA approved. Ready for production.`,
    staging_deployed_at: '2026-03-12T10:00:00Z',
    production_deployed_at: '2026-03-12T15:00:00Z',
    approved_by: 'user',
    created_at: '2026-03-11T08:00:00Z',
  },
  {
    id: '2',
    version: 'v1.1.0',
    status: 'deployed',
    tasks: ['4', '5'],
    prs: [
      { number: 22, title: 'Write unit tests for TaskQueue', author: 'tester', url: 'https://github.com/org/repo/pull/22', merged_at: '2026-03-15T08:00:00Z' },
      { number: 18, title: 'Setup CI/CD pipeline', author: 'developer', url: 'https://github.com/org/repo/pull/18', merged_at: '2026-03-14T07:45:00Z' },
    ],
    release_notes: `## v1.1.0 — Quality & Automation

### New Features
- Added comprehensive unit test suite for TaskQueue
- Automated CI/CD pipeline with multi-stage deployment

### Improvements
- Test coverage increased from 42% to 78%
- Build time reduced by 30% via parallel test execution
- Added pre-commit hooks for linting

### Bug Fixes
- Fixed race condition in TaskQueue when processing concurrent tasks
- Fixed memory leak in long-running agent processes`,
    testing_plan: `## Testing Plan for v1.1.0

### Unit Tests
- [ ] TaskQueue enqueue/dequeue operations
- [ ] Concurrent task handling (race condition fix)
- [ ] Agent lifecycle: start, stop, restart

### Integration Tests
- [ ] Full pipeline from task creation to completion
- [ ] CI workflow triggers correctly

### Performance Tests
- [ ] Build time benchmark (<5 min target)
- [ ] Memory usage under load`,
    ba_report: `## BA Report — v1.1.0

**Analysis Date:** 2026-03-13

### Business Value
Improved test coverage reduces regression risk by ~40%. CI automation saves ~2h of manual testing per release.

### Metrics
- Estimated time saved: 2h/release
- Bug escape rate target: <5%

### Recommendation
High value, low risk. Recommend immediate deployment.`,
    tester_report: `## QA Report — v1.1.0

**Test Date:** 2026-03-14
**Environment:** Staging

### Results
- ✅ 28/28 unit tests passed
- ✅ 15/15 integration tests passed
- ⚠️ 1 flaky test (timeout in CI) — documented, non-blocking

### Sign-off
QA approved with minor note on flaky test.`,
    staging_deployed_at: '2026-03-13T15:00:00Z',
    production_deployed_at: '2026-03-14T10:00:00Z',
    approved_by: 'user',
    created_at: '2026-03-13T10:00:00Z',
  },
  {
    id: '3',
    version: 'v1.2.0-rc1',
    status: 'staging',
    tasks: ['3', '1'],
    prs: [
      { number: 25, title: 'Add rate limiting to API', author: 'developer', url: 'https://github.com/org/repo/pull/25', merged_at: null },
      { number: 26, title: 'Implement user authentication', author: 'developer', url: 'https://github.com/org/repo/pull/26', merged_at: null },
    ],
    release_notes: `## v1.2.0-rc1 — Security & Auth

### New Features
- JWT-based user authentication system
- Role-based access control (RBAC)
- Rate limiting on all API endpoints (100 req/min per IP)
- API key management for service accounts

### Security
- Added request signing for internal service communication
- Implemented token refresh flow
- Added brute-force protection on login endpoint

### Breaking Changes
- All API endpoints now require authentication
- New \`Authorization: Bearer <token>\` header required`,
    testing_plan: `## Testing Plan for v1.2.0

### Security Tests
- [ ] SQL injection on login endpoint
- [ ] JWT token tampering
- [ ] Rate limiting enforcement (>100 req/min blocked)
- [ ] RBAC: admin can do X, viewer cannot

### Functional Tests
- [ ] User registration and login flow
- [ ] Token refresh flow
- [ ] API key creation and usage

### Load Tests
- [ ] 500 concurrent users
- [ ] Rate limiter holds under load`,
    ba_report: null,
    tester_report: null,
    staging_deployed_at: '2026-03-15T11:00:00Z',
    production_deployed_at: null,
    approved_by: null,
    created_at: '2026-03-14T17:00:00Z',
  },
  {
    id: '4',
    version: 'v1.3.0-draft',
    status: 'draft',
    tasks: ['6', '9'],
    prs: [],
    release_notes: `## v1.3.0 — Performance & Data

### Planned Features
- Database query optimization (N+1 fixes)
- Redis caching layer for frequent queries
- Database migration framework
- Query performance monitoring dashboard

### Goals
- Reduce average API response time by 50%
- Support 10x current database load`,
    testing_plan: `## Testing Plan for v1.3.0

### Performance Tests
- [ ] API response time baseline vs optimized
- [ ] Database query count before/after
- [ ] Cache hit rate monitoring

### Migration Tests
- [ ] Migration runs cleanly on empty DB
- [ ] Migration is reversible (rollback tested)`,
    ba_report: null,
    tester_report: null,
    staging_deployed_at: null,
    production_deployed_at: null,
    approved_by: null,
    created_at: '2026-03-15T08:00:00Z',
  },
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

// ---------------------------------------------------------------------------
// Generic fetch helper with mock fallback
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, fallback: T, options?: RequestInit): Promise<T> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
    if (!res.ok) {
      console.warn(`[api] ${path} returned ${res.status}, falling back to mock`)
      return fallback
    }
    return (await res.json()) as T
  } catch (err) {
    console.warn(`[api] ${path} failed (${err}), falling back to mock`)
    return fallback
  }
}

// ---------------------------------------------------------------------------
// API functions — real endpoints with mock fallback
// ---------------------------------------------------------------------------

export async function getTasks(): Promise<Task[]> {
  return apiFetch<Task[]>('/api/v1/tasks/', MOCK_TASKS)
}

export async function getAgents(): Promise<Agent[]> {
  return apiFetch<Agent[]>('/api/v1/agents/', MOCK_AGENTS)
}

export async function getEvents(): Promise<Event[]> {
  return apiFetch<Event[]>('/api/v1/events/', MOCK_EVENTS)
}

export async function getReleases(): Promise<Release[]> {
  return apiFetch<Release[]>('/api/v1/releases/', MOCK_RELEASES)
}

export async function getRelease(id: string): Promise<Release | null> {
  const fallback = MOCK_RELEASES.find(r => r.id === id) ?? null
  return apiFetch<Release | null>(`/api/v1/releases/${id}`, fallback)
}

export async function getStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>('/api/dashboard/stats', MOCK_STATS)
}

export async function getAgentMonitors(): Promise<AgentMonitor[]> {
  // Derives from /api/v1/agents/ — map to AgentMonitor shape with fallback
  const agents = await apiFetch<Agent[]>('/api/v1/agents/', MOCK_AGENTS)
  if (agents === MOCK_AGENTS) return MOCK_AGENT_MONITORS
  return agents.map(a => ({
    id: a.id,
    role: a.role,
    status: (a.status === 'running' ? 'working' : a.status) as AgentMonitorStatus,
    current_task_id: a.current_task_id,
    current_task_title: null,
    last_run_at: a.last_run_at,
    total_runs: a.total_runs,
    total_failures: a.total_failures,
    avg_time: null as unknown as string,
  }))
}

export async function getAgentRuns(): Promise<AgentRun[]> {
  // Agent runs endpoint not yet implemented in backend — use mock
  return MOCK_AGENT_RUNS
}

// ---------------------------------------------------------------------------
// Write operations
// ---------------------------------------------------------------------------

export async function createTask(data: Partial<Task>): Promise<Task> {
  const res = await fetch(`${BASE_URL}/api/v1/tasks/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create task: ${res.status}`)
  return res.json()
}

export async function updateTask(id: string, data: Partial<Task>): Promise<Task> {
  const res = await fetch(`${BASE_URL}/api/v1/tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to update task: ${res.status}`)
  return res.json()
}

export async function createRelease(data: { version: string; release_notes?: string; tasks?: string[] }): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/v1/releases/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create release: ${res.status}`)
  return res.json()
}

export async function approveRelease(id: string, approvedBy = 'user'): Promise<Release> {
  const res = await fetch(`${BASE_URL}/api/v1/releases/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved_by: approvedBy }),
  })
  if (!res.ok) throw new Error(`Failed to approve release: ${res.status}`)
  return res.json()
}

export async function triggerAgent(agentId: string): Promise<{ event_id: string; agent_id: string; message: string }> {
  const res = await fetch(`${BASE_URL}/api/v1/agents/${agentId}/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`Failed to trigger agent: ${res.status}`)
  return res.json()
}
