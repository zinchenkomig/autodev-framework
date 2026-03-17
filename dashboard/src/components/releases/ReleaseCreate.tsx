'use client'

import { useState } from 'react'
import { createRelease, type Task } from '@/lib/api'
import { CheckSquare, Square, Package, Loader2 } from 'lucide-react'

interface Props {
  doneTasks: Task[]
  onCreated: () => void
}

function generateVersion(): string {
  const now = new Date()
  const date = now.toISOString().slice(0, 10) // YYYY-MM-DD
  return `v${date}-1`
}

function priorityColor(p: string): string {
  switch (p) {
    case 'critical': return '#FF6B6B'
    case 'high': return '#CC7832'
    case 'normal': return '#6A8759'
    case 'low': return '#808080'
    default: return '#808080'
  }
}

export default function ReleaseCreate({ doneTasks, onCreated }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [version, setVersion] = useState(generateVersion)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const allSelected = doneTasks.length > 0 && selected.size === doneTasks.length

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(doneTasks.map((t) => t.id)))
    }
  }

  function toggleTask(id: string) {
    const next = new Set(selected)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setSelected(next)
  }

  async function handleCreate() {
    if (selected.size === 0) {
      setError('Select at least one task')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await createRelease({ version, tasks: Array.from(selected) })
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create release')
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Releases</h1>
        <p className="text-xs mt-0.5" style={{ color: '#808080' }}>No active release — create one from completed tasks</p>
      </div>

      {/* Version input */}
      <div
        className="p-4 space-y-3"
        style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
      >
        <label className="text-xs uppercase tracking-wider" style={{ color: '#808080' }}>Version</label>
        <input
          type="text"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          className="w-full px-3 py-2 text-sm font-mono outline-none"
          style={{
            background: '#2B2B2B',
            border: '1px solid #515151',
            borderRadius: '3px',
            color: '#FFC66D',
          }}
        />
      </div>

      {/* Task selection */}
      <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
        {/* Header row */}
        <div
          className="flex items-center gap-3 px-4 py-2.5 cursor-pointer"
          style={{ background: '#2B2B2B', borderBottom: '1px solid #515151' }}
          onClick={toggleAll}
        >
          {allSelected ? (
            <CheckSquare className="w-4 h-4 shrink-0" style={{ color: '#3592C4' }} />
          ) : (
            <Square className="w-4 h-4 shrink-0" style={{ color: '#808080' }} />
          )}
          <span className="text-xs font-medium" style={{ color: '#A9B7C6' }}>
            Select all ({doneTasks.length} done tasks)
          </span>
          {selected.size > 0 && (
            <span
              className="ml-auto text-xs px-2 py-0.5 rounded font-mono"
              style={{ background: 'rgba(53,146,196,0.15)', color: '#3592C4' }}
            >
              {selected.size} selected
            </span>
          )}
        </div>

        {doneTasks.length === 0 ? (
          <div className="py-10 text-center" style={{ background: '#3C3F41' }}>
            <Package className="w-6 h-6 mx-auto mb-2" style={{ color: '#515151' }} />
            <p className="text-xs" style={{ color: '#808080' }}>No completed tasks to include</p>
          </div>
        ) : (
          doneTasks.map((task, idx) => (
            <div
              key={task.id}
              className="flex items-center gap-3 px-4 py-3 cursor-pointer"
              style={{
                background: selected.has(task.id) ? 'rgba(53,146,196,0.06)' : '#3C3F41',
                borderBottom: idx < doneTasks.length - 1 ? '1px solid #515151' : 'none',
              }}
              onClick={() => toggleTask(task.id)}
              onMouseEnter={(e) => {
                if (!selected.has(task.id))
                  (e.currentTarget as HTMLDivElement).style.background = '#414345'
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLDivElement).style.background = selected.has(task.id)
                  ? 'rgba(53,146,196,0.06)'
                  : '#3C3F41'
              }}
            >
              {selected.has(task.id) ? (
                <CheckSquare className="w-4 h-4 shrink-0" style={{ color: '#3592C4' }} />
              ) : (
                <Square className="w-4 h-4 shrink-0" style={{ color: '#515151' }} />
              )}
              <span className="text-sm flex-1 truncate" style={{ color: '#A9B7C6' }}>
                {task.title}
              </span>
              {task.repo && (
                <span
                  className="text-xs px-1.5 py-0.5 font-mono shrink-0"
                  style={{
                    background: 'rgba(81,81,81,0.4)',
                    border: '1px solid #515151',
                    borderRadius: '3px',
                    color: '#808080',
                  }}
                >
                  {task.repo}
                </span>
              )}
              <span
                className="text-xs px-1.5 py-0.5 font-mono shrink-0"
                style={{
                  background: `${priorityColor(task.priority)}22`,
                  border: `1px solid ${priorityColor(task.priority)}44`,
                  borderRadius: '3px',
                  color: priorityColor(task.priority),
                }}
              >
                {task.priority}
              </span>
            </div>
          ))
        )}
      </div>

      {error && (
        <p className="text-xs" style={{ color: '#FF6B6B' }}>{error}</p>
      )}

      {/* Create button */}
      <div className="flex justify-end">
        <button
          onClick={handleCreate}
          disabled={loading || selected.size === 0}
          className="flex items-center gap-2 px-5 py-2 text-sm font-medium transition-opacity"
          style={{
            background: selected.size > 0 && !loading ? '#3592C4' : '#515151',
            color: '#FFFFFF',
            borderRadius: '4px',
            opacity: loading ? 0.7 : 1,
            cursor: loading || selected.size === 0 ? 'not-allowed' : 'pointer',
          }}
        >
          {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Создать релиз
          {selected.size > 0 && !loading && (
            <span className="text-xs opacity-75">({selected.size} tasks)</span>
          )}
        </button>
      </div>
    </div>
  )
}
