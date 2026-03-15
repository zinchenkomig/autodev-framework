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

export function KanbanColumn({ id, title, tasks, color, onTaskClick }: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id })

  return (
    <div className="flex flex-col min-w-[280px] w-full">
      {/* Column header */}
      <div className="flex items-center gap-2 mb-3 px-1">
        <div className={`w-2 h-2 rounded-full ${color}`} />
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          {title}
        </h3>
        <span className="ml-auto text-xs font-medium text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">
          {tasks.length}
        </span>
      </div>

      {/* Drop zone */}
      <div
        ref={setNodeRef}
        className={`
          flex-1 rounded-xl p-2 min-h-[120px] transition-colors
          ${isOver
            ? 'bg-gray-700/60 border-2 border-dashed border-blue-500/50'
            : 'bg-gray-900/50 border-2 border-dashed border-gray-800'
          }
        `}
      >
        <SortableContext items={tasks.map(t => t.id)} strategy={verticalListSortingStrategy}>
          <div className="flex flex-col gap-2">
            {tasks.map((task) => (
              <TaskCard key={task.id} task={task} onClick={onTaskClick} />
            ))}
            {tasks.length === 0 && (
              <div className="flex items-center justify-center h-20 text-gray-600 text-sm">
                Drop tasks here
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
  )
}
