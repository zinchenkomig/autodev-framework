'use client'

import { Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { Badge, Card } from '@/components/ui'
import type { Task } from '@/lib/api'
import { STATUS, dateTime, followUpRequest } from '@/lib/format'

/** First line of an agent summary, without Markdown marks: the gist for a compact list. */
function gist(summary: string): string {
  const line = summary.split('\n').find((l) => l.trim() && !/^\s*#/.test(l)) ?? ''
  return line.replace(/\*\*|`/g, '').replace(/^\s*([-*•]|\d+[.)])\s+/, '').trim()
}

const FOLLOW_UPS_SHOWN = 5

/** The main task's history: each follow-up, compact — what was asked and the gist of what was done. */
export function FollowUps({ items: data }: { items: Task[] }) {
  const [all, setAll] = useState(false)
  if (!data.length) return null
  const shown = all ? data : data.slice(-FOLLOW_UPS_SHOWN)
  return (
    <Card className="p-2">
      <div className="px-2 pb-1 pt-2 text-sm font-semibold">История доработок · {data.length}</div>
      {shown.length < data.length && (
        <button onClick={() => setAll(true)} className="px-2 py-1 text-xs text-muted hover:text-fg">
          Показать ранние · {data.length - shown.length}
        </button>
      )}
      <ol>
        {shown.map((c) => {
          const s = STATUS[c.status]
          const asked = followUpRequest(c)
          return (
            <li key={c.id} className="border-t border-line first:border-t-0">
              <Link href={`/tasks/${c.id}`} className="block space-y-0.5 rounded-xl px-2 py-2 hover:bg-surface-2">
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span className="font-mono">#{c.ticket_number}</span>
                  <span className="truncate">{dateTime(c.created_at)}</span>
                  <Badge tone={s.tone} className="ml-auto shrink-0 whitespace-nowrap">
                    {c.status === 'in_progress' && <Loader2 size={12} className="animate-spin" />}
                    {s.label}
                  </Badge>
                </div>
                <p className="line-clamp-2 break-words text-sm leading-snug">
                  {asked || c.title}
                </p>
                {c.summary && <p className="line-clamp-1 break-words text-xs text-muted">{gist(c.summary)}</p>}
              </Link>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
