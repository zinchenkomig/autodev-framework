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

// ─── Message ──────────────────────────────────────────────────────────────────

function Message({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'

  return (
    <div className={cn('flex flex-col gap-1', isUser ? 'items-end' : 'items-start')}>
      <p className={cn(
        'text-sm leading-relaxed whitespace-pre-wrap break-words max-w-xl',
        isUser ? 'text-[#FAFAFA]' : 'text-[#71717A]'
      )}>
        {msg.content}
      </p>

      {msg.tasks_created && msg.tasks_created.length > 0 && (
        <div className="flex flex-col gap-1 w-full max-w-xl mt-1">
          {msg.tasks_created.map(t => (
            <div key={t.id} className="flex items-center gap-2 border border-[#1F1F23] px-3 py-1.5 text-xs">
              <span className="font-mono text-[#3F3F46]">#{t.id.slice(0, 8)}</span>
              <span className="flex-1 truncate text-[#71717A]">{t.title}</span>
              <span className="text-[#6366F1] font-mono">{t.priority}</span>
            </div>
          ))}
        </div>
      )}

      {msg.created_at && (
        <span className="text-xs text-[#3F3F46]">
          {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      )}
    </div>
  )
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1">
      <span className="w-1 h-1 rounded-full bg-[#3F3F46] animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1 h-1 rounded-full bg-[#3F3F46] animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1 h-1 rounded-full bg-[#3F3F46] animate-bounce" style={{ animationDelay: '300ms' }} />
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
    <div className="flex flex-col h-[calc(100vh-4rem)] -m-6 md:-m-8">

      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-[#1F1F23] shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm text-[#FAFAFA]">PM Agent</span>
          <span className="text-xs text-[#22C55E]">● online</span>
        </div>
        <button
          onClick={handleReload}
          className="p-1.5 text-[#3F3F46] hover:text-[#71717A] transition-colors"
        >
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-4 h-4 text-[#3F3F46] animate-spin" />
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
                      <span className="text-xs text-[#3F3F46]">
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
        <div className="px-6 py-2 flex flex-wrap gap-2 border-t border-[#1F1F23] shrink-0">
          {SUGGESTIONS.map(s => (
            <button
              key={s}
              onClick={() => handleSend(s)}
              disabled={sending}
              className="px-3 py-1 border border-[#1F1F23] text-[#71717A] text-xs hover:border-[#3F3F46] hover:text-[#FAFAFA] transition-colors disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-6 py-4 border-t border-[#1F1F23] shrink-0">
        <div className="flex items-end gap-3 max-w-3xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Write a task or question... (Enter to send)"
            rows={1}
            disabled={sending || loading}
            className={cn(
              'flex-1 resize-none bg-transparent border-b border-[#1F1F23] py-2',
              'text-[#FAFAFA] placeholder-[#3F3F46] text-sm leading-relaxed',
              'focus:outline-none focus:border-[#6366F1]/50',
              'disabled:opacity-50 min-h-[36px] max-h-40 overflow-y-auto',
              'transition-colors'
            )}
            style={{ height: 'auto' }}
            onInput={e => {
              const el = e.currentTarget
              el.style.height = 'auto'
              el.style.height = Math.min(el.scrollHeight, 160) + 'px'
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || sending || loading}
            className={cn(
              'shrink-0 w-8 h-8 flex items-center justify-center transition-colors',
              'text-[#6366F1] hover:text-[#818CF8]',
              'disabled:opacity-30 disabled:cursor-not-allowed',
            )}
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
