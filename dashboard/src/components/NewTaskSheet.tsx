'use client'

import { MessageCircleQuestion } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type Priority, type Project, type Task } from '@/lib/api'
import { MODELS, PRIORITY } from '@/lib/format'
import { Button, ErrorNote, Field, Sheet, inputClass } from './ui'


export function NewTaskSheet({
  open,
  onClose,
  projects,
  defaultProject,
  onCreated,
  onDiscuss,
}: {
  open: boolean
  onClose: () => void
  projects: Project[]
  defaultProject: string | null
  onCreated: (task: Task) => void
  /** Talk it over before creating a task; `chatId` is the chat started with the typed text. */
  onDiscuss: (projectId: string, chatId: string | null) => void
}) {
  const [projectId, setProjectId] = useState('')
  const [text, setText] = useState('')
  const [priority, setPriority] = useState<Priority>('normal')
  const [pm, setPm] = useState(true)
  const [model, setModel] = useState('') // '' — the project's model
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Paused projects still accept tasks; they just wait until the project is enabled.
  const ordered = [...projects.filter((p) => p.enabled), ...projects.filter((p) => !p.enabled)]
  useEffect(() => {
    if (!open) return
    setError(null)
    setProjectId((current) =>
      current && ordered.some((p) => p.id === current) ? current : (defaultProject ?? ordered[0]?.id ?? ''),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const project = ordered.find((p) => p.id === projectId)
  // Each project has its own default; switching the project brings it back.
  useEffect(() => {
    if (project) setPm(project.pm)
  }, [project?.id, project?.pm]) // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || !project) return
    // First line is the title, the rest is the description (like a commit message).
    const [first, ...rest] = trimmed.split('\n')
    const title = first.length > 140 ? `${first.slice(0, 137)}…` : first
    const description = [first.length > 140 ? first : '', rest.join('\n')].filter(Boolean).join('\n').trim()
    setBusy(true)
    setError(null)
    try {
      const task = await api.createTask({ title, description, project_id: project.id, priority, pm, model: model || null })
      setText('')
      setPriority('normal')
      setModel('')
      onCreated(task)
      onClose()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function discuss() {
    if (!project) return
    const trimmed = text.trim()
    setBusy(true)
    setError(null)
    try {
      const chat = trimmed ? await api.createChat('project', project.id, trimmed) : null
      setText('')
      onDiscuss(project.id, chat?.id ?? null)
      onClose()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Новая задача">
      {ordered.length === 0 ? (
        <p className="text-sm text-muted">Сначала добавьте проект на вкладке «Проекты».</p>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Что сделать" hint="Первая строка — заголовок, дальше — подробности. Можно надиктовать с клавиатуры.">
            <textarea
              autoFocus
              required
              rows={6}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={'Добавь поиск по имени на страницу пользователей\nПоиск без учёта регистра, с подсветкой совпадений'}
              className={inputClass}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e)
              }}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Проект">
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className={inputClass}>
                {ordered.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.enabled ? '' : ' (на паузе)'}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Приоритет">
              <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)} className={inputClass}>
                {(Object.keys(PRIORITY) as Priority[]).map((p) => (
                  <option key={p} value={p}>
                    {PRIORITY[p]}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Модель">
            <select value={model} onChange={(e) => setModel(e.target.value)} className={inputClass}>
              <option value="">Как в проекте{project?.model ? ` (${MODELS[project.model] ?? project.model})` : ''}</option>
              {Object.entries(MODELS).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          <label className="flex items-start gap-3">
            <input type="checkbox" checked={pm} onChange={(e) => setPm(e.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--accent)]" />
            <span className="text-sm">
              PM продумает задачу
              <span className="block text-muted">
                Ответит на продуктовые вопросы до кода. Выключите для очевидной задачи или если хотите решить всё сами.
              </span>
            </span>
          </label>
          {project && !project.enabled && (
            <p className="text-sm text-warn">Проект на паузе — задача подождёт, пока его не включат.</p>
          )}
          <ErrorNote error={error} />
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={discuss} className="flex-1">
              <MessageCircleQuestion size={16} /> Обсудить
            </Button>
            <Button type="submit" variant="primary" disabled={busy || !text.trim()} className="flex-1">
              {busy ? 'Создаю…' : 'В работу'}
            </Button>
          </div>
          <p className="text-center text-xs text-muted">
            «Обсудить» — сначала посоветоваться с агентом: задача появится, только когда вы её подтвердите.
          </p>
        </form>
      )}
    </Sheet>
  )
}
