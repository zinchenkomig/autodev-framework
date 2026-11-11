import { Check, CircleHelp, Loader2, RotateCw } from 'lucide-react'
import { Inline } from '@/components/Markdown'
import { Button, Card } from '@/components/ui'
import type { Task } from '@/lib/api'
import { cx } from '@/lib/format'

/** The owner's manual check on stage: steps to tick, a question about any of them, a rebuild. */
export function TestPlan({
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
          Агент собирает план заново по задаче, её доработкам и коду на stage — ход видно в «Шагах агента».
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
                  <span
                    className={cx(
                      'break-words',
                      done ? 'line-clamp-1 text-sm text-muted line-through' : 'block whitespace-pre-wrap text-[15px] leading-relaxed',
                    )}
                  >
                    <Inline text={step} />
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
