'use client'

import { useState } from 'react'
import { type Task, type TaskStatus, updateTask } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { X, GitPullRequest } from 'lucide-react'
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
]

const STATUS_DOT: Record<TaskStatus, string> = {
  queued:      '#808080',
  assigned:    '#9876AA',
  in_progress: '#CC7832',
  review:      '#3592C4',
  done:        '#6A8759',
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

      <div className="fixed right-0 top-0 h-full w-full md:max-w-sm bg-[#09090B] border-l border-[#1F1F23] z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[#1F1F23]">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <PriorityBadge priority={task.priority} />
            </div>
            <p className="text-sm text-[#FAFAFA] leading-snug">{task.title}</p>
          </div>
          <button
            onClick={onClose}
            className="text-[#3F3F46] hover:text-[#71717A] transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* ── Status picker ── */}
          <div>
            <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">Status</p>
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
                      border: `1px solid ${isActive ? dot : '#3F3F46'}`,
                      background: isActive ? `${dot}22` : 'transparent',
                      color: isActive ? dot : '#71717A',
                      cursor: saving ? 'not-allowed' : isActive ? 'default' : 'pointer',
                    }}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: isActive ? dot : '#3F3F46',
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
              <p className="text-xs text-[#71717A] uppercase tracking-wider mb-2">Description</p>
              <p className="text-xs text-[#71717A] leading-relaxed">{task.description}</p>
            </div>
          )}

          <div>
            <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">Details</p>
            <div className="space-y-2">
              {[
                ['Assigned', task.assigned_to ?? '—'],
                ['Repository', task.repo],
                ['Source', task.source],
                ['Created by', task.created_by],
                ['Created', formatDistanceToNow(task.created_at)],
                ['Updated', formatDistanceToNow(task.updated_at)],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-xs text-[#3F3F46]">{label}</span>
                  <span className="text-xs text-[#71717A] font-mono">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {(task.issue_number || task.pr_number) && (
            <div>
              <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">Links</p>
              <div className="space-y-1.5">
                {task.pr_number && (
                  <a
                    href={`https://github.com/autodev-framework/${task.repo}/pull/${task.pr_number}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-xs text-[#6366F1] hover:text-[#818CF8] transition-colors"
                  >
                    <GitPullRequest className="w-3.5 h-3.5" />
                    PR #{task.pr_number}
                  </a>
                )}
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">History</p>
            <div className="space-y-2.5">
              <div className="flex items-start gap-2">
                <span className="text-xs text-[#3F3F46] mt-0.5">●</span>
                <div>
                  <p className="text-xs text-[#71717A]">
                    Status → <span className="text-[#FAFAFA]">{effectiveStatus}</span>
                    <span className="text-[#3F3F46] ml-1">by {task.assigned_to ?? 'system'}</span>
                  </p>
                  <p className="text-xs text-[#3F3F46]">{formatDistanceToNow(task.updated_at)}</p>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-xs text-[#3F3F46] mt-0.5">●</span>
                <div>
                  <p className="text-xs text-[#71717A]">
                    Created by <span className="text-[#FAFAFA]">{task.created_by}</span>
                  </p>
                  <p className="text-xs text-[#3F3F46]">{formatDistanceToNow(task.created_at)}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
