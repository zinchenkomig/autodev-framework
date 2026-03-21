'use client'

import { useState, useRef, useEffect, ReactNode } from 'react'
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
  
  if (date.toDateString() === today.toDateString()) return 'Сегодня'
  if (date.toDateString() === yesterday.toDateString()) return 'Вчера'
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function formatSessionDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// Parse markdown to React elements
function parseMarkdown(text: string): ReactNode[] {
  const elements: ReactNode[] = []
  const lines = text.split('\n')
  let key = 0
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    
    // Headers
    if (line.startsWith('## ')) {
      elements.push(<h3 key={key++} style={{ color: '#FFFFFF', fontWeight: 600, marginTop: '12px', marginBottom: '4px' }}>{line.slice(3)}</h3>)
      continue
    }
    if (line.startsWith('### ')) {
      elements.push(<h4 key={key++} style={{ color: '#BABABA', fontWeight: 600, marginTop: '8px', marginBottom: '2px' }}>{line.slice(4)}</h4>)
      continue
    }
    
    // Horizontal rule
    if (line === '---') {
      elements.push(<hr key={key++} style={{ border: 'none', borderTop: '1px solid #515151', margin: '8px 0' }} />)
      continue
    }
    
    // Empty line
    if (!line.trim()) {
      elements.push(<div key={key++} style={{ height: '8px' }} />)
      continue
    }
    
    // Parse inline formatting
    elements.push(<p key={key++} style={{ margin: '2px 0' }}>{parseInline(line)}</p>)
  }
  
  return elements
}

