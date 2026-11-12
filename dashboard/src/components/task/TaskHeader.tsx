import { CheckCircle2, CornerDownRight, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { Badge } from '@/components/ui'
import type { Project, Task } from '@/lib/api'
import { FIX_KIND, MODELS, PRIORITY, STATUS, ago } from '@/lib/format'

/** Number, status and marks, the main task of a follow-up, the title, where the task lives. */
export function TaskHeader({ task: t, project }: { task: Task; project?: Project }) {
  const s = STATUS[t.status]
  return (
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
        {t.model && <Badge tone="neutral">{MODELS[t.model] ?? t.model}</Badge>}
        {t.priority !== 'normal' && <Badge tone={t.priority === 'low' ? 'neutral' : 'warn'}>{PRIORITY[t.priority]}</Badge>}
        <span>{ago(t.status_changed_at)}</span>
      </div>
      {t.parent && (
        <Link href={`/tasks/${t.parent.id}`} className="flex min-w-0 items-center gap-1.5 text-sm text-muted hover:text-fg">
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
  )
}
