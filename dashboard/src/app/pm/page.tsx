'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Plus, Trash2, MessageSquare } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'pm'
  content: string
  created_at: string
}

interface Session {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || ''

export default function PMChatPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Load sessions on mount
  useEffect(() => {
    loadSessions()
  }, [])

  // Load messages when session changes
  useEffect(() => {
    if (currentSessionId) {
      loadSession(currentSessionId)
    } else {
      setMessages([])
    }
  }, [currentSessionId])

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function loadSessions() {
    try {
      const res = await fetch(`${API_URL}/api/pm/sessions`)
      if (res.ok) {
        const data = await res.json()
        setSessions(data)
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
        setMessages(data.messages.map((m: any) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          created_at: m.created_at,
        })))
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

      // Update session ID if new
      if (data.session_id && data.session_id !== currentSessionId) {
        setCurrentSessionId(data.session_id)
        loadSessions() // Refresh sidebar
      }

      const pmMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'pm',
        content: data.response,
        created_at: new Date().toISOString(),
      }

      setMessages(prev => [...prev, pmMessage])
    } catch (err) {
      console.error('Failed to send message', err)
    } finally {
      setIsLoading(false)
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
      }
    } catch (err) {
      console.error('Failed to delete session', err)
    }
  }

  function handleNewChat() {
    setCurrentSessionId(null)
    setMessages([])
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-[calc(100vh-120px)]" style={{ background: '#2B2B2B' }}>
      {/* Sessions Sidebar */}
      <div
        className="w-64 flex flex-col"
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
              className={`group flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors ${
                currentSessionId === session.id ? 'bg-opacity-100' : ''
              }`}
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
                <p className="text-xs" style={{ color: '#515151' }}>
                  {session.message_count} сообщ.
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
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div
          className="flex items-center gap-3 px-6 py-4"
          style={{ borderBottom: '1px solid #515151' }}
        >
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-lg"
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
              <p>Опиши задачу — я создам её в нужном репозитории</p>
            </div>
          )}
          {messages.map(msg => (
            <div
              key={msg.id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className="max-w-[70%] px-4 py-3 rounded-lg"
                style={{
                  background: msg.role === 'user' ? '#214283' : '#3C3F41',
                  color: '#BABABA',
                }}
              >
                <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
              </div>
            </div>
          ))}
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

        {/* Input */}
        <div className="px-6 py-4" style={{ borderTop: '1px solid #515151' }}>
          <div className="flex gap-3">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Опиши задачу..."
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
