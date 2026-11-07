'use client'

import { ChevronRight, Loader2, Send } from 'lucide-react'
import { useState } from 'react'
import { ChatOutcome, ChatSheet, PROJECT_CHAT_HINT } from '@/components/Chat'
import { ProjectChips } from '@/components/ProjectChips'
import { Button, Card, Empty, ErrorNote, inputClass } from '@/components/ui'
import { api, type Chat, type ChatSubject } from '@/lib/api'
import { ago } from '@/lib/format'
import { usePoll, useStoredState } from '@/lib/hooks'

const ALL = '*'

type Opened = { subject: ChatSubject; subjectId: string; id: string }

/** Every conversation with the agent, whatever it is about, and a new one about any project. */
export default function ChatsPage() {
  const [filter, setFilter] = useStoredState<string>('autodev.chats.project', ALL)
  const [opened, setOpened] = useState<Opened | null>(null)
  const [chosen, setChosen] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const projects = usePoll(api.projects, 30000)
  const scope = filter === ALL ? undefined : filter
  const chats = usePoll(() => api.allChats(scope), 10000, [scope])

  const list = projects.data ?? []
  const names = new Map(list.map((p) => [p.id, p.name]))
  // Paused projects can still be discussed: nothing runs until a task is approved.
  const ordered = [...list.filter((p) => p.enabled), ...list.filter((p) => !p.enabled)]
  const projectId = scope ?? (ordered.some((p) => p.id === chosen) ? chosen : (ordered[0]?.id ?? ''))
  const asked = (chats.data ?? []).filter((c) => c.question)

  async function start(e: React.FormEvent) {
    e.preventDefault()
    const body = text.trim()
    if (!body || !projectId) return
    setBusy(true)
    setError(null)
    try {
      const chat = await api.createChat('project', projectId, body)
      setText('')
      setOpened({ subject: 'project', subjectId: projectId, id: chat.id })
      await chats.refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {list.length > 1 && (
        <ProjectChips items={[{ id: ALL, name: 'Все проекты' }, ...list]} value={filter} onChange={setFilter} />
      )}

      <Card className="p-3">
        <form onSubmit={start} className="space-y-2">
          <textarea
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Как устроено… Как лучше сделать…"
            aria-label="Новый разговор"
            className={inputClass}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) start(e)
            }}
          />
          <div className="flex gap-2">
            {!scope && list.length > 1 && (
              <select
                value={projectId}
                onChange={(e) => setChosen(e.target.value)}
                aria-label="Проект"
                className={`${inputClass} min-w-0 flex-1`}
              >
                {ordered.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            <Button type="submit" variant="primary" disabled={busy || !text.trim() || !projectId} className="ml-auto shrink-0">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />} Спросить
            </Button>
          </div>
          <ErrorNote error={error} />
        </form>
      </Card>

      <ErrorNote error={chats.error} />
      {chats.data === null && !chats.error && <Loader2 className="mx-auto mt-10 animate-spin text-muted" />}
      {chats.data && asked.length === 0 && <Empty>Разговоров пока не было</Empty>}
      <ul className="space-y-2">
        {asked.map((c) => (
          <li key={c.id}>
            <ChatRow
              chat={c}
              project={!scope && c.project_id ? names.get(c.project_id) : undefined}
              onOpen={() => setOpened({ subject: c.subject, subjectId: c.subject_id ?? '', id: c.id })}
            />
          </li>
        ))}
      </ul>

      {opened && (
        <ChatSheet
          open
          onClose={() => {
            setOpened(null)
            chats.refresh()
          }}
          onBack={() => {
            setOpened(null)
            chats.refresh()
          }}
          subject={opened.subject}
          subjectId={opened.subjectId}
          openChat={opened.id}
          title="Разговор"
          hint={PROJECT_CHAT_HINT}
          onChange={chats.refresh}
        />
      )}
    </div>
  )
}

function ChatRow({ chat: c, project, onOpen }: { chat: Chat; project?: string; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-2 rounded-2xl border border-line bg-surface px-3 py-2.5 text-left transition hover:bg-surface-2 active:scale-[0.99]"
    >
      <span className="min-w-0 flex-1 space-y-1">
        <span className="line-clamp-2 block break-words text-[15px] leading-snug">{c.question}</span>
        <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <span>{ago(c.updated_at)}</span>
          {project && <span>· {project}</span>}
          {c.subject === 'task' && <span className="min-w-0 truncate">· {c.title}</span>}
          <ChatOutcome chat={c} />
        </span>
      </span>
      <ChevronRight size={16} className="shrink-0 text-muted" />
    </button>
  )
}
