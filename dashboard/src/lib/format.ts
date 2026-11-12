import type { Priority, Task, TaskStatus } from './api'

export const STATUS: Record<TaskStatus, { label: string; tone: string }> = {
  proposed: { label: 'Предложение', tone: 'info' },
  queued: { label: 'В очереди', tone: 'neutral' },
  in_progress: { label: 'В работе', tone: 'info' },
  ci: { label: 'Проверка CI', tone: 'warn' },
  deploying: { label: 'Выкатывается', tone: 'warn' },
  on_stage: { label: 'На stage', tone: 'ok' },
  released: { label: 'В проде', tone: 'done' },
  failed: { label: 'Ошибка', tone: 'bad' },
  cancelled: { label: 'Отменена', tone: 'neutral' },
}

export const PRIORITY: Record<Priority, string> = {
  critical: 'Срочно',
  high: 'Высокий',
  normal: 'Обычный',
  low: 'Низкий',
}

export const SCOUT_KIND: Record<string, string> = {
  bug: 'Баг',
  ux: 'Удобство',
  feature: 'Не хватает',
  simplify: 'Лишнее',
  tests: 'Тесты',
  debt: 'Чистота кода',
}

export const FIX_KIND: Record<string, string> = {
  ci: 'чиню CI',
  conflict: 'решаю конфликт',
  feedback: 'правки',
  retry: 'повтор',
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return ''
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 45) return 'только что'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} мин назад`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} ч назад`
  const days = Math.round(hours / 24)
  return `${days} дн назад`
}

export function time(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

/** Russian plural: plural(5, ['задача', 'задачи', 'задач']) → 'задач'. */
export function plural(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1]
  return forms[2]
}

/** Claude models offered for a task; the API takes any name the CLI does. */
export const MODELS: Record<string, string> = { opus: 'Opus', sonnet: 'Sonnet', haiku: 'Haiku' }

/** Enabled projects first: a paused one can still be picked, it just comes last. */
export function enabledFirst<T extends { enabled: boolean }>(projects: T[]): T[] {
  return [...projects.filter((p) => p.enabled), ...projects.filter((p) => !p.enabled)]
}

// What the API allows in each status (autodev/api/routes/tasks.py). Mirrored here so that a
// button shows only when its request would go through; change both together.

/** The change is in the stage branch: deploying, on stage or released. */
export const isMerged = (status: TaskStatus) => ['deploying', 'on_stage', 'released'].includes(status)
/** An agent or CI is busy with the task, or it waits for one. */
export const isRunning = (status: TaskStatus) => ['queued', 'in_progress', 'ci', 'deploying'].includes(status)
export const canCancel = (status: TaskStatus) => ['queued', 'in_progress', 'ci'].includes(status)
export const canRetry = (status: TaskStatus) => ['failed', 'cancelled'].includes(status)
export const canDelete = (status: TaskStatus) => !['in_progress', 'ci', 'deploying'].includes(status)
/** Nobody has started on it: the task itself can still be edited. */
export const notStarted = (task: Task) => ['queued', 'proposed'].includes(task.status) && !task.branch

/** What the owner's feedback turns into; null when the API takes none right now. */
export type FeedbackKind = 'follow_up' | 'same_pr' | 'description'

export function feedbackKind(task: Task): FeedbackKind | null {
  if (isMerged(task.status)) return 'follow_up' // a new task linked to this one
  if (['ci', 'failed', 'cancelled'].includes(task.status) && task.pr_number) return 'same_pr' // one more round on its PR
  if (notStarted(task)) return 'description' // appended to the task's text
  return null
}

/** What the owner asked for: a follow-up's description without the "Follow-up to #N" footer. */
export function followUpRequest(task: Task): string {
  return (task.description ?? '').split('\n\n---\n')[0].trim()
}
