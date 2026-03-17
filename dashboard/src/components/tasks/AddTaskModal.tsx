'use client'

import { useState } from 'react'
import { type Task, type Priority } from '@/lib/api'
import { X } from 'lucide-react'

interface AddTaskModalProps {
  onClose: () => void
  onAdd: (task: Task) => void
}

const labelStyle = {
  display: 'block',
  fontSize: '11px',
  fontWeight: 500,
  letterSpacing: '0.07em',
  textTransform: 'uppercase' as const,
  color: '#808080',
  marginBottom: '6px',
}

const fieldStyle = {
  width: '100%',
  background: '#3C3F41',
  border: '1px solid #515151',
  borderRadius: '3px',
  padding: '7px 10px',
  fontSize: '13px',
  color: '#BABABA',
  outline: 'none',
  transition: 'border-color 0.15s',
}

export function AddTaskModal({ onClose, onAdd }: AddTaskModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [repo, setRepo] = useState('backend')
  const [priority, setPriority] = useState<Priority>('normal')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return

    const newTask: Task = {
      id: crypto.randomUUID(),
      title: title.trim(),
      description: description.trim(),
      source: 'manual',
      priority,
      status: 'queued',
      assigned_to: null,
      repo,
      issue_number: null,
      pr_number: null,
      created_by: 'user',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    onAdd(newTask)
    onClose()
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-50" style={{ background: 'rgba(0,0,0,0.72)' }} onClick={onClose} />

      {/* Dialog */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          style={{
            background: '#2B2B2B',
            border: '1px solid #515151',
            borderRadius: '4px',
            width: '100%',
            maxWidth: '440px',
            boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
          }}
        >
          {/* Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '12px 16px',
              borderBottom: '1px solid #515151',
            }}
          >
            <span style={{ fontSize: '13px', fontWeight: 600, color: '#BABABA', letterSpacing: '0.03em' }}>
              New Task
            </span>
            <button
              onClick={onClose}
              style={{ color: '#808080', background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px' }}
              onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = '#BABABA'}
              onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = '#808080'}
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div>
              <label style={labelStyle}>Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Task title..."
                required
                style={fieldStyle}
                onFocus={e => (e.currentTarget as HTMLInputElement).style.borderColor = '#3592C4'}
                onBlur={e => (e.currentTarget as HTMLInputElement).style.borderColor = '#515151'}
              />
            </div>

            <div>
              <label style={labelStyle}>Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe the task..."
                rows={3}
                style={{ ...fieldStyle, resize: 'none' }}
                onFocus={e => (e.currentTarget as HTMLTextAreaElement).style.borderColor = '#3592C4'}
                onBlur={e => (e.currentTarget as HTMLTextAreaElement).style.borderColor = '#515151'}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              <div>
                <label style={labelStyle}>Repository</label>
                <select
                  value={repo}
                  onChange={(e) => setRepo(e.target.value)}
                  style={{ ...fieldStyle, cursor: 'pointer' }}
                  onFocus={e => (e.currentTarget as HTMLSelectElement).style.borderColor = '#3592C4'}
                  onBlur={e => (e.currentTarget as HTMLSelectElement).style.borderColor = '#515151'}
                >
                  <option value="backend" style={{ background: '#3C3F41' }}>backend</option>
                  <option value="frontend" style={{ background: '#3C3F41' }}>frontend</option>
                  <option value="infra" style={{ background: '#3C3F41' }}>infra</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Priority</label>
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as Priority)}
                  style={{ ...fieldStyle, cursor: 'pointer' }}
                  onFocus={e => (e.currentTarget as HTMLSelectElement).style.borderColor = '#3592C4'}
                  onBlur={e => (e.currentTarget as HTMLSelectElement).style.borderColor = '#515151'}
                >
                  <option value="low" style={{ background: '#3C3F41' }}>Low</option>
                  <option value="normal" style={{ background: '#3C3F41' }}>Normal</option>
                  <option value="high" style={{ background: '#3C3F41' }}>High</option>
                  <option value="critical" style={{ background: '#3C3F41' }}>Critical</option>
                </select>
              </div>
            </div>

            {/* Buttons */}
            <div style={{ display: 'flex', gap: '10px', paddingTop: '4px' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  flex: 1,
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 500,
                  color: '#808080',
                  background: '#3C3F41',
                  border: '1px solid #515151',
                  borderRadius: '3px',
                  cursor: 'pointer',
                  transition: 'color 0.15s, border-color 0.15s',
                }}
                onMouseEnter={e => {
                  const el = e.currentTarget as HTMLButtonElement
                  el.style.color = '#BABABA'
                  el.style.borderColor = '#6A6A6A'
                }}
                onMouseLeave={e => {
                  const el = e.currentTarget as HTMLButtonElement
                  el.style.color = '#808080'
                  el.style.borderColor = '#515151'
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!title.trim()}
                style={{
                  flex: 1,
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#FFFFFF',
                  background: title.trim() ? '#3592C4' : '#2a5f7a',
                  border: '1px solid transparent',
                  borderRadius: '3px',
                  cursor: title.trim() ? 'pointer' : 'not-allowed',
                  opacity: title.trim() ? 1 : 0.5,
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => {
                  if (title.trim()) (e.currentTarget as HTMLButtonElement).style.background = '#2a7aaa'
                }}
                onMouseLeave={e => {
                  if (title.trim()) (e.currentTarget as HTMLButtonElement).style.background = '#3592C4'
                }}
              >
                Add Task
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}
