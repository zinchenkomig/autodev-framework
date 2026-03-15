'use client'

import { useState, useMemo } from 'react'
import {
  DndContext,
  DragOverlay,
  closestCorners,
  type DragStartEvent,
  type DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { arrayMove } from '@dnd-kit/sortable'
import { type Task, type TaskStatus } from '@/lib/api'
import { KanbanColumn } from './KanbanColumn'
import { TaskCard } from './TaskCard'
import { TaskDetail } from './TaskDetail'
import { AddTaskModal } from './AddTaskModal'
import { Plus, Search, Filter } from 'lucide-react'

const COLUMNS: { id: TaskStatus; title: string; color: string }[] = [
  { id: 'queued', title: 'Queued', color: 'bg-gray-400' },
  { id: 'in_progress', title: 'In Progress', color: 'bg-yellow-400' },
  { id: 'review', title: 'Review', color: 'bg-blue-400' },
  { id: 'done', title: 'Done', color: 'bg-green-400' },
]

// Statuses shown in kanban (we hide assigned/failed from the board)
const KANBAN_STATUSES = new Set<TaskStatus>(['queued', 'in_progress', 'review', 'done'])

interface KanbanBoardProps {
  initialTasks: Task[]
}

export function KanbanBoard({ initialTasks }: KanbanBoardProps) {
  const [tasks, setTasks] = useState<Task[]>(
    initialTasks.filter((t) => KANBAN_STATUSES.has(t.status))
  )
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)

  // Filters
  const [repoFilter, setRepoFilter] = useState<string>('all')
  const [priorityFilter, setPriorityFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  // Unique repos
  const repos = useMemo(() => {
    const set = new Set(tasks.map((t) => t.repo))
    return ['all', ...Array.from(set)]
  }, [tasks])

  // Filtered tasks
  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (repoFilter !== 'all' && task.repo !== repoFilter) return false
      if (priorityFilter !== 'all' && task.priority !== priorityFilter) return false
      if (searchQuery && !task.title.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })
  }, [tasks, repoFilter, priorityFilter, searchQuery])

  // Group filtered tasks by status
  const tasksByStatus = useMemo(() => {
    const map: Record<TaskStatus, Task[]> = {
      queued: [],
      assigned: [],
      in_progress: [],
      review: [],
      done: [],
      failed: [],
    }
    for (const task of filteredTasks) {
      map[task.status].push(task)
    }
    return map
  }, [filteredTasks])

  function handleDragStart(event: DragStartEvent) {
    const task = tasks.find((t) => t.id === event.active.id)
    setActiveTask(task ?? null)
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    setActiveTask(null)

    if (!over) return

    const activeId = active.id as string
    const overId = over.id as string

    // Determine target column
    const overColumn = COLUMNS.find((c) => c.id === overId)
    const overTask = tasks.find((t) => t.id === overId)
    const targetStatus: TaskStatus = overColumn
      ? overColumn.id
      : (overTask?.status ?? 'queued')

    setTasks((prev) => {
      const activeIndex = prev.findIndex((t) => t.id === activeId)
      if (activeIndex === -1) return prev

      const updated = [...prev]
      updated[activeIndex] = { ...updated[activeIndex], status: targetStatus }

      // Reorder within column if dropping on a task
      if (overTask && overTask.status === targetStatus) {
        const overIndex = updated.findIndex((t) => t.id === overId)
        return arrayMove(updated, activeIndex, overIndex)
      }

      return updated
    })
  }

  function handleAddTask(newTask: Task) {
    setTasks((prev) => [newTask, ...prev])
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-gray-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search tasks..."
            className="w-full bg-gray-900 border border-gray-800 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all"
          />
        </div>

        {/* Filters */}
        <div className="flex gap-2 items-center">
          <Filter className="size-4 text-gray-500 shrink-0" />

          <select
            value={repoFilter}
            onChange={(e) => setRepoFilter(e.target.value)}
            className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
          >
            {repos.map((r) => (
              <option key={r} value={r}>
                {r === 'all' ? 'All repos' : r}
              </option>
            ))}
          </select>

          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all"
          >
            <option value="all">All priorities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </select>

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-500 transition-all shrink-0"
          >
            <Plus className="size-4" />
            Add Task
          </button>
        </div>
      </div>

      {/* Board */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex gap-4 overflow-x-auto pb-4 flex-1">
          {COLUMNS.map((col) => (
            <KanbanColumn
              key={col.id}
              id={col.id}
              title={col.title}
              color={col.color}
              tasks={tasksByStatus[col.id]}
              onTaskClick={setSelectedTask}
            />
          ))}
        </div>

        <DragOverlay>
          {activeTask && (
            <div className="rotate-2 scale-105 opacity-90">
              <TaskCard task={activeTask} onClick={() => {}} />
            </div>
          )}
        </DragOverlay>
      </DndContext>

      {/* Task detail panel */}
      {selectedTask && (
        <TaskDetail task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}

      {/* Add task modal */}
      {showAddModal && (
        <AddTaskModal onClose={() => setShowAddModal(false)} onAdd={handleAddTask} />
      )}
    </div>
  )
}
