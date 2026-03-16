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

const priorityDot: Record<string, { color: string; label: string }> = {
  critical: { color: 'text-[#EF4444]', label: 'critical' },
  high:     { color: 'text-[#F59E0B]', label: 'high' },
  normal:   { color: 'text-[#71717A]', label: 'normal' },
  low:      { color: 'text-[#3F3F46]', label: 'low' },
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

  const dot = priorityDot[task.priority] ?? priorityDot.normal

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`
        border border-[#1F1F23] bg-[#111113] p-3 cursor-pointer
        hover:border-[#3F3F46] transition-colors
        ${isDragging ? 'ring-1 ring-[#6366F1]/50' : ''}
      `}
      onClick={() => onClick(task)}
    >
      <div className="flex items-start gap-2">
        <button
          {...attributes}
          {...listeners}
          className="mt-0.5 text-[#3F3F46] hover:text-[#71717A] cursor-grab active:cursor-grabbing shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="w-3.5 h-3.5" />
        </button>

        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#FAFAFA] leading-snug line-clamp-2 mb-2">
            {task.title}
          </p>

          <div className="flex items-center gap-3 text-xs">
            <span className={dot.color}>●</span>
            <span className="text-[#71717A]">{dot.label}</span>
            <span className="text-[#3F3F46] font-mono">{task.repo}</span>
          </div>

          <div className="flex items-center justify-between mt-2">
            {task.assigned_to && (
              <span className="text-xs text-[#3F3F46]">{task.assigned_to}</span>
            )}
            <span className="text-xs text-[#3F3F46] ml-auto">
              {formatDistanceToNow(task.created_at)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
