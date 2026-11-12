'use client'

import { ChevronDown, ExternalLink, GitPullRequest } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui'
import type { Task } from '@/lib/api'
import { cx } from '@/lib/format'

/** The task's PR; with follow-ups, a menu of every PR — the main one first. */
export function PullRequests({ task, followUps }: { task: Task; followUps: Task[] }) {
  const [open, setOpen] = useState(false)
  const prs = [task, ...followUps].filter((t) => t.pr_url)
  if (prs.length === 0) return null
  if (prs.length === 1)
    return (
      <a href={prs[0].pr_url!} target="_blank" rel="noreferrer">
        <Button size="sm">
          <GitPullRequest size={15} /> PR #{prs[0].pr_number}
        </Button>
      </a>
    )
  const failed = task.full_diff?.error
  return (
    <div className="relative">
      <Button size="sm" onClick={() => setOpen(!open)} aria-expanded={open}>
        <GitPullRequest size={15} /> PR · {prs.length}
        <ChevronDown size={14} className={cx('text-muted transition', open && 'rotate-180')} />
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="fixed inset-x-4 z-20 mt-1 rounded-xl sm:absolute sm:inset-x-auto sm:left-0 sm:top-full sm:w-80 border border-line bg-surface p-1 shadow-xl">
            {prs.map((t) => (
              <a
                key={t.id}
                href={t.pr_url!}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2"
              >
                <span className="shrink-0 font-mono text-xs text-muted">#{t.pr_number}</span>
                <span className="min-w-0 flex-1 truncate">{t.id === task.id ? 'Основная задача' : t.title}</span>
                <ExternalLink size={12} className="shrink-0 text-muted" />
              </a>
            ))}
            {failed && <p className="border-t border-line px-2.5 py-2 text-xs text-muted">Одним сравнением не собрать: {failed}</p>}
          </div>
        </>
      )}
    </div>
  )
}
