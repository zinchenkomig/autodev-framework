'use client'

import { useState } from 'react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { type Task } from '@/lib/api'
import { deleteTask, updateTask } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { ExternalLink, GitBranch, GripVertical, GitPullRequest, Trash2, Undo2 } from 'lucide-react'

interface TaskCardProps {
  task: Task
  onClick: (task: Task) => void
  onDelete?: (taskId: string) => void
  onRequeue?: (taskId: string) => void
}

const priorityConfig: Record<string, { color: string; bg: string; label: string; border: string }> = {
  critical: { color: '#FFFFFF', bg: '#CC4E4E', label: 'critical', border: '#CC4E4E' },
  high:     { color: '#FFFFFF', bg: '#CC7832', label: 'high',     border: '#CC7832' },
  normal:   { color: '#FFFFFF', bg: '#3592C4', label: 'normal',   border: '#3592C4' },
  low:      { color: '#BABABA', bg: '#414345', label: 'low',      border: '#515151' },
}

const REQUEUE_STATUSES = new Set(['assigned', 'in_progress', 'review', 'ready_to_release', 'released'])

export function TaskCard({ task, onClick, onDelete, onRequeue }: TaskCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id, disabled: task.status === 'released' })

  const [showConfirm, setShowConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [requeuing, setRequeuing] = useState(false)

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  const cfg = priorityConfig[task.priority] ?? priorityConfig.normal

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation()
    setDeleting(true)
    try {
      await deleteTask(task.id)
      onDelete?.(task.id)
    } catch {
      onDelete?.(task.id)
    } finally {
      setDeleting(false)
      setShowConfirm(false)
    }
  }

  async function handleRequeue(e: React.MouseEvent) {
    e.stopPropagation()
    setRequeuing(true)
    try {
      await updateTask(task.id, { status: 'queued' })
      onRequeue?.(task.id)
    } catch {
      onRequeue?.(task.id)
    } finally {
      setRequeuing(false)
    }
  }

  const canRequeue = REQUEUE_STATUSES.has(task.status)

  return (
    <div
      ref={setNodeRef}
      style={{
        ...style,
        background: isDragging ? '#414345' : '#3C3F41',
        border: '1px solid #515151',
        borderLeft: `3px solid ${cfg.border}`,
        borderRadius: '4px',
        cursor: 'pointer',
        position: 'relative',
        /* Prevent confirm popover from escaping into sidebar */
        overflow: 'visible',
      }}
      className="p-3 transition-colors group"
      onClick={() => onClick(task)}
      onMouseEnter={e => {
        if (!isDragging) (e.currentTarget as HTMLDivElement).style.background = '#414345'
      }}
      onMouseLeave={e => {
        if (!isDragging) (e.currentTarget as HTMLDivElement).style.background = '#3C3F41'
      }}
    >
      {/* Action buttons — inside card, top-right corner, visible on hover */}
      <div
        className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ zIndex: 10 }}
        onClick={e => e.stopPropagation()}
      >
        {canRequeue && (
          <button
            onClick={handleRequeue}
            disabled={requeuing}
            title="Move to queue"
            className="flex items-center justify-center w-5 h-5 rounded transition-colors disabled:opacity-50"
            style={{ color: '#808080', background: 'transparent' }}
            onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = '#3592C4'}
            onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = '#808080'}
          >
            <Undo2 className="w-3 h-3" />
          </button>
        )}

        <button
          onClick={e => { e.stopPropagation(); setShowConfirm(v => !v) }}
          title="Delete task"
          className="flex items-center justify-center w-5 h-5 rounded transition-colors"
          style={{ color: '#808080', background: 'transparent' }}
          onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = '#CC4E4E'}
          onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = '#808080'}
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>

      {/* Confirm panel — renders inside the card below the action buttons */}
      {showConfirm && (
        <div
          className="flex items-center justify-between gap-2 mt-2 pt-2"
          style={{ borderTop: '1px solid #515151' }}
          onClick={e => e.stopPropagation()}
        >
          <p className="text-xs" style={{ color: '#BABABA' }}>Delete task?</p>
          <div className="flex gap-1.5">
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="px-2 py-0.5 text-xs rounded transition-colors disabled:opacity-50"
              style={{ background: '#CC4E4E', color: '#FFFFFF', border: 'none', cursor: 'pointer' }}
            >
              {deleting ? '...' : 'Yes'}
            </button>
            <button
              onClick={e => { e.stopPropagation(); setShowConfirm(false) }}
              className="px-2 py-0.5 text-xs rounded transition-colors"
              style={{ background: '#414345', color: '#BABABA', border: '1px solid #515151', cursor: 'pointer' }}
            >
              No
            </button>
          </div>
        </div>
      )}

      <div className="flex items-start gap-2">
        <button
          {...attributes}
          {...listeners}
          className="mt-0.5 cursor-grab active:cursor-grabbing shrink-0 transition-colors"
          style={{ color: '#515151' }}
          onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = '#808080'}
          onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = '#515151'}
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="w-3.5 h-3.5" />
        </button>

        <div className="flex-1 min-w-0 pr-10">
          <p className="text-sm leading-snug line-clamp-2 mb-2" style={{ color: '#FFFFFF' }}>
            {task.title}
          </p>

          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-xs font-medium px-1.5 py-0.5 rounded"
              style={{ color: cfg.color, background: cfg.bg }}
            >
              {cfg.label}
            </span>
            {task.depends_on && task.depends_on.length > 0 && task.status === 'queued' && (
              <span
                className="text-xs font-medium px-1.5 py-0.5 rounded"
                style={{ color: '#CC7832', background: 'rgba(204,120,50,0.2)' }}
                title="Waiting for dependencies"
              >
                ⏳ blocked
              </span>
            )}
            <span className="text-xs font-mono" style={{ color: '#808080' }}>{task.repo}</span>
            {task.branch && (
              <a
                href={`https://github.com/zinchenkomig/${task.repo}/tree/${task.branch}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={e => e.stopPropagation()}
                className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded transition-colors"
                style={{ color: '#9876AA', background: 'rgba(152,118,170,0.15)' }}
                onMouseEnter={e => (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(152,118,170,0.3)'}
                onMouseLeave={e => (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(152,118,170,0.15)'}
                title={task.branch}
              >
                <GitBranch className="w-3 h-3" />
                branch
              </a>
            )}
            {task.status === 'ready_to_release' || task.status === 'released' && task.pr_url && (
              <a
                href={task.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={e => e.stopPropagation()}
                className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded transition-colors"
                style={{ color: '#6A8759', background: 'rgba(106,135,89,0.15)' }}
                onMouseEnter={e => (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(106,135,89,0.3)'}
                onMouseLeave={e => (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(106,135,89,0.15)'}
              >
                <ExternalLink className="w-3 h-3" />
                PR
              </a>
            )}
          </div>

          <div className="flex items-center justify-between mt-2">
            {task.assigned_to && (
              <span className="text-xs" style={{ color: '#9876AA' }}>{task.assigned_to}</span>
            )}
            <span className="text-xs ml-auto" style={{ color: '#808080' }}>
              {formatDistanceToNow(task.created_at)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
