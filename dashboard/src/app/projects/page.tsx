'use client'

import { Globe, Plus } from 'lucide-react'
import Link from 'next/link'
import { Button, Card, Empty, ErrorNote } from '@/components/ui'
import { api } from '@/lib/api'
import { usePoll } from '@/lib/hooks'

export default function ProjectsPage() {
  const { data, error } = usePoll(api.projects, 15000)
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Проекты</h1>
        <Link href="/projects/new">
          <Button size="sm">
            <Plus size={15} /> Проект
          </Button>
        </Link>
      </div>
      <ErrorNote error={error} />
      {data?.length === 0 && <Empty>Проектов пока нет</Empty>}
      <div className="space-y-3">
        {data?.map((p) => {
          const c = p.task_counts
          const working = (c.queued ?? 0) + (c.in_progress ?? 0) + (c.ci ?? 0) + (c.deploying ?? 0)
          return (
            <Link key={p.id} href={`/projects/${p.id}`} className="block">
              <Card className="p-4 transition hover:border-accent/50">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 font-semibold">
                      {p.name}
                      {!p.enabled && <span className="text-xs font-normal text-muted">выключен</span>}
                    </div>
                    <div className="truncate text-sm text-muted">{p.repos.map((r) => r.name).join(', ')}</div>
                  </div>
                  {p.stage_url && <Globe size={18} className="text-muted" />}
                </div>
                <div className="mt-3 flex gap-4 text-sm">
                  <Stat label="в работе" value={working} />
                  <Stat label="на stage" value={c.on_stage ?? 0} tone="text-ok" />
                  <Stat label="ошибки" value={c.failed ?? 0} tone="text-bad" />
                  <Stat label="в проде" value={c.released ?? 0} />
                </div>
              </Card>
            </Link>
          )
        })}
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <div className={`text-lg font-semibold ${value ? (tone ?? '') : 'text-muted'}`}>{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  )
}
