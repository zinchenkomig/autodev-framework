'use client'

import { useState } from 'react'
import { type Task, type TaskStatus, updateTask } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { X, GitPullRequest, GitBranch } from 'lucide-react'
import { PriorityBadge } from '@/components/Badge'

interface TaskDetailProps {
  task: Task | null
  onClose: () => void
  onStatusChange?: (taskId: string, newStatus: TaskStatus) => void
}

const STATUS_PILLS: { id: TaskStatus; label: string }[] = [
  { id: 'queued',      label: 'Queued'      },
  { id: 'in_progress', label: 'In Progress' },
  { id: 'review',      label: 'Review'      },
  { id: 'done',        label: 'Done'        },
  { id: 'ready_to_release', label: 'Ready to Release' },
]

const STATUS_DOT: Record<TaskStatus, string> = {
  queued:      '#808080',
  assigned:    '#9876AA',
  in_progress: '#CC7832',
  review:      '#3592C4',
  done:        '#6A8759',
  ready_to_release: '#9876AA',
  failed:      '#CC4E4E',
}

export function TaskDetail({ task, onClose, onStatusChange }: TaskDetailProps) {
  const [currentStatus, setCurrentStatus] = useState<TaskStatus | null>(null)
  const [saving, setSaving] = useState(false)

  // Reset local state whenever the task changes
  const effectiveStatus: TaskStatus = currentStatus ?? (task?.status ?? 'queued')

  if (!task) return null

  async function handleStatusClick(status: TaskStatus) {
    if (!task || status === effectiveStatus || saving) return
    setSaving(true)
    try {
      await updateTask(task.id, { status })
      setCurrentStatus(status)
      onStatusChange?.(task.id, status)
    } catch (err) {
      console.warn('[TaskDetail] status update failed', err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40" onClick={onClose} />

      <div
        className="fixed right-0 top-0 h-full w-full md:max-w-sm z-50 flex flex-col"
        style={{ background: '#2B2B2B', borderLeft: '1px solid #515151' }}
      >
        {/* Header */}
        <div
          className="flex items-start gap-3 px-5 py-4"
          style={{ borderBottom: '1px solid #515151' }}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <PriorityBadge priority={task.priority} />
            </div>
            <p className="text-sm leading-snug" style={{ color: '#FFFFFF' }}>{task.title}</p>
          </div>
          <button
            onClick={onClose}
            className="transition-colors shrink-0"
            style={{ color: '#515151' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#808080')}
            onMouseLeave={e => (e.currentTarget.style.color = '#515151')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* ── Status picker ── */}
          <div>
            <p className="text-xs uppercase tracking-wider mb-3" style={{ color: '#808080' }}>Status</p>
            <div className="flex flex-wrap gap-2">
              {STATUS_PILLS.map(({ id, label }) => {
                const isActive = effectiveStatus === id
                const dot = STATUS_DOT[id]
                return (
                  <button
                    key={id}
                    disabled={saving}
                    onClick={() => handleStatusClick(id)}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all disabled:opacity-60"
                    style={{
                      border: `1px solid ${isActive ? dot : '#515151'}`,
                      background: isActive ? `${dot}22` : 'transparent',
                      color: isActive ? dot : '#808080',
                      cursor: saving ? 'not-allowed' : isActive ? 'default' : 'pointer',
                    }}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: isActive ? dot : '#515151',
                        flexShrink: 0,
                      }}
                    />
                    {label}
                  </button>
                )
              })}
            </div>
          </div>

          {task.description && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Description</p>
              <p className="text-xs leading-relaxed" style={{ color: '#808080' }}>{task.description}</p>
            </div>
          )}

          <div>
            <p className="text-xs uppercase tracking-wider mb-3" style={{ color: '#808080' }}>Details</p>
            <div
              className="rounded p-3 space-y-2"
              style={{ background: '#3C3F41', border: '1px solid #515151' }}
            >
              {[
                ['Assigned', task.assigned_to ?? '—'],
                ['Repository', task.repo],
                ['Source', task.source],
                ['Created by', task.created_by],
                ['Created', formatDistanceToNow(task.created_at)],
                ['Updated', formatDistanceToNow(task.updated_at)],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: '#515151' }}>{label}</span>
                  <span className="text-xs font-mono" style={{ color: '#808080' }}>{value}</span>
                </div>
              ))}

              {/* Branch link */}
              {task.branch && (
                <div className="flex items-center justify-between pt-1" style={{ borderTop: '1px solid #515151' }}>
                  <span className="text-xs" style={{ color: '#515151' }}>Branch</span>
                  <a
                    href={`https://github.com/zinchenkomig/${task.repo}/tree/${task.branch}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-xs font-mono transition-opacity hover:opacity-80"
                    style={{ color: '#9876AA' }}
                  >
                    <GitBranch className="w-4 h-4" />
                    {task.branch}
                  </a>
                </div>
              )}

              {/* PR link */}
              {task.pr_url && (
                <div className="flex items-center justify-between pt-1" style={{ borderTop: '1px solid #515151' }}>
                  <span className="text-xs" style={{ color: '#515151' }}>Pull Request</span>
                  <a
                    href={task.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-xs transition-opacity hover:opacity-80"
                    style={{ color: '#6A8759' }}
                  >
                    <GitPullRequest className="w-4 h-4" />
                    View Pull Request
                  </a>
                </div>
              )}
            </div>
          </div>

          <div>
            <p className="text-xs uppercase tracking-wider mb-3" style={{ color: '#808080' }}>History</p>
            <div className="space-y-2.5">
              <div className="flex items-start gap-2">
                <span className="text-xs mt-0.5" style={{ color: '#515151' }}>●</span>
                <div>
                  <p className="text-xs" style={{ color: '#808080' }}>
                    Status → <span style={{ color: '#BABABA' }}>{effectiveStatus}</span>
                    <span className="ml-1" style={{ color: '#515151' }}>by {task.assigned_to ?? 'system'}</span>
                  </p>
                  <p className="text-xs" style={{ color: '#515151' }}>{formatDistanceToNow(task.updated_at)}</p>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-xs mt-0.5" style={{ color: '#515151' }}>●</span>
                <div>
                  <p className="text-xs" style={{ color: '#808080' }}>
                    Created by <span style={{ color: '#BABABA' }}>{task.created_by}</span>
                  </p>
                  <p className="text-xs" style={{ color: '#515151' }}>{formatDistanceToNow(task.created_at)}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
