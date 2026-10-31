'use client'

import { ArrowUp, Check, Loader2, Quote, RotateCcw, Square, X } from 'lucide-react'
import Link from 'next/link'
import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button, ErrorNote } from '@/components/ui'
import { api, type Chat, type ChatMessage, type ChatProposal, type ChatSubject } from '@/lib/api'
import { cx, time } from '@/lib/format'

/**
 * A chat with an agent about a subject (a task now; a project or anything later), in a
 * bottom sheet. The agent answers read-only; actions it proposes wait for the owner's
 * approval right here. `quote` is what the question is about, e.g. a test-plan step.
 */
export function ChatSheet({
  open,
  onClose,
  subject,
  subjectId,
  title,
  hint,
  quote,
  onApplied,
}: {
  open: boolean
  onClose: () => void
  subject: ChatSubject
  subjectId: string
  title: string
  hint: string
  quote?: string | null
  onApplied?: () => void
}) {
  const { chat, setChat, error, setError } = useChat(open, subject, subjectId)
  const [text, setText] = useState('')
  const [pendingQuote, setPendingQuote] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  })

  useEffect(() => {
    // Opened for a new question about something else: take its quote.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (open) setPendingQuote(quote ?? null)
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

  const count = chat?.messages.length ?? 0
  const busy = !!chat && chat.state !== 'idle'
  useEffect(() => {
    const box = boxRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [count, busy, open])

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
    if (!chat || !body || sending) return
    setSending(true)
    if (await run(() => api.sendChat(chat.id, body, pendingQuote))) {
      setText('')
      setPendingQuote(null)
    }
    setSending(false)
  }

  if (!open) return null
  // On <body>: above the bottom tab bar whatever stacking context the page creates.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative flex h-[90dvh] w-full flex-col rounded-t-3xl border border-line bg-surface shadow-2xl sm:h-[80dvh] sm:max-w-lg sm:rounded-3xl">
        <div className="flex items-center gap-2 border-b border-line px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {chat && <p className="truncate text-xs text-muted">{chat.title}</p>}
          </div>
          {chat && count > 0 && !busy && (
            <button
              onClick={() =>
                confirm('Начать разговор заново? История удалится.') &&
                run(async () => {
                  await api.deleteChat(chat.id)
                  return api.openChat(subject, subjectId)
                })
              }
              className="rounded-full p-2 text-muted hover:bg-surface-2 hover:text-fg"
              aria-label="Начать заново"
              title="Начать заново"
            >
              <RotateCcw size={16} />
            </button>
          )}
          <button onClick={onClose} className="rounded-full p-2 hover:bg-surface-2" aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>

        <div ref={boxRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
          {!chat && !error && <Loader2 className="mx-auto mt-10 animate-spin text-muted" />}
          {chat && count === 0 && <p className="px-2 py-6 text-center text-sm text-muted">{hint}</p>}
          {chat?.messages.map((m) => (
            <Message
              key={m.id}
              message={m}
              onDecide={(index, approve) =>
                run(() => api.decideProposal(chat.id, m.id, index, approve)).then((ok) => ok && approve && onApplied?.())
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
        </div>

        <div className="space-y-2 border-t border-line px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
          <ErrorNote error={error} />
          {pendingQuote && (
            <div className="flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2 text-xs text-muted">
              <Quote size={12} className="mt-0.5 shrink-0" />
              <span className="line-clamp-2 min-w-0 flex-1">{pendingQuote}</span>
              <button onClick={() => setPendingQuote(null)} aria-label="Убрать цитату" className="shrink-0 hover:text-fg">
                <X size={14} />
              </button>
            </div>
          )}
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
              placeholder={busy ? 'Дописать…' : 'Вопрос…'}
              className="max-h-40 min-h-11 flex-1 resize-none rounded-2xl border border-line bg-bg px-3 py-2.5 text-[15px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
            />
            <button
              type="submit"
              disabled={!chat || !text.trim() || sending}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-accent-fg transition active:scale-95 disabled:opacity-40"
              aria-label="Отправить"
            >
              {sending ? <Loader2 size={18} className="animate-spin" /> : <ArrowUp size={18} />}
            </button>
          </form>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** The chat about a subject while the sheet is open: fetched every 2 s while the agent works, else every 15 s. */
function useChat(open: boolean, subject: ChatSubject, subjectId: string) {
  const [chat, setChatState] = useState<Chat | null>(null)
  const [error, setError] = useState<string | null>(null)
  const chatRef = useRef<Chat | null>(null)
  const setChat = useCallback((next: Chat) => {
    chatRef.current = next
    setChatState(next)
  }, [])
  const working = !!chat && chat.state !== 'idle'

  useEffect(() => {
    if (!open) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    async function tick() {
      try {
        const current = chatRef.current
        const next =
          current && current.subject_id === subjectId ? await api.chat(current.id) : await api.openChat(subject, subjectId)
        if (cancelled) return
        setChat(next)
        setError(null)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
      if (!cancelled) timer = setTimeout(tick, chatRef.current && chatRef.current.state !== 'idle' ? 2000 : 15000)
    }
    tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // `working` restarts the loop, so a message just sent is followed at the fast pace right away.
  }, [open, subject, subjectId, working, setChat])

  return { chat, setChat, error, setError }
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
