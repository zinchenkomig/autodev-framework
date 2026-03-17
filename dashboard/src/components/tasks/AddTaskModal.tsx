'use client'

import { useState } from 'react'
import { type Task, type Priority, createTask } from '@/lib/api'
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
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || submitting) return

    setSubmitting(true)
    setError(null)

    try {
      const newTask = await createTask({
        title: title.trim(),
        description: description.trim(),
        repo,
        priority,
        status: 'queued',
      })
      onAdd(newTask)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create task')
    } finally {
      setSubmitting(false)
    }
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

            {/* Error message */}
            {error && (
              <div
                style={{
                  padding: '8px 12px',
                  background: 'rgba(204,78,78,0.15)',
                  border: '1px solid rgba(204,78,78,0.4)',
                  borderRadius: '3px',
                  fontSize: '12px',
                  color: '#CC4E4E',
                }}
              >
                {error}
              </div>
            )}

            {/* Buttons */}
            <div style={{ display: 'flex', gap: '10px', paddingTop: '4px' }}>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                style={{
                  flex: 1,
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 500,
                  color: '#808080',
                  background: '#3C3F41',
                  border: '1px solid #515151',
                  borderRadius: '3px',
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  transition: 'color 0.15s, border-color 0.15s',
                  opacity: submitting ? 0.5 : 1,
                }}
                onMouseEnter={e => {
                  if (!submitting) {
                    const el = e.currentTarget as HTMLButtonElement
                    el.style.color = '#BABABA'
                    el.style.borderColor = '#6A6A6A'
                  }
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
                disabled={!title.trim() || submitting}
                style={{
                  flex: 1,
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#FFFFFF',
                  background: title.trim() && !submitting ? '#3592C4' : '#2a5f7a',
                  border: '1px solid transparent',
                  borderRadius: '3px',
                  cursor: title.trim() && !submitting ? 'pointer' : 'not-allowed',
                  opacity: title.trim() && !submitting ? 1 : 0.5,
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => {
                  if (title.trim() && !submitting) (e.currentTarget as HTMLButtonElement).style.background = '#2a7aaa'
                }}
                onMouseLeave={e => {
                  if (title.trim() && !submitting) (e.currentTarget as HTMLButtonElement).style.background = '#3592C4'
                }}
              >
                {submitting ? 'Creating…' : 'Add Task'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}
