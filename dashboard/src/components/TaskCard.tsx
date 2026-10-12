import { AlertTriangle, CheckCircle2, CornerDownRight, GitPullRequest, ListChecks, Loader2, RotateCw } from 'lucide-react'
import Link from 'next/link'
import type { Task } from '@/lib/api'
import { FIX_KIND, PRIORITY, STATUS, ago, cx } from '@/lib/format'
import { Badge } from './ui'

export function TaskCard({ task, showProject }: { task: Task; showProject?: boolean }) {
  const s = STATUS[task.status]
  const working = task.status === 'in_progress'
  return (
    <Link
      href={`/tasks/${task.id}`}
      className={cx(
        'block rounded-2xl border bg-surface p-3 transition hover:border-accent/50 active:scale-[0.99]',
        task.status === 'failed' ? 'border-bad/40' : 'border-line',
      )}
    >
      <div className="mb-1.5 flex items-center gap-2 text-xs text-muted">
        <span className="font-mono">#{task.ticket_number}</span>
        <span className="min-w-0 truncate">
          {[showProject && task.project_id, task.repo?.split('/')[1]].filter(Boolean).join(' · ')}
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
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone={s.tone}>
          {working && <Loader2 size={12} className="animate-spin" />}
          {s.label}
        </Badge>
        {task.pending_fix && task.status === 'queued' && (
          <Badge tone="warn">
            <RotateCw size={12} />
            {FIX_KIND[task.pending_fix] ?? task.pending_fix}
          </Badge>
        )}
        {(task.priority === 'critical' || task.priority === 'high') && (
          <Badge tone={task.priority === 'critical' ? 'bad' : 'warn'}>{PRIORITY[task.priority]}</Badge>
        )}
        {task.status === 'on_stage' &&
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
        {task.pr_number && (
          <span className="inline-flex items-center gap-1 text-xs text-muted">
            <GitPullRequest size={12} />#{task.pr_number}
          </span>
        )}
        {task.status === 'failed' && task.error && (
          <span className="flex w-full items-start gap-1 text-xs text-bad">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span className="line-clamp-2">{task.error}</span>
          </span>
        )}
      </div>
    </Link>
  )
}
