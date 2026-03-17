'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Loader2, RefreshCw, Download, X } from 'lucide-react'
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

interface GitHubImportResult {
  imported: number
  skipped: number
  errors: string[]
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

async function importFromGitHub(payload: {
  repo: string
  token: string
  labels: string[]
  state: string
}): Promise<GitHubImportResult> {
  const res = await fetch(`${BASE_URL}/pm/import-from-github`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
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

// ─── GitHub Import Modal ──────────────────────────────────────────────────────

const LABEL_OPTIONS = ['bug', 'enhancement', 'feature', 'documentation', 'help wanted', 'question', 'critical']

function GitHubImportModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: (result: GitHubImportResult) => void
}) {
  const [repo, setRepo] = useState('')
  const [token, setToken] = useState('')
  const [selectedLabels, setSelectedLabels] = useState<string[]>([])
  const [state, setState] = useState('open')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleLabel = (label: string) => {
    setSelectedLabels(prev =>
      prev.includes(label) ? prev.filter(l => l !== label) : [...prev, label]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!repo.trim() || !token.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await importFromGitHub({ repo: repo.trim(), token: token.trim(), labels: selectedLabels, state })
      onSuccess(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.6)' }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div
        className="w-full max-w-md mx-4 p-6 relative"
        style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '8px' }}
      >
        {/* Title */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold" style={{ color: '#FFFFFF' }}>
            🐙 Импорт из GitHub Issues
          </h2>
          <button onClick={onClose} style={{ color: '#808080' }}>
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Repository */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: '#BABABA' }}>
              Repository
            </label>
            <input
              type="text"
              placeholder="owner/repo"
              value={repo}
              onChange={e => setRepo(e.target.value)}
              required
              className="px-3 py-2 text-sm focus:outline-none"
              style={{
                background: '#2B2B2B',
                border: '1px solid #515151',
                borderRadius: '4px',
                color: '#FFFFFF',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = '#3592C4')}
              onBlur={e => (e.currentTarget.style.borderColor = '#515151')}
            />
          </div>

          {/* GitHub Token */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: '#BABABA' }}>
              GitHub Token
            </label>
            <input
              type="password"
              placeholder="ghp_..."
              value={token}
              onChange={e => setToken(e.target.value)}
              required
              className="px-3 py-2 text-sm focus:outline-none"
              style={{
                background: '#2B2B2B',
                border: '1px solid #515151',
                borderRadius: '4px',
                color: '#FFFFFF',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = '#3592C4')}
              onBlur={e => (e.currentTarget.style.borderColor = '#515151')}
            />
          </div>

          {/* State */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: '#BABABA' }}>
              Issue State
            </label>
            <select
              value={state}
              onChange={e => setState(e.target.value)}
              className="px-3 py-2 text-sm focus:outline-none"
              style={{
                background: '#2B2B2B',
                border: '1px solid #515151',
                borderRadius: '4px',
                color: '#FFFFFF',
              }}
            >
              <option value="open">Open</option>
              <option value="closed">Closed</option>
              <option value="all">All</option>
            </select>
          </div>

          {/* Labels */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: '#BABABA' }}>
              Labels (filter, optional)
            </label>
            <div className="flex flex-wrap gap-2">
              {LABEL_OPTIONS.map(label => (
                <button
                  key={label}
                  type="button"
                  onClick={() => toggleLabel(label)}
                  className="px-2.5 py-1 text-xs transition-colors"
                  style={{
                    borderRadius: '4px',
                    border: `1px solid ${selectedLabels.includes(label) ? '#3592C4' : '#515151'}`,
                    background: selectedLabels.includes(label) ? '#214283' : '#2B2B2B',
                    color: selectedLabels.includes(label) ? '#FFFFFF' : '#BABABA',
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div
              className="px-3 py-2 text-xs"
              style={{ background: '#4E2828', border: '1px solid #CC4E4E', borderRadius: '4px', color: '#FF8080' }}
            >
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading || !repo.trim() || !token.trim()}
            className="flex items-center justify-center gap-2 py-2.5 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: '#3592C4', borderRadius: '4px', color: '#FFFFFF' }}
            onMouseEnter={e => { if (!loading) (e.currentTarget).style.background = '#2a7aaa' }}
            onMouseLeave={e => (e.currentTarget).style.background = '#3592C4'}
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            {loading ? 'Импортирую...' : 'Импортировать'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function PMChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(true)
  const [showGitHubImport, setShowGitHubImport] = useState(false)
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

  const handleGitHubImportSuccess = (result: GitHubImportResult) => {
    setShowGitHubImport(false)
    const resultMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'pm',
      content:
        `✅ Импорт завершён!\n` +
        `  📥 Импортировано: ${result.imported} задач\n` +
        `  ⏭️ Пропущено (дубли): ${result.skipped}\n` +
        (result.errors.length > 0 ? `  ⚠️ Ошибок: ${result.errors.length}\n` : ''),
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, resultMsg])
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] -m-6 md:-m-8" style={{ background: '#2B2B2B' }}>

      {/* GitHub Import Modal */}
      {showGitHubImport && (
        <GitHubImportModal
          onClose={() => setShowGitHubImport(false)}
          onSuccess={handleGitHubImportSuccess}
        />
      )}

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
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowGitHubImport(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors"
            style={{
              border: '1px solid #515151',
              borderRadius: '4px',
              background: '#3C3F41',
              color: '#BABABA',
            }}
            onMouseEnter={e => {
              (e.currentTarget).style.borderColor = '#3592C4'
              ;(e.currentTarget).style.color = '#FFFFFF'
            }}
            onMouseLeave={e => {
              (e.currentTarget).style.borderColor = '#515151'
              ;(e.currentTarget).style.color = '#BABABA'
            }}
            title="Импорт задач из GitHub Issues"
          >
            <Download className="w-3.5 h-3.5" />
            Импорт из GitHub
          </button>
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
