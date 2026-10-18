'use client'

import { AlertTriangle, Eye, Globe, Rocket } from 'lucide-react'
import Link from 'next/link'
import { TaskCard } from '@/components/TaskCard'
import { Card, Empty, ErrorNote } from '@/components/ui'
import { plural } from '@/lib/format'
import { usePoll } from '@/lib/hooks'
import { fetchInbox } from '@/lib/inbox'

export default function InboxPage() {
  const { data, error } = usePoll(fetchInbox, 8000)
  const multiProject = new Set([...(data?.check ?? []), ...(data?.failed ?? [])].map((t) => t.project_id)).size > 1

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="text-xl font-semibold">Ждут меня</h1>
      <ErrorNote error={error} />
      {data?.total === 0 && <Empty>Ничего не ждёт — всё идёт само</Empty>}

      {data && data.check.length > 0 && (
        <Section icon={<Eye size={16} className="text-ok" />} title="Проверить на stage" count={data.check.length}>
          {data.check.map((t) => (
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
