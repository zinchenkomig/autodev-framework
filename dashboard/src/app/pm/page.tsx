'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Bot, User, Loader2, RefreshCw } from 'lucide-react'
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

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    critical: 'bg-red-500/20 text-red-400 border-red-500/30',
    high:     'bg-orange-500/20 text-orange-400 border-orange-500/30',
    normal:   'bg-blue-500/20 text-blue-400 border-blue-500/30',
    low:      'bg-gray-500/20 text-gray-400 border-gray-500/30',
  }
  return (
    <span className={cn(
      'inline-flex items-center px-1.5 py-0.5 rounded text-xs border font-medium',
      colors[priority] ?? colors.normal
    )}>
      {priority}
    </span>
  )
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'

  return (
    <div className={cn('flex gap-3 max-w-3xl', isUser ? 'flex-row-reverse ml-auto' : 'mr-auto')}>
      {/* Avatar */}
      <div className={cn(
        'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
        isUser ? 'bg-blue-500/20 border border-blue-500/40' : 'bg-emerald-500/20 border border-emerald-500/40'
      )}>
        {isUser
          ? <User className="w-4 h-4 text-blue-400" />
          : <Bot className="w-4 h-4 text-emerald-400" />
        }
      </div>

      {/* Bubble */}
      <div className={cn(
        'flex flex-col gap-2',
        isUser ? 'items-end' : 'items-start'
      )}>
        <div className={cn(
          'px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words max-w-xl',
          isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : 'bg-gray-800 text-gray-100 border border-gray-700 rounded-tl-sm'
        )}>
          {msg.content}
        </div>

        {/* Tasks created list */}
        {msg.tasks_created && msg.tasks_created.length > 0 && (
          <div className="flex flex-col gap-1.5 w-full max-w-xl">
            {msg.tasks_created.map(t => (
              <div key={t.id} className="flex items-center gap-2 px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-xs text-gray-300">
                <span className="font-mono text-gray-500">#{t.id.slice(0, 8)}</span>
                <span className="flex-1 truncate">{t.title}</span>
                <PriorityBadge priority={t.priority} />
              </div>
            ))}
          </div>
        )}

        {msg.created_at && (
          <span className="text-xs text-gray-600">
            {new Date(msg.created_at).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex gap-3 max-w-3xl mr-auto">
      <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-emerald-500/20 border border-emerald-500/40">
        <Bot className="w-4 h-4 text-emerald-400" />
      </div>
      <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-gray-800 border border-gray-700 flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}

// ─── Suggestion chips ─────────────────────────────────────────────────────────

const SUGGESTIONS = [
  'Какой статус проекта?',
  'Что делать дальше?',
  'Добавь авторизацию в приложение',
  'Добавь систему уведомлений',
  'Добавь поиск по задачам',
]

// ─── Main page ────────────────────────────────────────────────────────────────

export default function PMChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Load history on mount; show welcome message if empty
  useEffect(() => {
    fetchHistory()
      .then(history => {
        if (history.length === 0) {
          setMessages([{
            id: 'welcome',
            role: 'pm',
            content: 'Привет! Я PM этого проекта. Могу:\n• Создать задачи — просто опиши что нужно\n• Показать статус — спроси "статус"\n• Предложить задачи — спроси "что делать?"\n\nЧем помочь?',
            created_at: new Date().toISOString(),
          }])
        } else {
          setMessages(history)
        }
      })
      .finally(() => setLoading(false))
  }, [])

  // Scroll to bottom on new messages
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
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'pm',
        content: '❌ Ошибка связи с PM агентом. Попробуйте ещё раз.',
        created_at: new Date().toISOString(),
      }
      setMessages(prev => [...prev, errMsg])
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

  const isEmpty = !loading && messages.length === 0

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] -m-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 bg-gray-950 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
            <Bot className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h1 className="text-white font-semibold text-lg leading-none">PM Agent</h1>
            <p className="text-gray-500 text-xs mt-0.5">Project Manager · rule-based AI</p>
          </div>
          <span className="ml-2 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            online
          </span>
        </div>
        <button
          onClick={handleReload}
          className="p-2 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          title="Обновить историю"
        >
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>
      </div>

      {/* ── Messages ── */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
          </div>
        ) : (
          <>
            {isEmpty && (
              <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
                <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <Bot className="w-8 h-8 text-emerald-400" />
                </div>
                <div>
                  <p className="text-white font-medium text-lg">Привет! Я PM агент</p>
                  <p className="text-gray-400 text-sm mt-1 max-w-sm">
                    Опишите задачу в свободной форме — я разобью её на подзадачи и добавлю в очередь.
                    Или спросите о статусе проекта.
                  </p>
                </div>
              </div>
            )}

            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}

            {sending && <TypingIndicator />}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Suggestions (shown when no messages) ── */}
      {isEmpty && !loading && (
        <div className="px-6 py-3 flex flex-wrap gap-2 border-t border-gray-800/50 flex-shrink-0">
          {SUGGESTIONS.map(s => (
            <button
              key={s}
              onClick={() => handleSend(s)}
              disabled={sending}
              className="px-3 py-1.5 rounded-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs transition-colors disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* ── Input ── */}
      <div className="px-6 py-4 border-t border-gray-800 bg-gray-950 flex-shrink-0">
        <div className="flex items-end gap-3 max-w-4xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Напишите задачу или вопрос... (Enter — отправить, Shift+Enter — новая строка)"
            rows={1}
            disabled={sending || loading}
            className={cn(
              'flex-1 resize-none bg-gray-800 border border-gray-700 rounded-xl px-4 py-3',
              'text-gray-100 placeholder-gray-500 text-sm leading-relaxed',
              'focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20',
              'disabled:opacity-50 min-h-[48px] max-h-40 overflow-y-auto',
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
              'flex-shrink-0 w-11 h-11 rounded-xl flex items-center justify-center transition-all',
              'bg-blue-600 hover:bg-blue-500 text-white',
              'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-blue-600',
              'focus:outline-none focus:ring-2 focus:ring-blue-500/50'
            )}
          >
            {sending
              ? <Loader2 className="w-5 h-5 animate-spin" />
              : <Send className="w-5 h-5" />
            }
          </button>
        </div>
        <p className="text-center text-xs text-gray-700 mt-2">
          PM может принять задачу, запросить статус или предложить следующие шаги
        </p>
      </div>

    </div>
  )
}
