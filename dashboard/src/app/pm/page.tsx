'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Plus, Trash2, MessageSquare, Check, ExternalLink } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'pm'
  content: string
  created_at: string
}

interface TaskProposal {
  title: string
  repo: string
  priority: string
  description: string
}

interface Session {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
}

interface CreatedTask {
  id: string
  title: string
  repo: string
  url: string
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || ''

function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  
  if (date.toDateString() === today.toDateString()) {
    return 'Сегодня'
  } else if (date.toDateString() === yesterday.toDateString()) {
    return 'Вчера'
  } else {
    return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  }
}

function formatSessionDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export default function PMChatPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [proposals, setProposals] = useState<TaskProposal[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isApproving, setIsApproving] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadSessions()
  }, [])

  useEffect(() => {
    if (currentSessionId) {
      loadSession(currentSessionId)
    } else {
      setMessages([])
      setProposals([])
    }
  }, [currentSessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function loadSessions() {
    try {
      const res = await fetch(`${API_URL}/api/pm/sessions`)
      if (res.ok) {
        setSessions(await res.json())
      }
    } catch (err) {
      console.error('Failed to load sessions', err)
    }
  }

  async function loadSession(sessionId: string) {
    try {
      const res = await fetch(`${API_URL}/api/pm/sessions/${sessionId}`)
      if (res.ok) {
        const data = await res.json()
        setMessages(data.messages)
        setProposals([])
      }
    } catch (err) {
      console.error('Failed to load session', err)
    }
  }

  async function handleSend() {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      created_at: new Date().toISOString(),
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setProposals([])

    try {
      const res = await fetch(`${API_URL}/api/pm/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input.trim(),
          session_id: currentSessionId,
        }),
      })

      const data = await res.json()

      if (data.session_id && data.session_id !== currentSessionId) {
        setCurrentSessionId(data.session_id)
        loadSessions()
      }

      const pmMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'pm',
        content: data.response,
        created_at: new Date().toISOString(),
      }

      setMessages(prev => [...prev, pmMessage])
      
      if (data.proposals && data.proposals.length > 0) {
        setProposals(data.proposals)
      }
    } catch (err) {
      console.error('Failed to send message', err)
    } finally {
      setIsLoading(false)
    }
  }

  async function handleApprove() {
    if (!proposals.length || isApproving) return
    
    setIsApproving(true)
    
    try {
      const res = await fetch(`${API_URL}/api/pm/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSessionId,
          proposals: proposals,
        }),
      })

      const data = await res.json()
      
      const taskLinks = data.created_tasks.map((t: CreatedTask) => 
        `• [${t.title}](${t.url})`
      ).join('\n')
      
      const confirmMessage: Message = {
        id: Date.now().toString(),
        role: 'pm',
        content: `✅ Создано задач: ${data.created_tasks.length}\n\n${taskLinks}`,
        created_at: new Date().toISOString(),
      }
      
      setMessages(prev => [...prev, confirmMessage])
      setProposals([])
      loadSessions()
    } catch (err) {
      console.error('Failed to approve', err)
    } finally {
      setIsApproving(false)
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!confirm('Удалить этот диалог?')) return
    
    try {
      await fetch(`${API_URL}/api/pm/sessions/${sessionId}`, { method: 'DELETE' })
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null)
        setMessages([])
        setProposals([])
      }
    } catch (err) {
      console.error('Failed to delete session', err)
    }
  }

  function handleNewChat() {
    setCurrentSessionId(null)
    setMessages([])
    setProposals([])
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function renderContent(content: string) {
    const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g
    const parts = []
    let lastIndex = 0
    let match

    while ((match = linkRegex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        parts.push(content.slice(lastIndex, match.index))
      }
      parts.push(
        <a
          key={match.index}
          href={match[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 underline"
          style={{ color: '#6A8759' }}
        >
          {match[1]}
          <ExternalLink className="w-3 h-3" />
        </a>
      )
      lastIndex = match.index + match[0].length
    }

    if (lastIndex < content.length) {
      parts.push(content.slice(lastIndex))
    }

    return parts.length > 0 ? parts : content
  }

  // Group messages by date
  function getMessageDate(msg: Message): string {
    return new Date(msg.created_at).toDateString()
  }

  return (
    <div className="flex h-[calc(100vh-120px)]" style={{ background: '#2B2B2B' }}>
      {/* Sessions Sidebar */}
      <div
        className="w-64 flex flex-col shrink-0"
        style={{ borderRight: '1px solid #515151', background: '#313335' }}
      >
        <div className="p-3" style={{ borderBottom: '1px solid #515151' }}>
          <button
            onClick={handleNewChat}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm rounded transition-colors"
            style={{ background: '#214283', color: '#FFFFFF' }}
          >
            <Plus className="w-4 h-4" />
            Новый диалог
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto">
          {sessions.map(session => (
            <div
              key={session.id}
              className="group flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors"
              style={{
                background: currentSessionId === session.id ? '#214283' : 'transparent',
                borderLeft: currentSessionId === session.id ? '2px solid #3592C4' : '2px solid transparent',
              }}
              onClick={() => setCurrentSessionId(session.id)}
            >
              <MessageSquare className="w-4 h-4 shrink-0" style={{ color: '#808080' }} />
              <div className="flex-1 min-w-0">
                <p className="text-xs truncate" style={{ color: '#BABABA' }}>
                  {session.title || 'Без названия'}
                </p>
                <p className="text-xs" style={{ color: '#606060' }}>
                  {formatSessionDate(session.updated_at)}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleDeleteSession(session.id)
                }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded transition-opacity"
                style={{ color: '#808080' }}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div
          className="flex items-center gap-3 px-6 py-4 shrink-0"
          style={{ borderBottom: '1px solid #515151' }}
        >
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-lg shrink-0"
            style={{ background: '#6A8759', color: '#FFFFFF' }}
          >
            PM
          </div>
          <div>
            <h1 className="text-lg font-semibold" style={{ color: '#FFFFFF' }}>
              PM Agent
            </h1>
            <p className="text-xs" style={{ color: '#808080' }}>
              {currentSessionId ? 'Продолжение диалога' : 'Новый диалог'}
            </p>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-8" style={{ color: '#808080' }}>
              <p>Опиши фичу — я продумаю реализацию и предложу задачи</p>
            </div>
          )}
          {messages.map((msg, idx) => {
            const showDateSeparator = idx === 0 || getMessageDate(msg) !== getMessageDate(messages[idx - 1])
            
            return (
              <div key={msg.id}>
                {showDateSeparator && (
                  <div className="flex items-center justify-center my-4">
                    <span 
                      className="px-3 py-1 text-xs rounded-full"
                      style={{ background: '#3C3F41', color: '#808080' }}
                    >
                      {formatDate(msg.created_at)}
                    </span>
                  </div>
                )}
                <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className="max-w-[70%] px-4 py-3 rounded-lg"
                    style={{
                      background: msg.role === 'user' ? '#214283' : '#3C3F41',
                      color: '#BABABA',
                    }}
                  >
                    <p className="text-sm whitespace-pre-wrap">{renderContent(msg.content)}</p>
                    <p 
                      className="text-right mt-1"
                      style={{ color: '#606060', fontSize: '10px' }}
                    >
                      {formatTime(msg.created_at)}
                    </p>
                  </div>
                </div>
              </div>
            )
          })}
          {isLoading && (
            <div className="flex justify-start">
              <div
                className="px-4 py-3 rounded-lg"
                style={{ background: '#3C3F41', color: '#808080' }}
              >
                <span className="animate-pulse">PM думает...</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Proposals */}
        {proposals.length > 0 && (
          <div className="px-6 py-4" style={{ borderTop: '1px solid #515151', background: '#313335' }}>
            <p className="text-xs mb-3" style={{ color: '#808080' }}>
              Предложенные задачи:
            </p>
            {proposals.map((p, i) => (
              <div
                key={i}
                className="mb-2 p-3 rounded"
                style={{ background: '#3C3F41', border: '1px solid #515151' }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium" style={{ color: '#FFFFFF' }}>
                    {p.title}
                  </span>
                  <span
                    className="text-xs px-1.5 py-0.5 rounded"
                    style={{ background: '#214283', color: '#BABABA' }}
                  >
                    {p.priority}
                  </span>
                </div>
                <p className="text-xs mb-1" style={{ color: '#6A8759' }}>{p.repo}</p>
                <p className="text-xs" style={{ color: '#808080' }}>{p.description.slice(0, 150)}...</p>
              </div>
            ))}
            <button
              onClick={handleApprove}
              disabled={isApproving}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded transition-colors disabled:opacity-50"
              style={{ background: '#6A8759', color: '#FFFFFF' }}
            >
              <Check className="w-4 h-4" />
              {isApproving ? 'Создаю...' : `Создать ${proposals.length} задач${proposals.length > 1 ? 'и' : 'у'}`}
            </button>
          </div>
        )}

        {/* Input */}
        <div className="px-6 py-4 shrink-0" style={{ borderTop: '1px solid #515151' }}>
          <div className="flex gap-3">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Опиши фичу..."
              rows={2}
              className="flex-1 px-4 py-3 text-sm resize-none"
              style={{
                background: '#3C3F41',
                border: '1px solid #515151',
                borderRadius: '8px',
                color: '#BABABA',
                outline: 'none',
              }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="px-4 py-3 rounded-lg transition-colors disabled:opacity-50"
              style={{ background: '#6A8759', color: '#FFFFFF' }}
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
