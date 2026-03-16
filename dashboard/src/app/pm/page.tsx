'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Loader2, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? ''

// ─── Types ────────────────────────────────────────────────────────────────────

interface TaskCreated {
  id: string
  title: string
  priority: string
}

interface ChatMessage {
  id: string
  role: 'user' | 'pm'
  content: string
  created_at?: string
  tasks_created?: TaskCreated[]
}

// ─── API helpers ──────────────────────────────────────────────────────────────

async function sendMessage(message: string): Promise<{ response: string; tasks_created: TaskCreated[] }> {
  const res = await fetch(`${BASE_URL}/pm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchHistory(): Promise<ChatMessage[]> {
  const res = await fetch(`${BASE_URL}/pm/history`)
  if (!res.ok) return []
  return res.json()
}

// ─── Priority badge ───────────────────────────────────────────────────────────

const priorityBadge: Record<string, { bg: string; color: string }> = {
  critical: { bg: '#CC4E4E', color: '#fff' },
  high:     { bg: '#CC7832', color: '#fff' },
  normal:   { bg: '#3592C4', color: '#fff' },
  low:      { bg: '#414345', color: '#BABABA' },
}

// ─── Message ──────────────────────────────────────────────────────────────────

function Message({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'

  return (
    <div className={cn('flex flex-col gap-1.5', isUser ? 'items-end' : 'items-start')}>
      {!isUser && (
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className="text-base">🤖</span>
          <span className="text-xs font-medium" style={{ color: '#3592C4' }}>PM Agent</span>
        </div>
      )}
      <div
        className="px-4 py-2.5 max-w-xl"
        style={{
          background: isUser ? '#214283' : '#3C3F41',
          borderRadius: isUser ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
          border: `1px solid ${isUser ? '#2a5298' : '#515151'}`,
        }}
      >
        <p className="text-sm leading-relaxed whitespace-pre-wrap break-words" style={{ color: isUser ? '#FFFFFF' : '#BABABA' }}>
          {msg.content}
        </p>
      </div>

      {msg.tasks_created && msg.tasks_created.length > 0 && (
        <div className="flex flex-col gap-1.5 w-full max-w-xl mt-1">
          <p className="text-xs" style={{ color: '#808080' }}>Tasks created:</p>
          {msg.tasks_created.map(t => {
            const badge = priorityBadge[t.priority] ?? priorityBadge.normal
            return (
              <div
                key={t.id}
                className="flex items-center gap-2 px-3 py-2 text-xs"
                style={{
                  background: '#313335',
                  border: '1px solid #515151',
                  borderRadius: '4px',
                }}
              >
                <span className="font-mono" style={{ color: '#808080' }}>#{t.id.slice(0, 8)}</span>
                <span className="flex-1 truncate" style={{ color: '#BABABA' }}>{t.title}</span>
                <span
                  className="px-1.5 py-0.5 rounded font-mono text-xs font-medium"
                  style={{ color: badge.color, background: badge.bg }}
                >
                  {t.priority}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {msg.created_at && (
        <span className="text-xs" style={{ color: '#808080' }}>
          {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      )}
    </div>
  )
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex items-center gap-2">
      <span className="text-base">🤖</span>
      <div
        className="flex items-center gap-1 px-3 py-2"
        style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '12px 12px 12px 4px' }}
      >
        {[0, 150, 300].map(delay => (
          <span
            key={delay}
            className="w-1.5 h-1.5 rounded-full animate-bounce"
            style={{ background: '#808080', animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
    </div>
  )
}

// ─── Suggestions ──────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  'Project status?',
  'What to do next?',
  'Add auth to the app',
  'Add notifications',
  'Add task search',
]

// ─── Main page ────────────────────────────────────────────────────────────────

export default function PMChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    fetchHistory()
      .then(history => {
        if (history.length === 0) {
          setMessages([{
            id: 'welcome',
            role: 'pm',
            content: 'Hi. I\'m the PM agent. Describe a task or ask about project status.',
            created_at: new Date().toISOString(),
          }])
        } else {
          setMessages(history)
        }
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  const handleSend = async (text?: string) => {
    const msg = (text ?? input).trim()
    if (!msg || sending) return

    setInput('')
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: msg,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setSending(true)

    try {
      const { response, tasks_created } = await sendMessage(msg)
      const pmMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'pm',
        content: response,
        created_at: new Date().toISOString(),
        tasks_created,
      }
      setMessages(prev => [...prev, pmMsg])
    } catch {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'pm',
        content: 'Connection error. Please try again.',
        created_at: new Date().toISOString(),
      }])
    } finally {
      setSending(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleReload = () => {
    setLoading(true)
    fetchHistory()
      .then(setMessages)
      .finally(() => setLoading(false))
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] -m-6 md:-m-8" style={{ background: '#2B2B2B' }}>

      {/* Header */}
      <div
        className="flex items-center justify-between px-6 py-3 shrink-0"
        style={{ borderBottom: '1px solid #515151', background: '#313335' }}
      >
        <div className="flex items-center gap-3">
          <span className="text-base">🤖</span>
          <div>
            <span className="text-sm font-semibold" style={{ color: '#FFFFFF' }}>PM Agent</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span
                className="w-1.5 h-1.5 rounded-full animate-status-pulse"
                style={{ background: '#6A8759', display: 'inline-block' }}
              />
              <span className="text-xs" style={{ color: '#6A8759' }}>online</span>
            </div>
          </div>
        </div>
        <button
          onClick={handleReload}
          className="p-1.5 transition-colors"
          style={{ color: '#808080' }}
          onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = '#BABABA'}
          onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = '#808080'}
        >
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
          </div>
        ) : (
          <>
            {messages.map((msg, i) => {
              const prevMsg = messages[i - 1]
              const showTime = !prevMsg || (
                msg.created_at && prevMsg.created_at &&
                new Date(msg.created_at).getTime() - new Date(prevMsg.created_at).getTime() > 5 * 60 * 1000
              )

              return (
                <div key={msg.id}>
                  {showTime && msg.created_at && (
                    <div className="text-center my-3">
                      <span
                        className="text-xs px-3 py-1 rounded"
                        style={{ color: '#808080', background: '#313335' }}
                      >
                        {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  )}
                  <Message msg={msg} />
                </div>
              )
            })}
            {sending && <TypingIndicator />}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      {!loading && messages.length <= 1 && (
        <div
          className="px-6 py-3 flex flex-wrap gap-2 shrink-0"
          style={{ borderTop: '1px solid #515151', background: '#313335' }}
        >
          {SUGGESTIONS.map(s => (
            <button
              key={s}
              onClick={() => handleSend(s)}
              disabled={sending}
              className="px-3 py-1.5 text-xs transition-colors disabled:opacity-50"
              style={{
                border: '1px solid #515151',
                color: '#BABABA',
                borderRadius: '4px',
                background: '#3C3F41',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = '#3592C4'
                ;(e.currentTarget as HTMLButtonElement).style.color = '#FFFFFF'
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = '#515151'
                ;(e.currentTarget as HTMLButtonElement).style.color = '#BABABA'
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input area */}
      <div
        className="px-6 py-4 shrink-0"
        style={{ borderTop: '1px solid #515151', background: '#3C3F41' }}
      >
        <div
          className="flex items-end gap-3 max-w-3xl mx-auto p-3"
          style={{
            background: '#2B2B2B',
            border: '1px solid #515151',
            borderRadius: '6px',
          }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Write a task or question... (Enter to send)"
            rows={1}
            disabled={sending || loading}
            className="flex-1 resize-none bg-transparent py-1 text-sm leading-relaxed focus:outline-none disabled:opacity-50 min-h-[28px] max-h-40 overflow-y-auto"
            style={{ color: '#BABABA' }}
            onInput={e => {
              const el = e.currentTarget
              el.style.height = 'auto'
              el.style.height = Math.min(el.scrollHeight, 160) + 'px'
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || sending || loading}
            className="shrink-0 w-8 h-8 flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{
              background: '#3592C4',
              borderRadius: '4px',
              color: '#FFFFFF',
            }}
            onMouseEnter={e => {
              if (input.trim()) (e.currentTarget as HTMLButtonElement).style.background = '#2a7aaa'
            }}
            onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.background = '#3592C4'}
          >
            {sending
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <Send className="w-4 h-4" />
            }
          </button>
        </div>
      </div>
    </div>
  )
}
