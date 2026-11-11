'use client'

import { ChevronDown, ExternalLink } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Markdown } from '@/components/Markdown'
import { Card, Collapsible, ErrorNote } from '@/components/ui'
import { api, type LogEntry, type Task } from '@/lib/api'
import { cx, time } from '@/lib/format'

/** What the agent did — its summary up front, the step-by-step log folded underneath. */
export function WorkLog({ task: t, live }: { task: Task; live: boolean }) {
  const log = useTaskLog(t.id, live)
  // Open while the agent works and there's nothing else to read yet.
  const [open, setOpen] = useState<boolean | null>(null)
  const showLog = open ?? (live && !t.summary)
  const last = log.entries[log.entries.length - 1]
  return (
    <Card className="overflow-hidden">
      {t.summary && (
        <div className="p-4 pb-3">
          <div className="mb-1.5 text-sm font-semibold text-muted">Что сделано</div>
          <Collapsible height="max-h-72">
            <Markdown text={t.summary} className="text-[15px] leading-relaxed" />
          </Collapsible>
        </div>
      )}
      <button
        onClick={() => setOpen(!showLog)}
        className={cx('flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-2', t.summary && 'border-t border-line')}
      >
        <span className="shrink-0 text-sm font-semibold">{t.summary ? 'Шаги агента' : live ? 'Агент работает' : 'Шаги агента'}</span>
        {live && <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-ok" />}
        <span className="min-w-0 flex-1 truncate text-xs text-muted">
          {!showLog && (live && last ? last.message : log.entries.length > 0 && `${log.entries.length}`)}
        </span>
        <ChevronDown size={16} className={cx('shrink-0 text-muted transition', showLog && 'rotate-180')} />
      </button>
      {showLog && <LogEntries {...log} />}
    </Card>
  )
}

function useTaskLog(taskId: string, live: boolean) {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [error, setError] = useState<Error | null>(null)
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

  return { entries, error, boxRef }
}

const LEVEL_STYLE: Record<string, string> = {
  error: 'text-bad',
  warning: 'text-warn',
  transition: 'text-accent font-medium',
}


function LogEntries({ entries, error, boxRef }: ReturnType<typeof useTaskLog>) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  // Mounted on open: start at the newest entry.
  useEffect(() => {
    const box = boxRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [boxRef])
  return (
    <div ref={boxRef} className="max-h-[60dvh] overflow-y-auto border-t border-line px-2 py-2">
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
  )
}
