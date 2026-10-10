'use client'

import { Plus, Rocket } from 'lucide-react'
import Link from 'next/link'
import { useMemo, useState } from 'react'
import { NewTaskSheet } from '@/components/NewTaskSheet'
import { TaskCard } from '@/components/TaskCard'
import { Empty, ErrorNote } from '@/components/ui'
import { api, type Task, type TaskStatus } from '@/lib/api'
import { cx } from '@/lib/format'
import { usePoll, useStoredState } from '@/lib/hooks'

const COLUMNS: { key: string; title: string; statuses: TaskStatus[]; limit?: number }[] = [
  { key: 'queue', title: 'Очередь', statuses: ['queued'] },
  { key: 'work', title: 'В работе', statuses: ['in_progress'] },
  { key: 'checks', title: 'CI и деплой', statuses: ['ci', 'deploying'] },
  { key: 'stage', title: 'На stage', statuses: ['on_stage'] },
  { key: 'failed', title: 'Ошибки', statuses: ['failed'] },
  { key: 'done', title: 'Готово', statuses: ['released', 'cancelled'], limit: 30 },
]

const ALL = '*'

export default function Board() {
  const [projectFilter, setProjectFilter] = useStoredState<string>('autodev.project', ALL)
  const [tab, setTab] = useStoredState<string>('autodev.tab', 'work')
  const [creating, setCreating] = useState(false)

  const projects = usePoll(api.projects, 30000)
  const filter = projectFilter === ALL ? undefined : projectFilter
  const tasks = usePoll(() => api.tasks(filter), 5000, [filter])

  const columns = useMemo(() => {
    const list = tasks.data ?? []
    return COLUMNS.map((c) => {
      const items = list.filter((t) => c.statuses.includes(t.status))
      return { ...c, items: c.limit ? items.slice(0, c.limit) : items, total: items.length }
    })
  }, [tasks.data])

  const projectList = projects.data ?? []
  const current = projectList.find((p) => p.id === filter)
  const onStage = columns.find((c) => c.key === 'stage')?.total ?? 0
  const loading = tasks.data === null && !tasks.error

  function added(task: Task) {
    tasks.setData([task, ...(tasks.data ?? [])])
    setTab('queue')
  }

  return (
    <div className="space-y-4">
      {projectList.length > 1 && (
        <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
          {[{ id: ALL, name: 'Все проекты' }, ...projectList].map((p) => (
            <button
              key={p.id}
              onClick={() => setProjectFilter(p.id)}
              className={cx(
                'shrink-0 rounded-full border px-3 py-1.5 text-sm',
                projectFilter === p.id ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-surface text-muted',
              )}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}

      {current && onStage > 0 && (
        <Link
          href={`/projects/${current.id}`}
          className="flex items-center gap-3 rounded-2xl border border-ok/40 bg-ok/10 px-4 py-3 text-sm"
        >
          <Rocket size={18} className="text-ok" />
          <span>
            На stage ждут релиза: <b>{onStage}</b>
          </span>
          <span className="ml-auto font-medium text-ok">Выкатить →</span>
        </Link>
      )}

      <ErrorNote error={tasks.error} />

      {/* Phones: one column at a time, chosen by tabs. */}
      <div className="lg:hidden">
        <div className="no-scrollbar sticky top-14 z-20 -mx-4 flex gap-1 overflow-x-auto bg-bg px-4 pb-2 pt-1">
          {columns.map((c) => (
            <button
              key={c.key}
              onClick={() => setTab(c.key)}
              className={cx(
                'flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-sm',
                tab === c.key ? 'bg-surface font-semibold shadow-sm ring-1 ring-line' : 'text-muted',
              )}
            >
              {c.title}
              {c.total > 0 && (
                <span
                  className={cx(
                    'rounded-full px-1.5 text-xs',
                    c.key === 'failed' ? 'bg-bad text-white' : 'bg-surface-2 text-muted',
                  )}
                >
                  {c.total}
                </span>
              )}
            </button>
          ))}
        </div>
        {columns
          .filter((c) => c.key === tab)
          .map((c) => (
            <div key={c.key} className="space-y-2">
              {c.items.map((t) => (
                <TaskCard key={t.id} task={t} showProject={!filter} />
              ))}
              {!loading && c.items.length === 0 && <Empty>Пусто</Empty>}
            </div>
          ))}
      </div>

      {/* Desktop: the whole board. */}
      <div className="hidden gap-3 lg:grid lg:grid-cols-6">
        {columns.map((c) => (
          <section key={c.key} className="min-w-0 space-y-2">
            <h2 className="flex items-center gap-2 px-1 text-sm font-semibold text-muted">
              {c.title}
              <span className="text-xs font-normal">{c.total || ''}</span>
            </h2>
            {c.items.map((t) => (
              <TaskCard key={t.id} task={t} showProject={!filter} />
            ))}
          </section>
        ))}
      </div>

      <button
        onClick={() => setCreating(true)}
        className="fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-5 z-30 flex h-14 items-center gap-2 rounded-full bg-accent px-5 font-semibold text-accent-fg shadow-lg shadow-accent/30 active:scale-95 sm:bottom-8"
        aria-label="Новая задача"
      >
        <Plus size={22} />
        Задача
      </button>

      <NewTaskSheet
        open={creating}
        onClose={() => setCreating(false)}
        projects={projectList}
        defaultProject={filter ?? null}
        onCreated={added}
      />
    </div>
  )
}
