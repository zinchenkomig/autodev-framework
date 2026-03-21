'use client'

import { useState, useRef, useEffect, ReactNode } from 'react'
import { Send, Plus, Trash2, MessageSquare, Check, ExternalLink } from 'lucide-react'

interface Message { id: string; role: 'user' | 'pm'; content: string; created_at: string }
interface TaskProposal { title: string; repo: string; priority: string; description: string }
interface Session { id: string; title: string | null; created_at: string; updated_at: string; message_count: number }
interface CreatedTask { id: string; title: string; repo: string; url: string }

const API_URL = process.env.NEXT_PUBLIC_API_URL || ''

const formatTime = (d: string) => new Date(d).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const formatDate = (d: string) => {
  const date = new Date(d), today = new Date(), yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  if (date.toDateString() === today.toDateString()) return 'Сегодня'
  if (date.toDateString() === yesterday.toDateString()) return 'Вчера'
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}
const formatSessionDate = (d: string) => new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function parseMarkdown(text: string): ReactNode[] {
  const elements: ReactNode[] = []
  let key = 0
  for (const line of text.split('\n')) {
    if (line.startsWith('## ')) { elements.push(<h3 key={key++} className="text-white font-semibold mt-2 mb-0.5">{line.slice(3)}</h3>); continue }
    if (line.startsWith('### ')) { elements.push(<h4 key={key++} className="text-gray-300 font-semibold mt-1">{line.slice(4)}</h4>); continue }
    if (line === '---') { elements.push(<hr key={key++} className="border-t border-gray-600 my-1" />); continue }
    if (!line.trim()) { elements.push(<div key={key++} className="h-1" />); continue }
    elements.push(<p key={key++} className="my-0.5">{parseInline(line)}</p>)
  }
  return elements
}

