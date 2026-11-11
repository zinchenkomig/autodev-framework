'use client'

import { useState } from 'react'
import { Lightbox } from '@/components/ui'
import { api } from '@/lib/api'
import { usePoll } from '@/lib/hooks'

const SHOT_AUTHOR = /^(PM|Скаут): /

/** Screenshots of the task: the stage QA's, or the PM's ("PM: …") or the scout's ("Скаут: …"). */
export function Shots({ taskId, by }: { taskId: string; by?: 'PM' | 'Скаут' }) {
  const { data: artifacts } = usePoll(() => api.artifacts(taskId), 60000, [taskId])
  const [open, setOpen] = useState<number | null>(null)
  const shots = (artifacts ?? []).filter((a) => a.kind === 'screenshot' && (by ? a.name.startsWith(`${by}: `) : !SHOT_AUTHOR.test(a.name)))
  if (shots.length === 0) return null
  const caption = (name: string) => name.replace(SHOT_AUTHOR, '').replace(/^https?:\/\/[^/]+/, '') || '/'
  return (
    <div className="no-scrollbar -mx-1 flex snap-x gap-2 overflow-x-auto px-1">
      {shots.map((a, i) => (
        <a
          key={a.id}
          href={api.artifactUrl(a.url)}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
            e.preventDefault()
            setOpen(i)
          }}
          className="w-16 shrink-0 snap-start"
          title={caption(a.name)}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={api.artifactUrl(a.url)}
            alt={a.name}
            loading="lazy"
            className="aspect-[390/844] w-full rounded-lg border border-line object-cover object-top"
          />
        </a>
      ))}
      <Lightbox
        images={shots.map((a) => ({ src: api.artifactUrl(a.url), caption: caption(a.name) }))}
        index={open}
        onIndex={setOpen}
        onClose={() => setOpen(null)}
      />
    </div>
  )
}
