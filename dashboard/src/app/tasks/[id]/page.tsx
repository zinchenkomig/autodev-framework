'use client'

import {
  ArrowLeft,
  Check,
  CornerDownRight,
  CheckCircle2,
  ExternalLink,
  GitPullRequest,
  Globe,
  CircleHelp,
  Loader2,
  MessageCircleQuestion,
  MessageSquarePlus,
  RotateCw,
  Square,
  Trash2,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { ChatSheet } from '@/components/Chat'
import { Badge, Button, Card, ErrorNote, Sheet, inputClass } from '@/components/ui'
import { api, type LogEntry, type Task } from '@/lib/api'
import { FIX_KIND, PRIORITY, STATUS, ago, cx, dateTime, time } from '@/lib/format'
import { usePoll } from '@/lib/hooks'

const MERGED = ['deploying', 'on_stage', 'released']

export default function TaskPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const task = usePoll(() => api.task(id), 4000, [id])
  const projects = usePoll(api.projects, 60000)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  // The chat about this task; `quote` is the test-plan step a question is about.
  const [ask, setAsk] = useState<{ open: boolean; quote: string | null }>({ open: false, quote: null })
  const chats = usePoll(() => api.chats('task', id), 30000, [id])
  const asked = chats.data?.filter((c) => c.question).length ?? 0
  const undecided = chats.data?.some((c) => c.pending > 0) ?? false

  const t = task.data
  const project = projects.data?.find((p) => p.id === t?.project_id)

  async function act(fn: () => Promise<Task | void>, after?: (r: Task | void) => void) {
    setBusy(true)
    setActionError(null)
    try {
      const result = await fn()
      after?.(result)
      await task.refresh()
    } catch (e) {
      setActionError((e as Error).message)
    } finally {
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

  const s = STATUS[t.status]
  const canCancel = ['queued', 'in_progress', 'ci'].includes(t.status)
  const canRetry = ['failed', 'cancelled'].includes(t.status)
  const canDelete = !['in_progress', 'ci', 'deploying'].includes(t.status)
  const merged = MERGED.includes(t.status)
  const waiting = t.waiting_for.length > 0
  // Follow-ups are checked with their main task, by its one plan.
  const withMain = !!t.parent
  const canFeedback = merged || (['ci', 'failed', 'cancelled'].includes(t.status) && t.pr_number) || (t.status === 'queued' && !t.branch)

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <BackLink />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
          <span className="font-mono">#{t.ticket_number}</span>
          <Badge tone={s.tone}>
            {t.status === 'in_progress' && <Loader2 size={12} className="animate-spin" />}
            {s.label}
          </Badge>
          {t.pending_fix && t.status === 'queued' && <Badge tone="warn">{FIX_KIND[t.pending_fix] ?? t.pending_fix}</Badge>}
          {t.verified_at && (
            <Badge tone="ok">
              <CheckCircle2 size={12} /> проверено
            </Badge>
          )}
          {t.priority !== 'normal' && <Badge tone={t.priority === 'low' ? 'neutral' : 'warn'}>{PRIORITY[t.priority]}</Badge>}
          <span>{ago(t.status_changed_at)}</span>
        </div>
        {t.parent && (
          <Link
            href={`/tasks/${t.parent.id}`}
            className="flex min-w-0 items-center gap-1.5 text-sm text-muted hover:text-fg"
          >
            <CornerDownRight size={14} className="shrink-0" />
            <span className="shrink-0">Основная задача</span>
            <span className="truncate font-medium">
              #{t.parent.ticket_number} {t.parent.title}
            </span>
            <Badge tone={STATUS[t.parent.status].tone}>{STATUS[t.parent.status].label}</Badge>
          </Link>
        )}
        <h1 className="text-xl font-semibold leading-snug sm:text-2xl">{t.title}</h1>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
          {project && <Link href={`/projects/${project.id}`} className="hover:text-fg">{project.name}</Link>}
          {t.repo && <span>{t.repo}</span>}
          {t.attempts > 0 && <span>раундов исправлений: {t.attempts}</span>}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {t.pr_url && (
          <a href={t.pr_url} target="_blank" rel="noreferrer">
            <Button size="sm">
              <GitPullRequest size={15} /> PR #{t.pr_number}
            </Button>
          </a>
        )}
        {merged && project?.stage_url && (
          <a href={project.stage_url} target="_blank" rel="noreferrer">
            <Button size="sm" variant={t.status === 'on_stage' ? 'primary' : 'secondary'}>
              <Globe size={15} /> Открыть stage
            </Button>
          </a>
        )}
        {merged && !withMain && (
          <Button
            size="sm"
            disabled={busy || (waiting && !t.verified_at)}
            className={cx(t.verified_at && 'border-ok/40 text-ok')}
            onClick={() =>
              (!t.verified_at || confirm('Снять отметку «проверено»?')) &&
              act(() => api.verifyTask(t.id, !t.verified_at), (r) => r && task.setData(r))
            }
          >
            <CheckCircle2 size={15} /> {t.verified_at ? 'Проверено' : 'Отметить проверенным'}
          </Button>
        )}
        {canFeedback && (
          <Button size="sm" onClick={() => setFeedbackOpen(true)}>
            <MessageSquarePlus size={15} /> {merged ? 'Доработать' : 'Правки'}
          </Button>
        )}
        <Button size="sm" onClick={() => setAsk({ open: true, quote: null })}>
          <MessageCircleQuestion size={15} /> Спросить{asked > 0 && <span className="text-muted">· {asked}</span>}
          {undecided && <span className="h-2 w-2 rounded-full bg-warn" title="Есть предложение агента, ждёт решения" />}
        </Button>
        {canRetry && (
          <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => api.retryTask(t.id))}>
            <RotateCw size={15} /> Повторить
          </Button>
        )}
        {canCancel && (
          <Button size="sm" variant="danger" disabled={busy} onClick={() => confirm('Остановить задачу?') && act(() => api.cancelTask(t.id))}>
            <Square size={14} /> Стоп
          </Button>
        )}
        {canDelete && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => confirm('Удалить задачу?') && act(() => api.deleteTask(t.id), () => router.push('/'))}
          >
            <Trash2 size={15} />
          </Button>
        )}
      </div>
      <ErrorNote error={actionError} />

      {t.status === 'failed' && t.error && (
        <Card className="border-bad/40 p-4">
          <div className="mb-1 text-sm font-semibold text-bad">Что пошло не так</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{t.error}</pre>
        </Card>
      )}

      {t.qa && <QaCard taskId={t.id} qa={t.qa} />}

      {t.summary && (
        <Card className="p-4">
          <div className="mb-1 text-sm font-semibold">Что сделал агент</div>
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{t.summary}</p>
        </Card>
      )}

      {withMain && t.parent && (
        <Link href={`/tasks/${t.parent.id}`} className="block">
          <Card className="flex items-center gap-2 p-4 text-sm hover:bg-surface-2">
            <CheckCircle2 size={15} className={cx('shrink-0', t.verified_at ? 'text-ok' : 'text-muted')} />
            <span className="min-w-0 flex-1">
              Проверяется вместе с основной задачей{' '}
              <span className="font-medium">#{t.parent.ticket_number}</span> — по её общему плану
            </span>
          </Card>
        </Link>
      )}

      {!t.parent && waiting && merged && (
        <Card className="border-warn/40 p-4 text-sm">
          <div className="mb-1 font-semibold">Ждёт доработок</div>
          <p className="text-muted">
            {t.waiting_for.map((w) => `#${w.ticket_number}`).join(', ')} ещё не на stage. Когда они выкатятся, план
            обновится — проверить всё можно будет одним проходом.
          </p>
        </Card>
      )}

      {!withMain && (t.test_plan.length > 0 || merged) && (
        <TestPlan
          task={t}
          interactive={merged}
          onRefresh={
            merged
              ? () =>
                  confirm('Пересобрать план по задаче, её доработкам и коду на stage? Отметки останутся у шагов, текст которых не изменился, — как «проверено в прошлой версии».') &&
                  act(() => api.refreshPlan(t.id), (r) => r && task.setData(r))
              : undefined
          }
          busy={busy}
          onAsk={(step) => setAsk({ open: true, quote: `Шаг ${step + 1}: ${t.test_plan[step]}` })}
          onToggle={(step, done) => {
            const checked = done ? [...t.plan_checked, step] : t.plan_checked.filter((i) => i !== step)
            task.setData({ ...t, plan_checked: checked, plan_earlier: t.plan_earlier.filter((i) => i !== step) })
            act(() => api.checkStep(t.id, step, done), (r) => r && task.setData(r))
          }}
        />
      )}

      {!t.parent && <FollowUps taskId={t.id} />}

      {t.description && (
        <Card className="p-4">
          <div className="mb-1 text-sm font-semibold">Задача</div>
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-muted">{t.description}</p>
        </Card>
      )}

      <TaskLog key={t.id} taskId={t.id} live={['queued', 'in_progress', 'ci', 'deploying'].includes(t.status) || t.plan_refreshing} />

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
        merged={merged}
        onSubmit={(text) =>
          act(
            () => api.feedback(t.id, text),
            (r) => {
              setFeedbackOpen(false)
              if (r && r.id !== t.id) router.push(`/tasks/${r.id}`)
            },
          )
        }
        busy={busy}
      />

      <p className="pt-2 text-center text-xs text-muted">
        создана {dateTime(t.created_at)} · {t.created_by ?? t.source}
      </p>
    </div>
  )
}

