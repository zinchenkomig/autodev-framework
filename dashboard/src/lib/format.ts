import type { Priority, TaskStatus } from './api'

export const STATUS: Record<TaskStatus, { label: string; tone: string }> = {
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
