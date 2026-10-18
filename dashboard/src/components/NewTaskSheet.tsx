'use client'

import { useEffect, useState } from 'react'
import { api, type Priority, type Project, type Task } from '@/lib/api'
import { PRIORITY } from '@/lib/format'
import { Button, ErrorNote, Field, Sheet, inputClass } from './ui'


export function NewTaskSheet({
  open,
  onClose,
  projects,
  defaultProject,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  projects: Project[]
  defaultProject: string | null
  onCreated: (task: Task) => void
}) {
  const [projectId, setProjectId] = useState('')
  const [text, setText] = useState('')
  const [priority, setPriority] = useState<Priority>('normal')
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
      const task = await api.createTask({ title, description, project_id: project.id, priority })
      setText('')
      setPriority('normal')
      onCreated(task)
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
          {project && !project.enabled && (
            <p className="text-sm text-warn">Проект на паузе — задача подождёт, пока его не включат.</p>
          )}
          <ErrorNote error={error} />
          <Button type="submit" variant="primary" disabled={busy || !text.trim()} className="w-full">
            {busy ? 'Создаю…' : 'В работу'}
          </Button>
        </form>
      )}
    </Sheet>
  )
}
