'use client'

import { AlertTriangle, Eye, Globe, Rocket, Telescope } from 'lucide-react'
import Link from 'next/link'
import { useMemo } from 'react'
import { ProjectChips } from '@/components/ProjectChips'
import { TaskCard } from '@/components/TaskCard'
import { Card, Empty, ErrorNote } from '@/components/ui'
import { plural } from '@/lib/format'
import { ALL_PROJECTS, usePoll, useProjectFilter } from '@/lib/hooks'
import { fetchInbox } from '@/lib/inbox'

export default function InboxPage() {
  const { data: inbox, error } = usePoll(fetchInbox, 8000)

  // Projects that have something waiting, with how much, in the order projects are listed.
  const chips = useMemo(() => {
    if (!inbox) return []
    const counts = new Map<string, number>()
    const bump = (id: string | null) => id && counts.set(id, (counts.get(id) ?? 0) + 1)
    inbox.check.forEach((t) => bump(t.project_id))
    inbox.proposed.forEach((t) => bump(t.project_id))
    inbox.failed.forEach((t) => bump(t.project_id))
    inbox.release.forEach((r) => bump(r.project.id))
    return inbox.projects.filter((p) => counts.has(p.id)).map((p) => ({ id: p.id, name: p.name, count: counts.get(p.id)! }))
  }, [inbox])

  // A project whose queue emptied out falls back to all of them.
  const [project, setProject] = useProjectFilter('autodev.inbox.project', inbox && chips)
  const data = useMemo(() => {
    if (!inbox || project === ALL_PROJECTS) return inbox
    const check = inbox.check.filter((t) => t.project_id === project)
    const proposed = inbox.proposed.filter((t) => t.project_id === project)
    const failed = inbox.failed.filter((t) => t.project_id === project)
    const release = inbox.release.filter((r) => r.project.id === project)
    return { ...inbox, check, proposed, failed, release, total: check.length + proposed.length + failed.length + release.length }
  }, [inbox, project])
  const multiProject = project === ALL_PROJECTS && chips.length > 1

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="text-xl font-semibold">Ждут меня</h1>
      <ErrorNote error={error} />
      {chips.length > 1 && (
        <ProjectChips
          items={[{ id: ALL_PROJECTS, name: 'Все проекты', count: inbox?.total }, ...chips]}
          value={project}
          onChange={setProject}
        />
      )}
      {data?.total === 0 && <Empty>Ничего не ждёт — всё идёт само</Empty>}

      {data && data.check.length > 0 && (
        <Section icon={<Eye size={16} className="text-ok" />} title="Проверить на stage" count={data.check.length}>
          {data.check.map((t) => (
            <TaskCard key={t.id} task={t} showProject={multiProject} />
          ))}
        </Section>
      )}

      {data && data.proposed.length > 0 && (
        <Section icon={<Telescope size={16} className="text-accent" />} title="Решить, что брать в работу" count={data.proposed.length}>
          {data.proposed.map((t) => (
            <TaskCard key={t.id} task={t} showProject={multiProject} />
          ))}
        </Section>
      )}

      {data && data.failed.length > 0 && (
        <Section
          icon={<AlertTriangle size={16} className="text-bad" />}
          title="Разобраться с ошибкой"
          count={data.failed.length}
        >
          {data.failed.map((t) => (
            <TaskCard key={t.id} task={t} showProject={multiProject} />
          ))}
        </Section>
      )}

      {data && data.release.length > 0 && (
        <Section icon={<Rocket size={16} className="text-accent" />} title="Выкатить в прод" count={data.release.length}>
          {data.release.map(({ project, tasks }) => (
            <Link key={project.id} href={`/projects/${project.id}`} className="block">
              <Card className="flex items-center gap-3 p-3 transition hover:border-accent/50">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-medium">
                    {project.name}
                    {project.stage_url && <Globe size={14} className="text-muted" />}
                  </div>
                  <div className="text-sm text-muted">
                    Всё проверено: {tasks} {plural(tasks, ['задача', 'задачи', 'задач'])} на stage
                  </div>
                </div>
                <span className="shrink-0 text-sm font-medium text-accent">Выкатить →</span>
              </Card>
            </Link>
          ))}
        </Section>
      )}
    </div>
  )
}

function Section({
  icon,
  title,
  count,
  children,
}: {
  icon: React.ReactNode
  title: string
  count: number
  children: React.ReactNode
}) {
  return (
    <section className="space-y-2">
      <h2 className="flex items-center gap-2 px-1 text-sm font-semibold text-muted">
        {icon}
        {title}
        <span className="text-xs font-normal">{count}</span>
      </h2>
      {children}
    </section>
  )
}
