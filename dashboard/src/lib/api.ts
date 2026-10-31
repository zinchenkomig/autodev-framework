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

export interface TaskRef {
  id: string
  ticket_number: number
  title: string
  status: TaskStatus
}

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
  qa: { ok: boolean; problems: string[]; skipped: string | null } | null
  test_plan: string[]
  plan_checked: number[]
  plan_earlier: number[] // ticked on the previous version; to check again
  verified_at: string | null
  plan_refreshing: boolean
  waiting_for: TaskRef[]
  depends_on: string[]
  parent: TaskRef | null
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

export interface Artifact {
  id: string
  kind: string
  name: string
  url: string
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

/** Create the repo on GitHub; a brief becomes the project's first task. */
export interface NewRepo {
  private: boolean
  brief: string
}

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

/** What a chat is about; decides the agent's context and the actions it may propose. */
export type ChatSubject = 'task'

export interface ChatProposal {
  action: string
  label: string
  title: string
  description: string
  state: 'pending' | 'applied' | 'rejected'
  result: { task_id?: string; ticket_number?: number } | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'event' | 'error'
  text: string
  quote: string | null
  proposals: ChatProposal[]
  created_at: string
}

export interface ChatOutcome {
  label: string
  title: string
  state: 'applied' | 'rejected'
  task_id: string | null
  ticket_number: number | null
}

export interface Chat {
  id: string
  subject: ChatSubject
  subject_id: string | null
  project_id: string | null
  title: string
  question: string | null // the owner's first message
  outcome: ChatOutcome[] // decided proposals: what the chat came to
  pending: number // proposals waiting for the owner
  state: 'idle' | 'queued' | 'answering'
  activity: string | null
  stopping: boolean
  messages: ChatMessage[]
  created_at: string
  updated_at: string
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
  if (res.status === 401 && typeof window !== 'undefined') {
    // The session is gone (signed out, or the password changed): back to the login form.
    window.location.href = `/api/auth/login?next=${encodeURIComponent(location.pathname + location.search)}`
  }
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
  createProject: (p: ProjectInput, newRepo?: NewRepo) =>
    post<Project>('/api/projects/', newRepo ? { ...p, new_repo: newRepo } : p),
  updateProject: (id: string, p: Omit<ProjectInput, 'id'>) =>
    request<Project>(`/api/projects/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),
  release: (id: string) => post<Release>(`/api/projects/${id}/release`),
  releases: (projectId?: string) =>
    request<Release[]>(`/api/releases/${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`),

  tasks: (projectId?: string) =>
    request<Task[]>(`/api/tasks/?limit=500${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ''}`),
  tasksIn: (statuses: TaskStatus[]) =>
    request<Task[]>(`/api/tasks/?limit=500${statuses.map((s) => `&status=${s}`).join('')}`),
  task: (id: string) => request<Task>(`/api/tasks/${id}`),
  children: (id: string) => request<Task[]>(`/api/tasks/?parent_id=${encodeURIComponent(id)}`),
  createTask: (t: { title: string; description: string; project_id: string; repo?: string | null; priority: Priority }) =>
    post<Task>('/api/tasks/', t),
  updateTask: (id: string, t: Partial<Pick<Task, 'title' | 'description' | 'priority'>>) =>
    request<Task>(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(t) }),
  deleteTask: (id: string) => request<void>(`/api/tasks/${id}`, { method: 'DELETE' }),
  cancelTask: (id: string) => post<Task>(`/api/tasks/${id}/cancel`),
  retryTask: (id: string) => post<Task>(`/api/tasks/${id}/retry`),
  feedback: (id: string, text: string) => post<Task>(`/api/tasks/${id}/feedback`, { text }),
  checkStep: (id: string, step: number, done: boolean) => post<Task>(`/api/tasks/${id}/plan/${step}`, { done }),
  refreshPlan: (id: string) => post<Task>(`/api/tasks/${id}/plan/refresh`),
  verifyTask: (id: string, verified: boolean) => post<Task>(`/api/tasks/${id}/verify`, { verified }),
  logs: (id: string, after?: string) =>
    request<LogEntry[]>(`/api/tasks/${id}/logs${after ? `?after=${encodeURIComponent(after)}` : ''}`),
  artifacts: (id: string) => request<Artifact[]>(`/api/tasks/${id}/artifacts`),
  artifactUrl: (path: string) => `${BASE}${path}`,
  transitions: (id: string) => request<Transition[]>(`/api/tasks/${id}/transitions`),

  chats: (subject: ChatSubject, subjectId: string) =>
    request<Chat[]>(`/api/chats/?subject=${subject}&subject_id=${encodeURIComponent(subjectId)}`),
  /** A new chat with its first question. */
  createChat: (subject: ChatSubject, subjectId: string, text: string, quote?: string | null) =>
    post<Chat>('/api/chats/', { subject, subject_id: subjectId, text, quote: quote ?? null }),
  chat: (id: string) => request<Chat>(`/api/chats/${id}`),
  deleteChat: (id: string) => request<void>(`/api/chats/${id}`, { method: 'DELETE' }),
  sendChat: (id: string, text: string, quote?: string | null) =>
    post<Chat>(`/api/chats/${id}/messages`, { text, quote: quote ?? null }),
  stopChat: (id: string) => post<Chat>(`/api/chats/${id}/stop`),
  decideProposal: (id: string, messageId: string, index: number, approve: boolean) =>
    post<Chat>(`/api/chats/${id}/messages/${messageId}/proposals/${index}`, { approve }),

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
