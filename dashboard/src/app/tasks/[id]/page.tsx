'use client'

import { ArrowLeft, CheckCircle2, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'
import { ChatSheet } from '@/components/Chat'
import { Markdown } from '@/components/Markdown'
import { FeedbackSheet } from '@/components/task/FeedbackSheet'
import { FollowUps } from '@/components/task/FollowUps'
import { Shots } from '@/components/task/Shots'
import { AcceptanceCard, QaCard } from '@/components/task/StageChecks'
import { TaskActions } from '@/components/task/TaskActions'
import { TaskHeader } from '@/components/task/TaskHeader'
import { TestPlan } from '@/components/task/TestPlan'
import { WorkLog } from '@/components/task/WorkLog'
import { Card, Collapsible, ErrorNote } from '@/components/ui'
import { api, type Task } from '@/lib/api'
import { SCOUT_KIND, cx, dateTime, feedbackKind, followUpRequest, isMerged, isRunning } from '@/lib/format'
import { usePoll } from '@/lib/hooks'

export default function TaskPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const task = usePoll(() => api.task(id), 4000, [id])
  const projects = usePoll(api.projects, 60000)
  const chats = usePoll(() => api.chats('task', id), 30000, [id])
  const children = usePoll(() => api.children(id), 8000, [id])
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  // The chat about this task; `quote` is the test-plan step a question is about.
  const [ask, setAsk] = useState<{ open: boolean; quote: string | null }>({ open: false, quote: null })

  const t = task.data
  const project = projects.data?.find((p) => p.id === t?.project_id)

  /** Runs a request that changes a task: shows this task as the API returned it, then reloads it. */
  async function act(request: () => Promise<Task>): Promise<Task | undefined> {
    setBusy(true)
    setActionError(null)
    try {
      const result = await request()
      if (result.id === id) task.setData(result) // feedback may return a new follow-up instead
      await task.refresh()
      return result
    } catch (e) {
      setActionError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setActionError(null)
    try {
      await api.deleteTask(id)
      router.push('/') // no reload: the task is gone
    } catch (e) {
      setActionError((e as Error).message)
      setBusy(false)
    }
  }

  if (task.error && !t) {
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorNote error={task.error} />
      </div>
    )
  }
  if (!t) return <Loader2 className="mx-auto mt-16 animate-spin text-muted" />

  const merged = isMerged(t.status)
  const waiting = t.waiting_for.length > 0
  const followUps = children.data ?? []
  // The PM's acceptance writes to the log while the task already stands on stage.
  const accepting = t.acceptance?.state === 'checking' || t.acceptance?.state === 'fixing'

  async function sendFeedback(text: string) {
    const result = await act(() => api.feedback(id, text))
    if (!result) return
    setFeedbackOpen(false)
    if (result.id !== id) router.push(`/tasks/${result.id}`)
  }

  const toggleStep = (step: number, done: boolean) => {
    // Shown at once; the API's answer replaces it.
    const checked = done ? [...t.plan_checked, step] : t.plan_checked.filter((i) => i !== step)
    task.setData({ ...t, plan_checked: checked, plan_earlier: t.plan_earlier.filter((i) => i !== step) })
    act(() => api.checkStep(id, step, done))
  }

  function refreshPlan() {
    const question =
      'Пересобрать план по задаче, её доработкам и коду на stage? Отметки останутся у шагов, текст которых не изменился, — как «проверено в прошлой версии».'
    if (confirm(question)) act(() => api.refreshPlan(id))
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 lg:max-w-6xl">
      <BackLink />
      <TaskHeader task={t} project={project} />
      <TaskActions
        task={t}
        project={project}
        followUps={followUps}
        chats={chats.data ?? []}
        busy={busy}
        act={act}
        onFeedback={() => setFeedbackOpen(true)}
        onAsk={() => setAsk({ open: true, quote: null })}
        onDelete={remove}
      />
      <ErrorNote error={actionError} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0 space-y-4">
          {t.status === 'failed' && t.error && (
            <Card className="border-bad/40 p-4">
              <div className="mb-1 text-sm font-semibold text-bad">Что пошло не так</div>
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{t.error}</pre>
            </Card>
          )}

          {t.scout?.rejected !== undefined && t.status === 'cancelled' && (
            <Card className="p-4 text-sm">
              <span className="font-semibold text-muted">Вы отклонили</span>
              {t.scout.rejected && `: ${t.scout.rejected}`}
            </Card>
          )}

          {t.description && (
            <Card className="p-4">
              <div className="mb-1.5 text-sm font-semibold text-muted">
                {t.created_by === 'scout' ? `Нашёл скаут${t.scout?.kind ? ` · ${SCOUT_KIND[t.scout.kind]}` : ''}` : t.parent ? 'Что попросили' : 'Задача'}
              </div>
              <Collapsible>
                <Markdown text={t.parent ? followUpRequest(t) : t.description} className="text-[15px] leading-relaxed" />
              </Collapsible>
              {t.created_by === 'scout' && <Shots taskId={t.id} by="Скаут" />}
            </Card>
          )}

          {t.brief && (
            <Card className="p-4">
              <div className="mb-1.5 text-sm font-semibold text-muted">ТЗ от PM</div>
              <Collapsible>
                <Markdown text={t.brief} className="text-[15px] leading-relaxed" />
              </Collapsible>
            </Card>
          )}

          <WorkLog key={t.id} task={t} live={isRunning(t.status) || t.plan_refreshing || accepting} />

          {/* A follow-up is checked with its main task, by its one plan. */}
          {t.parent ? (
            <Link href={`/tasks/${t.parent.id}`} className="block">
              <Card className="flex items-center gap-2 p-4 text-sm hover:bg-surface-2">
                <CheckCircle2 size={15} className={cx('shrink-0', t.verified_at ? 'text-ok' : 'text-muted')} />
                <span className="min-w-0 flex-1">
                  Проверяется вместе с основной задачей{' '}
                  <span className="font-medium">#{t.parent.ticket_number}</span> — по её общему плану
                </span>
              </Card>
            </Link>
          ) : (
            <>
              {waiting && merged && (
                <Card className="border-warn/40 p-4 text-sm">
                  <div className="mb-1 font-semibold">Ждёт доработок</div>
                  <p className="text-muted">
                    {t.waiting_for.map((w) => `#${w.ticket_number}`).join(', ')} ещё не на stage. Когда они выкатятся, план
                    обновится — проверить всё можно будет одним проходом.
                  </p>
                </Card>
              )}

              {t.acceptance && <AcceptanceCard task={t} />}

              {(t.test_plan.length > 0 || merged) && (
                <TestPlan
                  task={t}
                  interactive={merged}
                  busy={busy}
                  onRefresh={merged ? refreshPlan : undefined}
                  onAsk={(step) => setAsk({ open: true, quote: `Шаг ${step + 1}: ${t.test_plan[step]}` })}
                  onToggle={toggleStep}
                />
              )}
            </>
          )}
        </div>

        <aside className="min-w-0 space-y-4">
          {!t.parent && <FollowUps items={followUps} />}
          {t.qa && <QaCard taskId={t.id} qa={t.qa} />}
          <p className="text-center text-xs text-muted lg:text-left">
            создана {dateTime(t.created_at)} · {t.created_by ?? t.source}
          </p>
        </aside>
      </div>

      <ChatSheet
        open={ask.open}
        onClose={() => {
          setAsk({ open: false, quote: null })
          chats.refresh()
        }}
        subject="task"
        subjectId={t.id}
        title="Вопросы по задаче"
        hint="Спросите про непонятный термин, шаг плана или как это сделано. Агент знает задачу, план проверки и код проекта. Если нужна доработка — предложит, а создаст только после вашего «да»."
        quote={ask.quote}
        onChange={() => {
          task.refresh()
          chats.refresh()
        }}
      />

      <FeedbackSheet
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        kind={feedbackKind(t)}
        onSubmit={sendFeedback}
        busy={busy}
      />
    </div>
  )
}

function BackLink() {
  return (
    <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
      <ArrowLeft size={16} /> Задачи
    </Link>
  )
}
