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
  onTaskDelete?: (taskId: string) => void
  onTaskRequeue?: (taskId: string) => void
}

const columnConfig: Record<string, { dot: string; bg: string; badge: string }> = {
  queued:      { dot: '#808080',  bg: '#313335', badge: 'rgba(128,128,128,0.2)' },
  in_progress: { dot: '#CC7832',  bg: '#313335', badge: 'rgba(204,120,50,0.2)'  },
  review:      { dot: '#3592C4',  bg: '#313335', badge: 'rgba(53,146,196,0.2)'  },
  done:        { dot: '#6A8759',  bg: '#313335', badge: 'rgba(106,135,89,0.2)'  },
  ready_to_release: { dot: '#9876AA', bg: '#313335', badge: 'rgba(152,118,170,0.2)' },
}

export function KanbanColumn({ id, title, tasks, onTaskClick, onTaskDelete, onTaskRequeue }: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id })
  const cfg = columnConfig[id] ?? columnConfig.queued

  // Badge: grey when 0 tasks, column-accent when non-zero
  const badgeDot = tasks.length === 0 ? '#515151' : cfg.dot
  const badgeBg = tasks.length === 0 ? 'rgba(81,81,81,0.2)' : cfg.badge

  return (
    <div
      className="flex flex-col min-w-[260px] w-full"
      style={{
        borderRight: '1px solid #515151',
        /* Contain card tooltips/popovers within the column */
        overflow: 'hidden',
      }}
    >
      {/* Column header */}
      <div
        className="flex items-center gap-2 px-3 py-2.5"
        style={{ borderBottom: '1px solid #515151', background: '#2B2B2B' }}
      >
        <span className="text-xs" style={{ color: cfg.dot }}>●</span>
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#BABABA' }}>{title}</span>
        <span
          className="ml-auto text-xs font-mono px-1.5 py-0.5 rounded"
          style={{ color: badgeDot, background: badgeBg }}
        >
          {tasks.length}
        </span>
      </div>

      {/* Drop zone */}
      <div
        ref={setNodeRef}
        className="flex-1 min-h-[120px] p-2 transition-colors"
        style={{
          background: isOver ? '#353739' : cfg.bg,
          overflowY: 'auto',
          maxHeight: 'calc(100vh - 200px)',
        }}
      >
        <SortableContext items={tasks.map(t => t.id)} strategy={verticalListSortingStrategy}>
          <div className="flex flex-col gap-2">
            {tasks.map((task) => (
              <TaskCard key={task.id} task={task} onClick={onTaskClick} onDelete={onTaskDelete} onRequeue={onTaskRequeue} />
            ))}
            {tasks.length === 0 && (
              <div className="flex items-center justify-center h-16 text-xs" style={{ color: '#636363' }}>
                drop tasks here
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
  )
}
