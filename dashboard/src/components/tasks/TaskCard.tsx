'use client'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { type Task } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { GripVertical } from 'lucide-react'

interface TaskCardProps {
  task: Task
  onClick: (task: Task) => void
}

const priorityConfig: Record<string, { color: string; bg: string; label: string; border: string }> = {
  critical: { color: '#FFFFFF', bg: '#CC4E4E', label: 'critical', border: '#CC4E4E' },
  high:     { color: '#FFFFFF', bg: '#CC7832', label: 'high',     border: '#CC7832' },
  normal:   { color: '#FFFFFF', bg: '#3592C4', label: 'normal',   border: '#3592C4' },
  low:      { color: '#BABABA', bg: '#414345', label: 'low',      border: '#515151' },
}

export function TaskCard({ task, onClick }: TaskCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  const cfg = priorityConfig[task.priority] ?? priorityConfig.normal

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
      }}
      className="p-3 transition-colors"
      onClick={() => onClick(task)}
      onMouseEnter={e => {
        if (!isDragging) (e.currentTarget as HTMLDivElement).style.background = '#414345'
      }}
      onMouseLeave={e => {
        if (!isDragging) (e.currentTarget as HTMLDivElement).style.background = '#3C3F41'
      }}
    >
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

        <div className="flex-1 min-w-0">
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
            <span className="text-xs font-mono" style={{ color: '#808080' }}>{task.repo}</span>
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
