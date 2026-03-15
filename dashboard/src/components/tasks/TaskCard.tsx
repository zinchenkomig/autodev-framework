'use client'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { type Task } from '@/lib/api'
import { PriorityBadge } from '@/components/Badge'
import { formatDistanceToNow } from '@/lib/utils'
import { GripVertical, GitPullRequest, Hash, User2 } from 'lucide-react'

interface TaskCardProps {
  task: Task
  onClick: (task: Task) => void
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

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`
        bg-gray-800 border border-gray-700 rounded-lg p-3 cursor-pointer
        hover:border-gray-600 hover:bg-gray-750 transition-all
        ${isDragging ? 'shadow-2xl ring-1 ring-blue-500/50' : ''}
      `}
      onClick={() => onClick(task)}
    >
      <div className="flex items-start gap-2">
        {/* Drag handle */}
        <button
          {...attributes}
          {...listeners}
          className="mt-0.5 text-gray-600 hover:text-gray-400 cursor-grab active:cursor-grabbing shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="size-4" />
        </button>

        <div className="flex-1 min-w-0">
          {/* Title */}
          <p className="text-sm text-white font-medium leading-snug line-clamp-2 mb-2">
            {task.title}
          </p>

          {/* Badges */}
          <div className="flex flex-wrap gap-1.5 mb-2">
            <PriorityBadge priority={task.priority} />
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-700 text-gray-300 border border-gray-600">
              {task.repo}
            </span>
          </div>

          {/* Meta */}
          <div className="flex items-center gap-3 text-xs text-gray-500">
            {task.assigned_to && (
              <span className="flex items-center gap-1">
                <User2 className="size-3" />
                {task.assigned_to}
              </span>
            )}
            {task.issue_number && (
              <span className="flex items-center gap-1">
                <Hash className="size-3" />
                {task.issue_number}
              </span>
            )}
            {task.pr_number && (
              <span className="flex items-center gap-1 text-blue-400">
                <GitPullRequest className="size-3" />
                PR#{task.pr_number}
              </span>
            )}
          </div>

          {/* Time */}
          <p className="text-xs text-gray-600 mt-1.5">
            {formatDistanceToNow(task.created_at)}
          </p>
        </div>
      </div>
    </div>
  )
}
