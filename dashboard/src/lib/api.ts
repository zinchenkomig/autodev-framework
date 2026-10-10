// Typed client for the AutoDev API. Same origin in production (ingress routes /api);
// set NEXT_PUBLIC_API_URL for local development.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

export type TaskStatus =
  | 'queued'
  | 'in_progress'
  | 'ci'
  | 'deploying'
  | 'on_stage'
  | 'released'
  | 'failed'
  | 'cancelled'

export type Priority = 'critical' | 'high' | 'normal' | 'low'

export interface Task {
  id: string
  ticket_number: number
  title: string
  description: string | null
  project_id: string | null
  repo: string | null
  source: string
  priority: Priority
  status: TaskStatus
  assigned_to: string | null
  branch: string | null
  pr_number: number | null
  pr_url: string | null
  summary: string | null
  error: string | null
  attempts: number
  pending_fix: string | null
  depends_on: string[]
  created_by: string | null
  created_at: string
  status_changed_at: string
  updated_at: string
}

export interface LogEntry {
  id: string
  agent_id: string
  level: string
  message: string
  details: string | null
  created_at: string
}

export interface Transition {
  id: string
  from_status: string
  to_status: string
  reason: string | null
  triggered_by: string | null
  created_at: string
}

export interface Repo {
  name: string
  role: string
  version_url?: string | null
  setup?: string | null
}

export interface Project {
  id: string
  name: string
  repos: Repo[]
  base_branch: string
  prod_branch: string
  stage_url: string | null
  smoke_paths: string[]
  instructions: string | null
  model: string | null
  max_parallel: number
  enabled: boolean
  task_counts: Partial<Record<TaskStatus, number>>
}

export type ProjectInput = Omit<Project, 'task_counts'>

export interface Release {
  id: string
  project_id: string | null
  version: string
  status: 'pending' | 'deployed' | 'failed'
  tasks: string[]
  release_notes: string | null
  release_prs: { repo: string; pr_number: number; pr_url: string; merged: boolean }[]
  error: string | null
  created_by: string | null
  production_deployed_at: string | null
  created_at: string
}

export interface SystemStatus {
  worker_online: boolean
  worker_last_seen: string | null
  developers_enabled: boolean
  paused_until: string | null
  slots: { id: string; status: string; task_id: string | null; task_ticket: number | null; task_title: string | null }[]
}

export interface TelegramSettings {
  bot_token: string
  owner_chat_id: string
  webhook_secret: string
  webhook_url: string
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    cache: 'no-store',
  })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  status: () => request<SystemStatus>('/api/status/'),

  projects: () => request<Project[]>('/api/projects/'),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (p: ProjectInput) => post<Project>('/api/projects/', p),
  updateProject: (id: string, p: Omit<ProjectInput, 'id'>) =>
    request<Project>(`/api/projects/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),
  release: (id: string) => post<Release>(`/api/projects/${id}/release`),
  releases: (projectId?: string) =>
    request<Release[]>(`/api/releases/${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`),

  tasks: (projectId?: string) =>
    request<Task[]>(`/api/tasks/?limit=500${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ''}`),
  task: (id: string) => request<Task>(`/api/tasks/${id}`),
  createTask: (t: { title: string; description: string; project_id: string; repo?: string | null; priority: Priority }) =>
    post<Task>('/api/tasks/', t),
  updateTask: (id: string, t: Partial<Pick<Task, 'title' | 'description' | 'priority'>>) =>
    request<Task>(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(t) }),
  deleteTask: (id: string) => request<void>(`/api/tasks/${id}`, { method: 'DELETE' }),
  cancelTask: (id: string) => post<Task>(`/api/tasks/${id}/cancel`),
  retryTask: (id: string) => post<Task>(`/api/tasks/${id}/retry`),
  feedback: (id: string, text: string) => post<Task>(`/api/tasks/${id}/feedback`, { text }),
  logs: (id: string, after?: string) =>
    request<LogEntry[]>(`/api/tasks/${id}/logs${after ? `?after=${encodeURIComponent(after)}` : ''}`),
  transitions: (id: string) => request<Transition[]>(`/api/tasks/${id}/transitions`),

  toggleDevelopers: () => post<{ enabled: boolean }>('/api/agents/developer/toggle'),

  telegram: () => request<TelegramSettings>('/api/settings/telegram'),
  saveTelegram: (s: TelegramSettings) =>
    request<{ status: string }>('/api/settings/telegram', { method: 'PUT', body: JSON.stringify(s) }),
  testTelegram: (s: { bot_token?: string; owner_chat_id?: string }) =>
    post<{ success: boolean; message: string; bot_username: string | null }>('/api/settings/telegram/test', s),
  detectChat: (bot_token?: string) =>
    post<{ chat_id: string; name: string }>('/api/settings/telegram/detect-chat', { bot_token }),
  setWebhook: () => post<{ status: string; webhook_url: string }>('/api/settings/telegram/webhook'),
}
