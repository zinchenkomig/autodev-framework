import { AlertTriangle, CheckCircle2, CornerDownRight, GitPullRequest, ListChecks, Loader2, RotateCw, Wrench } from 'lucide-react'
import Link from 'next/link'
import type { Task } from '@/lib/api'
import { FIX_KIND, PRIORITY, STATUS, ago, cx } from '@/lib/format'
import { Badge } from './ui'

/** followUps, active: the main task's follow-ups stacked into its card (see lib/stack). */
export function TaskCard({
  task,
  showProject,
  followUps = [],
  active = null,
}: {
  task: Task
  showProject?: boolean
  followUps?: Task[]
  active?: Task | null
}) {
  // A follow-up in the works speaks for the card: its status, fix round and error.
  const shown = active ?? task
  const s = STATUS[shown.status]
  const working = shown.status === 'in_progress'
  return (
    <Link
      href={`/tasks/${task.id}`}
      className={cx(
        'block rounded-2xl border bg-surface p-3 transition hover:border-accent/50 active:scale-[0.99]',
        shown.status === 'failed' ? 'border-bad/40' : 'border-line',
      )}
    >
      <div className="mb-1.5 flex items-center gap-2 text-xs text-muted">
        <span className="font-mono">#{task.ticket_number}</span>
        <span className="min-w-0 truncate">
          {showProject && task.project_id}
        </span>
        <span className="ml-auto shrink-0">{ago(task.status_changed_at)}</span>
      </div>
      {task.parent && (
        <div className="mb-1 flex min-w-0 items-center gap-1 text-xs text-muted">
          <CornerDownRight size={12} className="shrink-0" />
          <span className="truncate">
            #{task.parent.ticket_number} {task.parent.title}
          </span>
        </div>
      )}
      <div className="line-clamp-3 text-[15px] font-medium leading-snug">{task.title}</div>
      {active && (
        <div className="mt-1 flex min-w-0 items-center gap-1 text-xs text-muted">
          <Wrench size={12} className="shrink-0" />
          <span className="truncate">
            доработка #{active.ticket_number}
            {followUps.length > 1 && ` · всего ${followUps.length}`}
          </span>
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone={s.tone}>
          {working && <Loader2 size={12} className="animate-spin" />}
          {s.label}
        </Badge>
        {shown.pending_fix && shown.status === 'queued' && (
          <Badge tone="warn">
            <RotateCw size={12} />
            {FIX_KIND[shown.pending_fix] ?? shown.pending_fix}
          </Badge>
        )}
        {(task.priority === 'critical' || task.priority === 'high') && (
          <Badge tone={task.priority === 'critical' ? 'bad' : 'warn'}>{PRIORITY[task.priority]}</Badge>
        )}
        {shown.status === 'on_stage' &&
          (task.verified_at ? (
            <Badge tone="ok">
              <CheckCircle2 size={12} />
              проверено
            </Badge>
          ) : (
            task.test_plan.length > 0 && (
              <span className="inline-flex items-center gap-1 text-xs text-muted">
                <ListChecks size={12} />
                {task.plan_checked.length}/{task.test_plan.length}
              </span>
            )
          ))}
        {!active && followUps.length > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-muted">
            <Wrench size={12} />
            {followUps.length}
          </span>
        )}
        {shown.pr_number && (
          <span className="inline-flex items-center gap-1 text-xs text-muted">
            <GitPullRequest size={12} />#{shown.pr_number}
          </span>
        )}
        {shown.status === 'failed' && shown.error && (
          <span className="flex w-full items-start gap-1 text-xs text-bad">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span className="line-clamp-2">{shown.error}</span>
          </span>
        )}
      </div>
    </Link>
  )
}