function parseInline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  let remaining = text
  let key = 0
  
  while (remaining.length > 0) {
    // Bold **text**
    const boldMatch = remaining.match(/\*\*([^*]+)\*\*/)
    // Code `text`
    const codeMatch = remaining.match(/`([^`]+)`/)
    // Link [text](url)
    const linkMatch = remaining.match(/\[([^\]]+)\]\(([^)]+)\)/)
    
    // Find the earliest match
    const matches = [
      boldMatch ? { type: 'bold', match: boldMatch, index: boldMatch.index! } : null,
      codeMatch ? { type: 'code', match: codeMatch, index: codeMatch.index! } : null,
      linkMatch ? { type: 'link', match: linkMatch, index: linkMatch.index! } : null,
    ].filter(Boolean).sort((a, b) => a!.index - b!.index)
    
    if (matches.length === 0) {
      parts.push(remaining)
      break
    }
    
    const first = matches[0]!
    
    // Add text before match
    if (first.index > 0) {
      parts.push(remaining.slice(0, first.index))
    }
    
    // Add formatted element
    if (first.type === 'bold') {
      parts.push(<strong key={key++} style={{ color: '#FFFFFF' }}>{first.match[1]}</strong>)
      remaining = remaining.slice(first.index + first.match[0].length)
    } else if (first.type === 'code') {
      parts.push(<code key={key++} style={{ background: '#2B2B2B', padding: '1px 4px', borderRadius: '3px', color: '#6A8759' }}>{first.match[1]}</code>)
      remaining = remaining.slice(first.index + first.match[0].length)
    } else if (first.type === 'link') {
      parts.push(
        <a key={key++} href={first.match[2]} target="_blank" rel="noopener noreferrer" 
           style={{ color: '#6A8759', textDecoration: 'underline' }}>
          {first.match[1]} <ExternalLink className="inline w-3 h-3" />
        </a>
      )
      remaining = remaining.slice(first.index + first.match[0].length)
    }
  }
  
  return parts
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

  useEffect(() => { loadSessions() }, [])
  useEffect(() => {
    if (currentSessionId) loadSession(currentSessionId)
    else { setMessages([]); setProposals([]) }
  }, [currentSessionId])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function loadSessions() {
    try {
      const res = await fetch(`${API_URL}/api/pm/sessions`)
      if (res.ok) setSessions(await res.json())
    } catch (err) { console.error('Failed to load sessions', err) }
  }

  async function loadSession(sessionId: string) {
    try {
      const res = await fetch(`${API_URL}/api/pm/sessions/${sessionId}`)
      if (res.ok) {
        const data = await res.json()
        setMessages(data.messages)
        setProposals([])
      }
    } catch (err) { console.error('Failed to load session', err) }
  }

  async function handleSend() {
    if (!input.trim() || isLoading) return
    const userMessage: Message = { id: Date.now().toString(), role: 'user', content: input.trim(), created_at: new Date().toISOString() }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setProposals([])

    try {
      const res = await fetch(`${API_URL}/api/pm/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: input.trim(), session_id: currentSessionId }),
      })
      const data = await res.json()
      if (data.session_id && data.session_id !== currentSessionId) {
        setCurrentSessionId(data.session_id)
        loadSessions()
      }
      const pmMessage: Message = { id: (Date.now() + 1).toString(), role: 'pm', content: data.response, created_at: new Date().toISOString() }
      setMessages(prev => [...prev, pmMessage])
      if (data.proposals?.length > 0) setProposals(data.proposals)
    } catch (err) { console.error('Failed to send message', err) }
    finally { setIsLoading(false) }
  }

  async function handleApprove() {
    if (!proposals.length || isApproving) return
    setIsApproving(true)
    try {
      const res = await fetch(`${API_URL}/api/pm/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentSessionId, proposals }),
      })
      const data = await res.json()
      const taskLinks = data.created_tasks.map((t: CreatedTask) => `• [${t.title}](${t.url})`).join('\n')
      const confirmMessage: Message = { id: Date.now().toString(), role: 'pm', content: `✅ Создано: ${data.created_tasks.length}\n\n${taskLinks}`, created_at: new Date().toISOString() }
      setMessages(prev => [...prev, confirmMessage])
      setProposals([])
      loadSessions()
    } catch (err) { console.error('Failed to approve', err) }
    finally { setIsApproving(false) }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!confirm('Удалить?')) return
    try {
      await fetch(`${API_URL}/api/pm/sessions/${sessionId}`, { method: 'DELETE' })
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (currentSessionId === sessionId) { setCurrentSessionId(null); setMessages([]); setProposals([]) }
    } catch (err) { console.error('Failed to delete', err) }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const getMessageDate = (msg: Message) => new Date(msg.created_at).toDateString()

  return (
    <div className="flex h-[calc(100vh-80px)]" style={{ background: '#2B2B2B' }}>
      {/* Sidebar */}
      <div className="w-56 flex flex-col shrink-0" style={{ borderRight: '1px solid #515151', background: '#313335' }}>
        <div className="p-2" style={{ borderBottom: '1px solid #515151' }}>
          <button onClick={() => { setCurrentSessionId(null); setMessages([]); setProposals([]) }}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs rounded"
            style={{ background: '#214283', color: '#FFF' }}>
            <Plus className="w-3.5 h-3.5" /> Новый диалог
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessions.map(session => (
            <div key={session.id} className="group flex items-center gap-1.5 px-2 py-1.5 cursor-pointer"
              style={{ background: currentSessionId === session.id ? '#214283' : 'transparent', borderLeft: currentSessionId === session.id ? '2px solid #3592C4' : '2px solid transparent' }}
              onClick={() => setCurrentSessionId(session.id)}>
              <MessageSquare className="w-3.5 h-3.5 shrink-0" style={{ color: '#808080' }} />
              <div className="flex-1 min-w-0">
                <p className="text-xs truncate" style={{ color: '#BABABA' }}>{session.title || 'Без названия'}</p>
                <p className="text-xs" style={{ color: '#606060', fontSize: '10px' }}>{formatSessionDate(session.updated_at)}</p>
              </div>
              <button onClick={(e) => { e.stopPropagation(); handleDeleteSession(session.id) }}
                className="opacity-0 group-hover:opacity-100 p-0.5" style={{ color: '#808080' }}>
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-2 shrink-0" style={{ borderBottom: '1px solid #515151' }}>
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm shrink-0" style={{ background: '#6A8759', color: '#FFF' }}>PM</div>
          <div>
            <h1 className="text-sm font-semibold" style={{ color: '#FFF' }}>PM Agent</h1>
            <p className="text-xs" style={{ color: '#808080' }}>{currentSessionId ? 'Диалог' : 'Новый'}</p>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
          {messages.length === 0 && <div className="text-center py-4 text-xs" style={{ color: '#808080' }}>Опиши фичу — я продумаю реализацию</div>}
          {messages.map((msg, idx) => {
            const showDate = idx === 0 || getMessageDate(msg) !== getMessageDate(messages[idx - 1])
            return (
              <div key={msg.id}>
                {showDate && (
                  <div className="flex justify-center my-2">
                    <span className="px-2 py-0.5 text-xs rounded-full" style={{ background: '#3C3F41', color: '#808080' }}>{formatDate(msg.created_at)}</span>
                  </div>
                )}
                <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className="max-w-[80%] px-3 py-2 rounded-lg text-sm" style={{ background: msg.role === 'user' ? '#214283' : '#3C3F41', color: '#BABABA' }}>
                    <div>{msg.role === 'user' ? msg.content : parseMarkdown(msg.content)}</div>
                    <p className="text-right mt-1" style={{ color: '#606060', fontSize: '9px' }}>{formatTime(msg.created_at)}</p>
                  </div>
                </div>
              </div>
            )
          })}
          {isLoading && <div className="flex justify-start"><div className="px-3 py-2 rounded-lg text-sm animate-pulse" style={{ background: '#3C3F41', color: '#808080' }}>Думаю...</div></div>}
          <div ref={messagesEndRef} />
        </div>

        {/* Proposals */}
        {proposals.length > 0 && (
          <div className="px-4 py-2" style={{ borderTop: '1px solid #515151', background: '#313335' }}>
            <p className="text-xs mb-2" style={{ color: '#808080' }}>Задачи:</p>
            {proposals.map((p, i) => (
              <div key={i} className="mb-1.5 p-2 rounded text-xs" style={{ background: '#3C3F41', border: '1px solid #515151' }}>
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="font-medium" style={{ color: '#FFF' }}>{p.title}</span>
                  <span className="px-1 py-0.5 rounded text-xs" style={{ background: '#214283', color: '#BABABA', fontSize: '10px' }}>{p.priority}</span>
                </div>
                <p style={{ color: '#6A8759', fontSize: '10px' }}>{p.repo}</p>
                <p className="mt-1" style={{ color: '#808080' }}>{p.description.slice(0, 120)}...</p>
              </div>
            ))}
            <button onClick={handleApprove} disabled={isApproving}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-sm disabled:opacity-50"
              style={{ background: '#6A8759', color: '#FFF' }}>
              <Check className="w-3.5 h-3.5" /> {isApproving ? 'Создаю...' : `Создать ${proposals.length}`}
            </button>
          </div>
        )}

        {/* Input */}
        <div className="px-4 py-2 shrink-0" style={{ borderTop: '1px solid #515151' }}>
          <div className="flex gap-2">
            <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
              placeholder="Опиши фичу..." rows={1}
              className="flex-1 px-3 py-2 text-sm resize-none"
              style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '6px', color: '#BABABA', outline: 'none' }} />
            <button onClick={handleSend} disabled={!input.trim() || isLoading}
              className="px-3 py-2 rounded-lg disabled:opacity-50" style={{ background: '#6A8759', color: '#FFF' }}>
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
