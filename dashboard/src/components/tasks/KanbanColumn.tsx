'use client'

import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { type Task } from '@/lib/api'
import { TaskCard } from './TaskCard'

interface KanbanColumnProps {
  id: string
  title: string
  tasks: Task[]
  color: string
  onTaskClick: (task: Task) => void
}

const statusDot: Record<string, string> = {
  queued:      'text-[#71717A]',
  in_progress: 'text-[#F59E0B]',
  review:      'text-[#6366F1]',
  done:        'text-[#22C55E]',
}

export function KanbanColumn({ id, title, tasks, onTaskClick }: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id })
  const dot = statusDot[id] ?? 'text-[#3F3F46]'

  return (
    <div className="flex flex-col min-w-[260px] w-full border-r border-[#1F1F23] last:border-r-0 px-3">
      {/* Column header */}
      <div className="flex items-center gap-2 mb-4 py-1">
        <span className={`text-xs ${dot}`}>●</span>
        <span className="text-xs text-[#71717A] uppercase tracking-wider">{title}</span>
        <span className="ml-auto text-xs font-mono text-[#3F3F46]">{tasks.length}</span>
      </div>

      {/* Drop zone */}
      <div
        ref={setNodeRef}
        className={`
          flex-1 min-h-[120px] transition-colors
          ${isOver ? 'bg-white/[0.02]' : ''}
        `}
      >
        <SortableContext items={tasks.map(t => t.id)} strategy={verticalListSortingStrategy}>
          <div className="flex flex-col gap-2">
            {tasks.map((task) => (
              <TaskCard key={task.id} task={task} onClick={onTaskClick} />
            ))}
            {tasks.length === 0 && (
              <div className="flex items-center justify-center h-16 text-[#3F3F46] text-xs">
                empty
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
  )
}
