'use client'

import { ArrowLeft, CheckCircle2, Clock, ExternalLink, Globe, Loader2, Rocket, XCircle } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'
import { ProjectForm } from '@/components/ProjectForm'
import { TaskCard } from '@/components/TaskCard'
import { Badge, Button, Card, Empty, ErrorNote } from '@/components/ui'
import { api, type Release } from '@/lib/api'
import { dateTime, plural } from '@/lib/format'
import { usePoll } from '@/lib/hooks'
import { stack } from '@/lib/stack'

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const project = usePoll(() => api.project(id), 15000, [id])
  const releases = usePoll(() => api.releases(id), 8000, [id])
  const tasks = usePoll(() => api.tasks(id), 10000, [id])
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const p = project.data
  if (project.error && !p) return <ErrorNote error={project.error} />
  if (!p) return <Loader2 className="mx-auto mt-16 animate-spin text-muted" />

  // Follow-ups go out with their main task and are checked in it.
  const onStage = stack((tasks.data ?? []).filter((t) => t.status === 'on_stage'))
  const pending = releases.data?.find((r) => r.status === 'pending')
  const unchecked = onStage.filter((s) => !s.task.verified_at).length

  async function release() {
    const warning = unchecked ? `\n\nНе проверено на stage: ${unchecked}.` : ''
    if (!confirm(`Выкатить ${p!.name} в прод (${p!.base_branch} → ${p!.prod_branch})?${warning}`)) return
    setBusy(true)
    setError(null)
    try {
      await api.release(p!.id)
      await releases.refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link href="/projects" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft size={16} /> Проекты
      </Link>

      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold">{p.name}</h1>
          <div className="text-sm text-muted">{p.repos.map((r) => r.name).join(', ')}</div>
        </div>
        {p.stage_url && (
          <a href={p.stage_url} target="_blank" rel="noreferrer">
            <Button size="sm">
              <Globe size={15} /> Stage
            </Button>
          </a>
        )}
      </div>

      <Card className="space-y-3 p-4">
        <div className="flex items-center gap-2">
          <Rocket size={18} className="text-accent" />
          <span className="font-semibold">Релиз в прод</span>
        </div>
        {pending ? (
          <ReleaseRow release={pending} />
        ) : (
          <>
            <p className="text-sm text-muted">
              {onStage.length
                ? `На stage ${onStage.length} ${plural(onStage.length, ['невыпущенная задача', 'невыпущенные задачи', 'невыпущенных задач'])}. Открою PR ${p.base_branch} → ${p.prod_branch} и смержу их, когда пройдут проверки.`
                : `Новых задач на stage нет. Релиз всё равно можно сделать, если в ${p.base_branch} есть изменения.`}
            </p>
            <Button variant="primary" onClick={release} disabled={busy}>
              <Rocket size={16} /> {busy ? 'Открываю PR…' : 'Выкатить в прод'}
            </Button>
          </>
        )}
        <ErrorNote error={error} />
      </Card>

      {onStage.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-muted">
            Попадут в релиз
            {unchecked > 0 && <span className="font-normal text-warn"> · не проверено {unchecked}</span>}
          </h2>
          {onStage.map((s) => (
            <TaskCard key={s.task.id} task={s.task} followUps={s.followUps} />
          ))}
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-muted">История релизов</h2>
        {releases.data?.length === 0 && <Empty>Релизов ещё не было</Empty>}
        {releases.data
          ?.filter((r) => r.id !== pending?.id)
          .map((r) => (
            <Card key={r.id} className="p-3">
              <ReleaseRow release={r} />
            </Card>
          ))}
      </section>

      <section className="space-y-3">
        <button className="text-sm font-semibold text-accent" onClick={() => setEditing((v) => !v)}>
          {editing ? 'Скрыть настройки' : 'Настройки проекта'}
        </button>
        {editing && (
          <Card className="p-4">
            <ProjectForm
              initial={p}
              isNew={false}
              onSubmit={async (next) => {
                const { id: _id, ...rest } = next
                void _id
                await api.updateProject(p.id, rest)
                await project.refresh()
                setEditing(false)
              }}
            />
            <div className="mt-6 border-t border-line pt-4">
              <Button
                variant="danger"
                size="sm"
                onClick={async () => {
                  if (!confirm('Удалить проект? Возможно только если в нём нет задач.')) return
                  try {
                    await api.deleteProject(p.id)
                    router.push('/projects')
                  } catch (e) {
                    setError((e as Error).message)
                  }
                }}
              >
                Удалить проект
              </Button>
            </div>
          </Card>
        )}
      </section>
    </div>
  )
}

function ReleaseRow({ release }: { release: Release }) {
  const icon =
    release.status === 'deployed' ? (
      <CheckCircle2 size={16} className="text-ok" />
    ) : release.status === 'failed' ? (
      <XCircle size={16} className="text-bad" />
    ) : (
      <Clock size={16} className="text-warn" />
    )
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {icon}
        <span className="font-mono text-sm font-medium">{release.version}</span>
        <Badge tone={release.status === 'deployed' ? 'ok' : release.status === 'failed' ? 'bad' : 'warn'}>
          {release.status === 'deployed' ? 'в проде' : release.status === 'failed' ? 'ошибка' : 'жду проверок'}
        </Badge>
        <span className="ml-auto text-xs text-muted">{dateTime(release.production_deployed_at ?? release.created_at)}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {release.release_prs.map((pr) => (
          <a
            key={pr.pr_url}
            href={pr.pr_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
          >
            {pr.merged ? <CheckCircle2 size={12} className="text-ok" /> : <Clock size={12} />}
            {pr.repo.split('/')[1]}#{pr.pr_number}
            <ExternalLink size={11} />
          </a>
        ))}
      </div>
      {release.error && <ErrorNote error={release.error} />}
      {release.release_notes && (
        <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-muted">{release.release_notes}</pre>
      )}
    </div>
  )
}
