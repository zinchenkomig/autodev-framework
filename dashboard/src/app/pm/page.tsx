'use client'

import { useState, useRef, useEffect } from 'react'
import { Send } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'pm'
  content: string
  timestamp: Date
}

export default function PMChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'pm',
      content: 'Привет! Я PM агент. Опиши задачу, которую нужно реализовать, и я создам её в системе.\n\nМогу уточнить детали: приоритет, проект, acceptance criteria.',
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const res = await fetch('/api/pm/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: input.trim(), history: messages }),
      })

      const data = await res.json()

      const pmMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'pm',
        content: data.response,
        timestamp: new Date(),
      }

      setMessages(prev => [...prev, pmMessage])
    } catch (err) {
      console.error('Failed to send message', err)
    } finally {
      setIsLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-120px)]" style={{ background: '#2B2B2B' }}>
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
            Создание и управление задачами
          </p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
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
              <p className="text-xs mt-2" style={{ color: '#808080' }}>
                {msg.timestamp.toLocaleTimeString()}
              </p>
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
            style={{
              background: '#6A8759',
              color: '#FFFFFF',
            }}
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  )
}
