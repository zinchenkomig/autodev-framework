'use client'

import { Loader2, Send } from 'lucide-react'
import { useState } from 'react'
import { ChatRow, ChatSheet, PROJECT_CHAT_HINT } from '@/components/Chat'
import { ProjectChips } from '@/components/ProjectChips'
import { Button, Card, Empty, ErrorNote, inputClass } from '@/components/ui'
import { api, type ChatSubject } from '@/lib/api'
import { enabledFirst } from '@/lib/format'
import { ALL_PROJECTS, usePoll, useProjectFilter } from '@/lib/hooks'

type Opened = { subject: ChatSubject; subjectId: string; id: string }

/** Every conversation with the agent, whatever it is about, and a new one about any project. */
export default function ChatsPage() {
  const [opened, setOpened] = useState<Opened | null>(null)
  const [chosen, setChosen] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const projects = usePoll(api.projects, 30000)
  const [filter, setFilter] = useProjectFilter('autodev.chats.project', projects.data)
  const scope = filter === ALL_PROJECTS ? undefined : filter
  const chats = usePoll(() => api.allChats(scope), 10000, [scope])

  const list = projects.data ?? []
  const names = new Map(list.map((p) => [p.id, p.name]))
  // Paused projects can still be discussed: nothing runs until a task is approved.
  const ordered = enabledFirst(list)
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
        <ProjectChips items={[{ id: ALL_PROJECTS, name: 'Все проекты' }, ...list]} value={filter} onChange={setFilter} />
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
              showTask
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