function parseInline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  let remaining = text, key = 0
  while (remaining.length > 0) {
    const bold = remaining.match(/\*\*([^*]+)\*\*/), code = remaining.match(/`([^`]+)`/), link = remaining.match(/\[([^\]]+)\]\(([^)]+)\)/)
    const matches = [bold && { t: 'b', m: bold, i: bold.index! }, code && { t: 'c', m: code, i: code.index! }, link && { t: 'l', m: link, i: link.index! }].filter(Boolean).sort((a, b) => a!.i - b!.i)
    if (!matches.length) { parts.push(remaining); break }
    const f = matches[0]!
    if (f.i > 0) parts.push(remaining.slice(0, f.i))
    if (f.t === 'b') parts.push(<strong key={key++} className="text-white">{f.m[1]}</strong>)
    else if (f.t === 'c') parts.push(<code key={key++} className="bg-gray-900 px-1 rounded text-green-400 text-xs">{f.m[1]}</code>)
    else parts.push(<a key={key++} href={f.m[2]} target="_blank" rel="noopener noreferrer" className="text-green-400 underline">{f.m[1]}</a>)
    remaining = remaining.slice(f.i + f.m[0].length)
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

  useEffect(() => { fetch(`${API_URL}/api/pm/sessions`).then(r => r.ok ? r.json() : []).then(setSessions) }, [])
  useEffect(() => {
    if (currentSessionId) fetch(`${API_URL}/api/pm/sessions/${currentSessionId}`).then(r => r.ok ? r.json() : { messages: [] }).then(d => { setMessages(d.messages); setProposals([]) })
    else { setMessages([]); setProposals([]) }
  }, [currentSessionId])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function handleSend() {
    if (!input.trim() || isLoading) return
    const msg: Message = { id: Date.now().toString(), role: 'user', content: input.trim(), created_at: new Date().toISOString() }
    setMessages(p => [...p, msg]); setInput(''); setIsLoading(true); setProposals([])
    try {
      const r = await fetch(`${API_URL}/api/pm/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: input.trim(), session_id: currentSessionId }) })
      const d = await r.json()
      if (d.session_id !== currentSessionId) { setCurrentSessionId(d.session_id); fetch(`${API_URL}/api/pm/sessions`).then(r => r.json()).then(setSessions) }
      setMessages(p => [...p, { id: (Date.now() + 1).toString(), role: 'pm', content: d.response, created_at: new Date().toISOString() }])
      if (d.proposals?.length) setProposals(d.proposals)
    } catch (e) { console.error(e) }
    setIsLoading(false)
  }

  async function handleApprove() {
    if (!proposals.length || isApproving) return
    setIsApproving(true)
    try {
      const r = await fetch(`${API_URL}/api/pm/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: currentSessionId, proposals }) })
      const d = await r.json()
      setMessages(p => [...p, { id: Date.now().toString(), role: 'pm', content: `✅ Создано: ${d.created_tasks.length}\n\n${d.created_tasks.map((t: CreatedTask) => `• [${t.title}](${t.url})`).join('\n')}`, created_at: new Date().toISOString() }])
      setProposals([])
    } catch (e) { console.error(e) }
    setIsApproving(false)
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Удалить?')) return
    await fetch(`${API_URL}/api/pm/sessions/${id}`, { method: 'DELETE' })
    setSessions(p => p.filter(s => s.id !== id))
    if (currentSessionId === id) { setCurrentSessionId(null); setMessages([]); setProposals([]) }
  }

  const getDate = (m: Message) => new Date(m.created_at).toDateString()

  return (
    <div className="flex h-screen" style={{ background: '#2B2B2B' }}>
      {/* Sidebar */}
      <div className="w-48 flex flex-col" style={{ borderRight: '1px solid #515151', background: '#313335' }}>
        <button onClick={() => { setCurrentSessionId(null); setMessages([]); setProposals([]) }}
          className="m-1 flex items-center justify-center gap-1 py-1 text-xs rounded" style={{ background: '#214283', color: '#FFF' }}>
          <Plus className="w-3 h-3" /> Новый
        </button>
        <div className="flex-1 overflow-y-auto">
          {sessions.map(s => (
            <div key={s.id} className="group flex items-center gap-1 px-1 py-1 cursor-pointer text-xs"
              style={{ background: currentSessionId === s.id ? '#214283' : 'transparent' }}
              onClick={() => setCurrentSessionId(s.id)}>
              <MessageSquare className="w-3 h-3" style={{ color: '#808080' }} />
              <div className="flex-1 min-w-0">
                <p className="truncate" style={{ color: '#BABABA' }}>{s.title || '...'}</p>
                <p style={{ color: '#606060', fontSize: '9px' }}>{formatSessionDate(s.updated_at)}</p>
              </div>
              <button onClick={e => { e.stopPropagation(); handleDelete(s.id) }} className="opacity-0 group-hover:opacity-100" style={{ color: '#808080' }}>
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat */}
      <div className="flex-1 flex flex-col">
        {/* Messages - no padding */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 && <div className="text-center py-4 text-xs" style={{ color: '#808080' }}>Опиши фичу</div>}
          {messages.map((m, i) => (
            <div key={m.id}>
              {(i === 0 || getDate(m) !== getDate(messages[i - 1])) && (
                <div className="flex justify-center py-1"><span className="px-2 text-xs rounded" style={{ background: '#3C3F41', color: '#808080' }}>{formatDate(m.created_at)}</span></div>
              )}
              <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className="max-w-[85%] px-2 py-1 m-0.5 rounded text-sm" style={{ background: m.role === 'user' ? '#214283' : '#3C3F41', color: '#BABABA' }}>
                  <div>{m.role === 'user' ? m.content : parseMarkdown(m.content)}</div>
                  <p className="text-right" style={{ color: '#606060', fontSize: '9px' }}>{formatTime(m.created_at)}</p>
                </div>
              </div>
            </div>
          ))}
          {isLoading && <div className="m-0.5 px-2 py-1 rounded text-sm animate-pulse" style={{ background: '#3C3F41', color: '#808080', width: 'fit-content' }}>...</div>}
          <div ref={messagesEndRef} />
        </div>

        {/* Proposals */}
        {proposals.length > 0 && (
          <div className="p-1" style={{ borderTop: '1px solid #515151', background: '#313335' }}>
            {proposals.map((p, i) => (
              <div key={i} className="p-1 mb-1 rounded text-xs" style={{ background: '#3C3F41', border: '1px solid #515151' }}>
                <span className="font-medium text-white">{p.title}</span>
                <span className="ml-1 px-1 rounded text-xs" style={{ background: '#214283', color: '#AAA', fontSize: '9px' }}>{p.priority}</span>
                <span className="ml-1" style={{ color: '#6A8759', fontSize: '9px' }}>{p.repo}</span>
                <p className="mt-0.5" style={{ color: '#808080' }}>{p.description.slice(0, 100)}...</p>
              </div>
            ))}
            <button onClick={handleApprove} disabled={isApproving} className="w-full flex items-center justify-center gap-1 py-1 rounded text-xs disabled:opacity-50" style={{ background: '#6A8759', color: '#FFF' }}>
              <Check className="w-3 h-3" /> Создать {proposals.length}
            </button>
          </div>
        )}

        {/* Input */}
        <div className="flex gap-1 p-1" style={{ borderTop: '1px solid #515151' }}>
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="Фича..." className="flex-1 px-2 py-1 text-sm rounded" style={{ background: '#3C3F41', border: '1px solid #515151', color: '#BABABA', outline: 'none' }} />
          <button onClick={handleSend} disabled={!input.trim() || isLoading} className="px-2 py-1 rounded disabled:opacity-50" style={{ background: '#6A8759', color: '#FFF' }}>
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
