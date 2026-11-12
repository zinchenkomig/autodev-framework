import { Loader2 } from 'lucide-react'
import Link from 'next/link'
import { Card } from '@/components/ui'
import type { Acceptance, Task } from '@/lib/api'
import { cx } from '@/lib/format'
import { Shots } from './Shots'

/** The automatic check of stage after the deploy: errors the headless browser caught, its screenshots. */
export function QaCard({ taskId, qa }: { taskId: string; qa: NonNullable<Task['qa']> }) {
  const tone = qa.skipped ? 'text-muted' : qa.ok ? 'text-ok' : 'text-bad'
  return (
    <Card className="space-y-2 p-3">
      <div className={cx('text-sm font-semibold', tone)}>
        {qa.skipped ? 'Автопроверка stage пропущена' : qa.ok ? 'Автопроверка stage: ошибок нет' : 'Автопроверка: на stage проблемы'}
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
      <Shots taskId={taskId} />
    </Card>
  )
}

const ACCEPTANCE: Record<Acceptance['state'], { title: string; tone: string }> = {
  checking: { title: 'PM проверяет на stage', tone: 'text-accent' },
  fixing: { title: 'PM нашёл замечания и отправил доработку', tone: 'text-warn' },
  accepted: { title: 'PM проверил и принял', tone: 'text-ok' },
  concerns: { title: 'PM: замечания остались', tone: 'text-warn' },
  failed: { title: 'PM не смог проверить', tone: 'text-muted' },
}

/** The PM's check on stage before the owner's: what it found, its screenshots. */
export function AcceptanceCard({ task: t }: { task: Task }) {
  const a = t.acceptance!
  const { title, tone } = ACCEPTANCE[a.state] ?? ACCEPTANCE.failed
  return (
    <Card className="space-y-2 p-4">
      <div className={cx('text-sm font-semibold', tone)}>
        {a.state === 'checking' && <Loader2 size={14} className="mr-1.5 inline animate-spin align-[-2px]" />}
        {title}
        {a.state === 'fixing' && a.fix_task && (
          <>
            {' '}
            <Link href={`/tasks/${a.fix_task.id}`} className="text-accent hover:opacity-80">
              #{a.fix_task.ticket_number}
            </Link>
          </>
        )}
      </div>
      {a.state === 'checking' && (
        <p className="text-sm text-muted">Проходит план проверки как вы, с телефона. Позовёт вас, когда примет.</p>
      )}
      {a.state !== 'checking' && a.summary && <p className="text-[15px] leading-relaxed">{a.summary}</p>}
      {a.state !== 'checking' && a.state !== 'accepted' && (a.issues?.length ?? 0) > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {a.issues!.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
      <Shots taskId={t.id} by="PM" />
    </Card>
  )
}