const CHILD_KIND: Record<string, string> = {
  feedback: 'Доработка',
  chat: 'Доработка из чата',
  qa: 'Исправление после QA',
  // from the multi-repo days
  triage: 'Часть задачи',
  developer: 'Нужно для другой части',
}

/** What the owner asked for: a follow-up's description without the "Follow-up to #N" footer. */
function request(task: Task): string {
  return (task.description ?? '').split('\n\n---\n')[0].trim()
}

/** The main task's history: each follow-up with what was asked and what the agent did. */
function FollowUps({ taskId }: { taskId: string }) {
  const { data } = usePoll(() => api.children(taskId), 8000, [taskId])
  if (!data?.length) return null
  return (
    <Card className="p-2">
      <div className="px-2 pb-1 pt-2 text-sm font-semibold">История доработок · {data.length}</div>
      <ol>
        {data.map((c) => {
          const s = STATUS[c.status]
          const asked = request(c)
          return (
            <li key={c.id} className="border-t border-line first:border-t-0">
              <Link href={`/tasks/${c.id}`} className="block space-y-1 rounded-xl px-2 py-2.5 hover:bg-surface-2">
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span className="font-mono">#{c.ticket_number}</span>
                  <span className="truncate">{CHILD_KIND[c.created_by ?? ''] ?? 'Доработка'}</span>
                  <span>· {dateTime(c.created_at)}</span>
                  <Badge tone={s.tone} className="ml-auto shrink-0 whitespace-nowrap">
                    {c.status === 'in_progress' && <Loader2 size={12} className="animate-spin" />}
                    {s.label}
                  </Badge>
                </div>
                <p className="line-clamp-4 whitespace-pre-wrap break-words text-[15px] leading-snug">{asked || c.title}</p>
                {c.summary && (
                  <p className="line-clamp-3 whitespace-pre-wrap break-words text-xs leading-relaxed text-muted">
                    {c.summary}
                  </p>
                )}
              </Link>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

function TestPlan({
  task,
  interactive,
  busy,
  onToggle,
  onRefresh,
  onAsk,
}: {
  task: Task
  interactive: boolean
  busy: boolean
  onToggle: (step: number, done: boolean) => void
  onRefresh?: () => void
  onAsk: (step: number) => void
}) {
  const checked = new Set(task.plan_checked)
  const earlier = new Set(task.plan_earlier)
  const next = interactive ? task.test_plan.findIndex((_, i) => !checked.has(i)) : -1
  const empty = task.test_plan.length === 0
  return (
    <Card className="p-2">
      <div className="flex items-center justify-between gap-2 px-2 pb-1 pt-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold">Как проверить на stage</div>
          {interactive && !empty && (
            <div className={cx('text-xs', checked.size === task.test_plan.length ? 'text-ok' : 'text-muted')}>
              проверено {checked.size} из {task.test_plan.length}
              {earlier.size > 0 && ` · ${earlier.size} в прошлой версии`}
            </div>
          )}
        </div>
        {onRefresh && (
          <Button size="sm" variant="ghost" className="shrink-0" disabled={busy || task.plan_refreshing} onClick={onRefresh}>
            {task.plan_refreshing ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
            {task.plan_refreshing ? 'Пересобираю…' : 'Пересобрать'}
          </Button>
        )}
      </div>
      {task.plan_refreshing && (
        <p className="px-2 pb-1 text-xs text-muted">
          Агент собирает план заново по задаче, её доработкам и коду на stage — ход видно в логе ниже.
        </p>
      )}
      {empty && !task.plan_refreshing && (
        <p className="px-2 pb-2 text-sm text-muted">Плана нет. Нажмите «Пересобрать», чтобы агент его написал.</p>
      )}
      <ol>
        {task.test_plan.map((step, i) => {
          const done = checked.has(i)
          // Ticked on the previous version: the new code may have broken it, so it waits for a new tick.
          const before = !done && earlier.has(i)
          return (
            <li key={i} className={cx('flex items-start rounded-xl', i === next && 'bg-accent/10')}>
              <button
                disabled={!interactive}
                onClick={() => onToggle(i, !done)}
                className={cx(
                  'flex min-w-0 flex-1 items-start gap-3 rounded-xl py-2.5 pl-2 text-left transition disabled:cursor-default',
                  interactive && 'hover:bg-surface-2 active:scale-[0.99]',
                )}
              >
                <span
                  className={cx(
                    'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-[11px] font-semibold',
                    done
                      ? 'border-ok bg-ok text-white'
                      : before
                        ? 'border-dashed border-ok text-ok'
                        : i === next
                          ? 'border-accent text-accent'
                          : 'border-line text-muted',
                  )}
                >
                  {done || before ? <Check size={14} strokeWidth={3} /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className={cx('block whitespace-pre-wrap break-words text-[15px] leading-relaxed', done && 'text-muted line-through')}>
                    {step}
                  </span>
                  {before && <span className="mt-0.5 block text-xs text-ok">Проверено в прошлой версии — проверьте снова</span>}
                </span>
              </button>
              <button
                onClick={() => onAsk(i)}
                className="shrink-0 rounded-xl p-2.5 text-muted transition hover:bg-surface-2 hover:text-fg"
                aria-label={`Спросить про шаг ${i + 1}`}
                title="Спросить про этот шаг"
              >
                <CircleHelp size={16} />
              </button>
            </li>
          )
        })}
      </ol>
      {!interactive && !empty && <p className="px-2 pb-2 pt-1 text-xs text-muted">Отмечать шаги можно, когда задача попадёт на stage.</p>}
    </Card>
  )
}

function QaCard({ taskId, qa }: { taskId: string; qa: NonNullable<Task['qa']> }) {
  const { data: artifacts } = usePoll(() => api.artifacts(taskId), 60000, [taskId])
  const shots = (artifacts ?? []).filter((a) => a.kind === 'screenshot')
  const tone = qa.skipped ? 'text-muted' : qa.ok ? 'text-ok' : 'text-bad'
  return (
    <Card className="space-y-3 p-4">
      <div className={cx('flex items-center gap-2 text-sm font-semibold', tone)}>
        {qa.skipped ? 'Проверка stage пропущена' : qa.ok ? 'Stage проверен — ошибок нет' : 'На stage есть проблемы'}
      </div>
      {qa.skipped && <p className="text-xs text-muted">{qa.skipped}</p>}
      {qa.problems.length > 0 && (
        <ul className="space-y-1 text-xs text-bad">
          {qa.problems.map((p) => (
            <li key={p} className="break-words">
              {p}
            </li>
          ))}
        </ul>
      )}
      {shots.length > 0 && (
        <div className="no-scrollbar -mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-1">
          {shots.map((a) => (
            <a key={a.id} href={api.artifactUrl(a.url)} target="_blank" rel="noreferrer" className="w-40 shrink-0 snap-start">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={api.artifactUrl(a.url)}
                alt={a.name}
                loading="lazy"
                className="aspect-[390/844] w-full rounded-xl border border-line object-cover object-top"
              />
              <div className="mt-1 truncate text-[11px] text-muted">{a.name.replace(/^https?:\/\/[^/]+/, '') || '/'}</div>
            </a>
          ))}
        </div>
      )}
    </Card>
  )
}

function BackLink() {
  return (
    <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
      <ArrowLeft size={16} /> Задачи
    </Link>
  )
}

function FeedbackSheet({
  open,
  onClose,
  merged,
  onSubmit,
  busy,
}: {
  open: boolean
  onClose: () => void
  merged: boolean
  onSubmit: (text: string) => void
  busy: boolean
}) {
  const [text, setText] = useState('')
  return (
    <Sheet open={open} onClose={onClose} title={merged ? 'Доработать' : 'Правки'}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) onSubmit(text.trim())
        }}
      >
        <p className="text-sm text-muted">
          {merged
            ? 'Изменение уже в stage — создам новую задачу-доработку, связанную с этой.'
            : 'Агент продолжит в той же сессии и обновит этот же PR.'}
        </p>
        <textarea
          autoFocus
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={inputClass}
          placeholder="Сделай кнопку заметнее и добавь подтверждение удаления"
        />
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !text.trim()}>
          Отправить
        </Button>
      </form>
    </Sheet>
  )
}

const LEVEL_STYLE: Record<string, string> = {
  error: 'text-bad',
  warning: 'text-warn',
  transition: 'text-accent font-medium',
}

function TaskLog({ taskId, live }: { taskId: string; live: boolean }) {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const lastRef = useRef<string | undefined>(undefined)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const batch = await api.logs(taskId, lastRef.current)
        if (cancelled || batch.length === 0) return
        lastRef.current = batch[batch.length - 1].created_at
        const box = boxRef.current
        const atBottom = !box || box.scrollHeight - box.scrollTop - box.clientHeight < 80
        setEntries((prev) => [...prev, ...batch])
        if (atBottom) requestAnimationFrame(() => box && (box.scrollTop = box.scrollHeight))
        setError(null)
      } catch (e) {
        if (!cancelled) setError(e as Error)
      }
    }

    load()
    const timer = live ? setInterval(load, 3000) : undefined
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [taskId, live])

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-sm font-semibold">Ход работы</span>
        {live && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ok" /> обновляется
          </span>
        )}
      </div>
      <div ref={boxRef} className="max-h-[60dvh] overflow-y-auto px-2 py-2">
        <ErrorNote error={error} />
        {entries.length === 0 && !error && <p className="px-2 py-4 text-sm text-muted">Пока пусто</p>}
        {entries.map((e) => (
          <div key={e.id} className="rounded-lg px-2 py-1 hover:bg-surface-2">
            <button
              className="flex w-full items-start gap-2 text-left"
              onClick={() => e.details && setOpen((o) => ({ ...o, [e.id]: !o[e.id] }))}
            >
              <span className="mt-0.5 shrink-0 font-mono text-[11px] text-muted">{time(e.created_at)}</span>
              <span className={cx('min-w-0 break-words text-[13px] leading-snug', LEVEL_STYLE[e.level])}>
                {e.message}
                {e.details && <ExternalLink size={11} className="ml-1 inline text-muted" />}
              </span>
            </button>
            {e.details && open[e.id] && (
              <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-bg p-2 font-mono text-[11px] leading-relaxed text-muted">
                {e.details}
              </pre>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}
