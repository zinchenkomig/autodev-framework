'use client'

import { ArrowLeft, ArrowUp, Check, ChevronRight, Loader2, Plus, Quote, Square, Trash2, X } from 'lucide-react'
import Link from 'next/link'
import { Fragment, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Badge, Button, ErrorNote } from '@/components/ui'
import { api, type Chat, type ChatMessage, type ChatProposal, type ChatSubject } from '@/lib/api'
import { ago, cx, time } from '@/lib/format'

/** The list of chats, or one chat (`id` null: a new question, created when it is sent). */
type View = { kind: 'list' } | { kind: 'chat'; id: string | null }

/**
 * Chats with an agent about a subject (a task now; a project or anything later), in a
 * bottom sheet: a chat per question, the earlier ones listed with what they came to.
 * The agent answers read-only; actions it proposes wait for the owner's approval right
 * here. `quote` (e.g. a test-plan step) opens a new question about it.
 */
export function ChatSheet({
  open,
  onClose,
  subject,
  subjectId,
  title,
  hint,
  quote,
  onChange,
}: {
  open: boolean
  onClose: () => void
  subject: ChatSubject
  subjectId: string
  title: string
  hint: string
  quote?: string | null
  /** Something changed outside the chat: a proposal was applied, a chat created or deleted. */
  onChange?: () => void
}) {
  const [view, setView] = useState<View>({ kind: 'list' })
  const [chats, setChats] = useState<Chat[] | null>(null)
  const [chat, setChat] = useState<Chat | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [pendingQuote, setPendingQuote] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  // With no chats yet, opening the sheet goes straight to a new question.
  const startNew = useRef(false)

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  })

  useEffect(() => {
    if (!open) return
    // A quote means a new question about it; otherwise the list of earlier ones.
    /* eslint-disable react-hooks/set-state-in-effect */
    setPendingQuote(quote ?? null)
    setChat(null)
    setError(null)
    setView(quote ? { kind: 'chat', id: null } : { kind: 'list' })
    /* eslint-enable react-hooks/set-state-in-effect */
    startNew.current = !quote
  }, [open, quote])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [open])

  // Fetched every 2 s while the agent works, else every 15 s.
  const chatId = view.kind === 'chat' ? view.id : null
  const fast = view.kind === 'chat' ? !!chat && chat.state !== 'idle' : !!chats?.some((c) => c.state !== 'idle')
  useEffect(() => {
    if (!open || (view.kind === 'chat' && !chatId)) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    async function tick() {
      try {
        if (chatId) {
          const next = await api.chat(chatId)
          if (!cancelled) setChat(next)
        } else {
          const list = await api.chats(subject, subjectId)
          if (cancelled) return
          setChats(list)
          if (startNew.current && list.length === 0) setView({ kind: 'chat', id: null })
          startNew.current = false
        }
        if (!cancelled) setError(null)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
      if (!cancelled) timer = setTimeout(tick, fast ? 2000 : 15000)
    }
    tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, subject, subjectId, view.kind, chatId, fast])

  const count = chat?.messages.length ?? 0
  const busy = !!chat && chat.state !== 'idle'
  useEffect(() => {
    const box = boxRef.current
    if (box && view.kind === 'chat') box.scrollTop = box.scrollHeight
  }, [count, busy, view.kind])

  function show(next: View) {
    setChat(null)
    setError(null)
    if (next.kind === 'list') setPendingQuote(null)
    setView(next)
  }

  async function run(fn: () => Promise<Chat | void>) {
    setError(null)
    try {
      const next = await fn()
      if (next) setChat(next)
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    }
  }

  async function send() {
    const body = text.trim()
    if (!body || sending) return
    setSending(true)
    const ok = await run(async () => {
      if (chat) return api.sendChat(chat.id, body, pendingQuote)
      const created = await api.createChat(subject, subjectId, body, pendingQuote)
      setView({ kind: 'chat', id: created.id })
      onChange?.()
      return created
    })
    if (ok) {
      setText('')
      setPendingQuote(null)
    }
    setSending(false)
  }

  if (!open) return null
  const listing = view.kind === 'list'
  const heading = listing ? title : chat?.question ? 'Вопрос' : 'Новый вопрос'
  // On <body>: above the bottom tab bar whatever stacking context the page creates.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative flex h-[90dvh] w-full flex-col rounded-t-3xl border border-line bg-surface shadow-2xl sm:h-[80dvh] sm:max-w-lg sm:rounded-3xl">
        <div className="flex items-center gap-1 border-b border-line px-2 py-3">
          {!listing && (
            <button onClick={() => show({ kind: 'list' })} className="rounded-full p-2 hover:bg-surface-2" aria-label="Все вопросы">
              <ArrowLeft size={18} />
            </button>
          )}
          <div className={cx('min-w-0 flex-1', listing && 'pl-2')}>
            <h2 className="truncate text-base font-semibold">{heading}</h2>
            <p className="truncate text-xs text-muted">{listing ? (chats?.[0]?.title ?? '') : (chat?.title ?? title)}</p>
          </div>
          {chat && !busy && (
            <button
              onClick={() =>
                confirm('Удалить этот вопрос вместе с ответами?') &&
                run(async () => {
                  await api.deleteChat(chat.id)
                  onChange?.()
                  show({ kind: 'list' })
                })
              }
              className="rounded-full p-2 text-muted hover:bg-surface-2 hover:text-fg"
              aria-label="Удалить вопрос"
              title="Удалить вопрос"
            >
              <Trash2 size={16} />
            </button>
          )}
          <button onClick={onClose} className="rounded-full p-2 hover:bg-surface-2" aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>

        <div ref={boxRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
          {listing ? (
            <ChatList chats={chats} onOpen={(id) => show({ kind: 'chat', id })} onNew={() => show({ kind: 'chat', id: null })} />
          ) : (
            <>
              {chatId && !chat && !error && <Loader2 className="mx-auto mt-10 animate-spin text-muted" />}
              {!chatId && <p className="px-2 py-6 text-center text-sm text-muted">{hint}</p>}
              {chat?.messages.map((m) => (
                <Message
                  key={m.id}
                  message={m}
                  onDecide={(index, approve) =>
                    run(() => api.decideProposal(chat.id, m.id, index, approve)).then((ok) => ok && onChange?.())
                  }
                />
              ))}
              {busy && chat && (
                <div className="flex items-center gap-2 px-1 text-sm text-muted">
                  <Loader2 size={14} className="shrink-0 animate-spin" />
                  <span className="min-w-0 flex-1 truncate">
                    {chat.stopping ? 'Останавливаю…' : chat.state === 'queued' ? (chat.activity ?? 'Сейчас отвечу…') : (chat.activity ?? 'Думаю…')}
                  </span>
                  {!chat.stopping && (
                    <Button size="sm" variant="ghost" onClick={() => run(() => api.stopChat(chat.id))}>
                      <Square size={12} /> Стоп
                    </Button>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="space-y-2 border-t border-line px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
          <ErrorNote error={error} />
          {!listing && pendingQuote && (
            <div className="flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2 text-xs text-muted">
              <Quote size={12} className="mt-0.5 shrink-0" />
              <span className="line-clamp-2 min-w-0 flex-1">{pendingQuote}</span>
              <button onClick={() => setPendingQuote(null)} aria-label="Убрать цитату" className="shrink-0 hover:text-fg">
                <X size={14} />
              </button>
            </div>
          )}
          {listing ? (
            <Button variant="primary" className="w-full" onClick={() => show({ kind: 'chat', id: null })}>
              <Plus size={16} /> Новый вопрос
            </Button>
          ) : (
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                send()
              }}
            >
              <textarea
                rows={1}
                value={text}
                autoFocus={!chatId}
                onChange={(e) => {
                  setText(e.target.value)
                  e.target.style.height = 'auto'
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
                }}
                onKeyDown={(e) => {
                  // Enter sends on a desktop keyboard; on a phone Enter is a new line.
                  if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer: fine)').matches) {
                    e.preventDefault()
                    send()
                  }
                }}
                placeholder={busy ? 'Дописать…' : chatId ? 'Уточнить…' : 'Вопрос…'}
                className="max-h-40 min-h-11 flex-1 resize-none rounded-2xl border border-line bg-bg px-3 py-2.5 text-[15px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
              />
              <button
                type="submit"
                disabled={(!!chatId && !chat) || !text.trim() || sending}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-accent-fg transition active:scale-95 disabled:opacity-40"
                aria-label="Отправить"
              >
                {sending ? <Loader2 size={18} className="animate-spin" /> : <ArrowUp size={18} />}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** Earlier questions, newest first, each with what it came to. */
function ChatList({ chats, onOpen, onNew }: { chats: Chat[] | null; onOpen: (id: string) => void; onNew: () => void }) {
  if (!chats) return <Loader2 className="mx-auto mt-10 animate-spin text-muted" />
  const asked = chats.filter((c) => c.question)
  if (asked.length === 0) {
    return (
      <button onClick={onNew} className="w-full px-2 py-6 text-center text-sm text-muted">
        Вопросов пока не было
      </button>
    )
  }
  return (
    <ul className="space-y-2">
      {asked.map((c) => (
        <li key={c.id}>
          <button
            onClick={() => onOpen(c.id)}
            className="flex w-full items-center gap-2 rounded-2xl border border-line px-3 py-2.5 text-left transition hover:bg-surface-2 active:scale-[0.99]"
          >
            <span className="min-w-0 flex-1 space-y-1">
              <span className="line-clamp-2 block break-words text-[15px] leading-snug">{c.question}</span>
              <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                <span>{ago(c.updated_at)}</span>
                <ChatOutcome chat={c} />
              </span>
            </span>
            <ChevronRight size={16} className="shrink-0 text-muted" />
          </button>
        </li>
      ))}
    </ul>
  )
}

function ChatOutcome({ chat: c }: { chat: Chat }) {
  if (c.state !== 'idle') {
    return (
      <Badge tone="info">
        <Loader2 size={11} className="animate-spin" /> отвечает
      </Badge>
    )
  }
  const applied = c.outcome.filter((o) => o.state === 'applied')
  return (
    <>
      {c.pending > 0 && <Badge tone="warn">ждёт решения</Badge>}
      {applied.map((o, i) => (
        <Badge key={i} tone="ok">
          {o.label.toLowerCase()}
          {o.ticket_number ? ` → #${o.ticket_number}` : ''}
        </Badge>
      ))}
      {c.pending === 0 && applied.length === 0 && c.outcome.length > 0 && <Badge>отклонено</Badge>}
    </>
  )
}

function Message({
  message: m,
  onDecide,
}: {
  message: ChatMessage
  onDecide: (index: number, approve: boolean) => Promise<unknown>
}) {
  if (m.role === 'event') return <p className="px-6 text-center text-xs text-muted">{m.text}</p>
  if (m.role === 'error') {
    return <p className="mx-auto max-w-[85%] rounded-xl bg-bad/10 px-3 py-2 text-xs text-bad">Не получилось ответить: {m.text}</p>
  }
  const mine = m.role === 'user'
  return (
    <div className={cx('flex flex-col gap-1.5', mine ? 'items-end' : 'items-start')}>
      <div
        className={cx(
          'max-w-[88%] rounded-2xl px-3 py-2 text-[15px] leading-relaxed',
          mine ? 'rounded-br-md bg-accent text-accent-fg' : 'rounded-bl-md bg-surface-2',
        )}
      >
        {m.quote && (
          <div className={cx('mb-1 border-l-2 pl-2 text-xs', mine ? 'border-accent-fg/50 opacity-80' : 'border-line text-muted')}>
            <span className="line-clamp-3">{m.quote}</span>
          </div>
        )}
        {mine ? <p className="whitespace-pre-wrap break-words">{m.text}</p> : <Markdown text={m.text} />}
      </div>
      {m.proposals.map((p, i) => (
        <ProposalCard key={i} proposal={p} onDecide={(approve) => onDecide(i, approve)} />
      ))}
      <span className="px-1 text-[10px] text-muted">{time(m.created_at).slice(0, 5)}</span>
    </div>
  )
}

function ProposalCard({ proposal: p, onDecide }: { proposal: ChatProposal; onDecide: (approve: boolean) => Promise<unknown> }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const decide = async (approve: boolean) => {
    setBusy(true)
    await onDecide(approve)
    setBusy(false)
  }
  return (
    <div className={cx('w-[88%] rounded-2xl border p-3', p.state === 'pending' ? 'border-accent/40 bg-accent/5' : 'border-line')}>
      <div className="text-xs font-medium text-muted">Предлагаю · {p.label}</div>
      <div className={cx('mt-0.5 text-[15px] font-medium leading-snug', p.state === 'rejected' && 'text-muted line-through')}>{p.title}</div>
      <button onClick={() => setOpen(!open)} className="mt-1 text-left text-xs text-muted">
        <span className={cx('whitespace-pre-wrap break-words', !open && 'line-clamp-2')}>{p.description}</span>
      </button>
      {p.state === 'pending' && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" variant="primary" disabled={busy} onClick={() => decide(true)}>
            <Check size={14} /> {p.label}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide(false)}>
            Не надо
          </Button>
        </div>
      )}
      {p.state === 'applied' && (
        <div className="mt-2 text-xs text-ok">
          {p.result?.task_id ? (
            <Link href={`/tasks/${p.result.task_id}`} className="underline">
              Задача #{p.result.ticket_number} →
            </Link>
          ) : (
            'Сделано'
          )}
        </div>
      )}
      {p.state === 'rejected' && <div className="mt-2 text-xs text-muted">Отклонено</div>}
    </div>
  )
}

/** The light Markdown the agent writes: paragraphs, lists, **bold** and `code`. */
function Markdown({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/)
  return (
    <div className="space-y-2 break-words">
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
          const ordered = /^\s*\d/.test(lines[0])
          const items = lines.map((l) => l.replace(/^\s*([-*•]|\d+[.)])\s+/, ''))
          const List = ordered ? 'ol' : 'ul'
          return (
            <List key={i} className={cx('space-y-1 pl-5', ordered ? 'list-decimal' : 'list-disc')}>
              {items.map((item, j) => (
                <li key={j}>
                  <Inline text={item} />
                </li>
              ))}
            </List>
          )
        }
        return (
          <p key={i} className="whitespace-pre-wrap">
            <Inline text={block} />
          </p>
        )
      })}
    </div>
  )
}

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : part.startsWith('`') && part.endsWith('`') && part.length > 2 ? (
          <code key={i} className="rounded bg-bg px-1 py-0.5 font-mono text-[13px]">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}
