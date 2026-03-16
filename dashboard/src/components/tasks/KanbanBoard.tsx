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
import { Plus, Search, Filter, ChevronLeft, ChevronRight } from 'lucide-react'

const COLUMNS: { id: TaskStatus; title: string; color: string }[] = [
  { id: 'queued', title: 'Queued', color: 'text-[#71717A]' },
  { id: 'in_progress', title: 'In Progress', color: 'text-[#F59E0B]' },
  { id: 'review', title: 'Review', color: 'text-[#6366F1]' },
  { id: 'done', title: 'Done', color: 'text-[#22C55E]' },
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
  // Mobile column switcher
  const [mobileColIndex, setMobileColIndex] = useState(0)

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
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[#3F3F46]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search tasks..."
            className="w-full bg-transparent border border-[#1F1F23] pl-8 pr-4 py-2 text-sm text-[#FAFAFA] placeholder-[#3F3F46] focus:outline-none focus:border-[#6366F1]/50 transition-colors"
          />
        </div>

        {/* Filters */}
        <div className="flex gap-2 items-center">
          <Filter className="size-3.5 text-[#3F3F46] shrink-0" />

          <select
            value={repoFilter}
            onChange={(e) => setRepoFilter(e.target.value)}
            className="bg-transparent border border-[#1F1F23] px-3 py-2 text-xs text-[#71717A] focus:outline-none focus:border-[#6366F1]/50 transition-colors"
          >
            {repos.map((r) => (
              <option key={r} value={r} className="bg-[#111113]">
                {r === 'all' ? 'All repos' : r}
              </option>
            ))}
          </select>

          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="bg-transparent border border-[#1F1F23] px-3 py-2 text-xs text-[#71717A] focus:outline-none focus:border-[#6366F1]/50 transition-colors"
          >
            <option value="all" className="bg-[#111113]">All priorities</option>
            <option value="critical" className="bg-[#111113]">Critical</option>
            <option value="high" className="bg-[#111113]">High</option>
            <option value="normal" className="bg-[#111113]">Normal</option>
            <option value="low" className="bg-[#111113]">Low</option>
          </select>

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-[#FAFAFA] bg-[#6366F1] hover:bg-[#4F46E5] transition-colors shrink-0"
          >
            <Plus className="size-3.5" />
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
        {/* Desktop: all columns side-by-side */}
        <div className="hidden md:flex overflow-x-auto pb-4 flex-1 border border-[#1F1F23]">
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

        {/* Mobile: single column with prev/next switcher */}
        <div className="md:hidden flex flex-col flex-1">
          {/* Column switcher nav */}
          <div className="flex items-center justify-between mb-3">
            <button
              onClick={() => setMobileColIndex(i => Math.max(0, i - 1))}
              disabled={mobileColIndex === 0}
              className="p-2 text-[#3F3F46] hover:text-[#71717A] disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-2">
              <span className={`text-xs ${COLUMNS[mobileColIndex].color}`}>●</span>
              <span className="text-xs text-[#71717A] uppercase tracking-wider">
                {COLUMNS[mobileColIndex].title}
              </span>
              <span className="text-xs font-mono text-[#3F3F46]">
                {tasksByStatus[COLUMNS[mobileColIndex].id].length}
              </span>
            </div>
            <button
              onClick={() => setMobileColIndex(i => Math.min(COLUMNS.length - 1, i + 1))}
              disabled={mobileColIndex === COLUMNS.length - 1}
              className="p-2 text-[#3F3F46] hover:text-[#71717A] disabled:opacity-30 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          {/* Dots indicator */}
          <div className="flex justify-center gap-1.5 mb-3">
            {COLUMNS.map((_, i) => (
              <button
                key={i}
                onClick={() => setMobileColIndex(i)}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${i === mobileColIndex ? 'bg-[#6366F1]' : 'bg-[#1F1F23]'}`}
              />
            ))}
          </div>
          {/* Active column */}
          <div className="flex-1 overflow-y-auto">
            <KanbanColumn
              key={COLUMNS[mobileColIndex].id}
              id={COLUMNS[mobileColIndex].id}
              title={COLUMNS[mobileColIndex].title}
              color={COLUMNS[mobileColIndex].color}
              tasks={tasksByStatus[COLUMNS[mobileColIndex].id]}
              onTaskClick={setSelectedTask}
            />
          </div>
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
