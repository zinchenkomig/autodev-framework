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
  { id: 'queued',      title: 'Queued',      color: '#808080' },
  { id: 'in_progress', title: 'In Progress', color: '#CC7832' },
  { id: 'review',      title: 'Review',      color: '#3592C4' },
  { id: 'done',        title: 'Done',        color: '#6A8759' },
  { id: 'failed',     title: 'Failed',     color: '#CC4E4E' },
]

const KANBAN_STATUSES = new Set<TaskStatus>(['queued', 'in_progress', 'review', 'done', 'failed'])

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
  const [mobileColIndex, setMobileColIndex] = useState(0)

  const [repoFilter, setRepoFilter] = useState<string>('all')
  const [priorityFilter, setPriorityFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const repos = useMemo(() => {
    const set = new Set(tasks.map((t) => t.repo))
    return ['all', ...Array.from(set)]
  }, [tasks])

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (repoFilter !== 'all' && task.repo !== repoFilter) return false
      if (priorityFilter !== 'all' && task.priority !== priorityFilter) return false
      if (searchQuery && !task.title.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })
  }, [tasks, repoFilter, priorityFilter, searchQuery])

  const tasksByStatus = useMemo(() => {
    const map: Record<TaskStatus, Task[]> = {
      queued: [], assigned: [], in_progress: [], review: [], done: [], failed: [],
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

  function handleDeleteTask(taskId: string) {
    setTasks((prev) => prev.filter((t) => t.id !== taskId))
    if (selectedTask?.id === taskId) setSelectedTask(null)
  }

  function handleRequeuTask(taskId: string) {
    setTasks((prev) => prev.map((t) => t.id === taskId ? { ...t, status: 'queued' as const } : t))
    if (selectedTask?.id === taskId) setSelectedTask(null)
  }

  function handleStatusChange(taskId: string, newStatus: TaskStatus) {
    setTasks((prev) => prev.map((t) => t.id === taskId ? { ...t, status: newStatus } : t))
    if (selectedTask?.id === taskId) setSelectedTask((prev) => prev ? { ...prev, status: newStatus } : prev)
  }

  const inputStyle = {
    background: '#3C3F41',
    border: '1px solid #515151',
    color: '#BABABA',
    borderRadius: '4px',
    padding: '6px 12px',
    fontSize: '13px',
    outline: 'none',
  }

  const selectStyle = {
    ...inputStyle,
    cursor: 'pointer',
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5" style={{ color: '#808080' }} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search tasks..."
            style={{ ...inputStyle, paddingLeft: '32px', width: '100%' }}
          />
        </div>

        {/* Filters */}
        <div className="flex gap-2 items-center">
          <Filter className="size-3.5 shrink-0" style={{ color: '#808080' }} />

          <select
            value={repoFilter}
            onChange={(e) => setRepoFilter(e.target.value)}
            style={{ ...selectStyle, background: '#313335' }}
          >
            {repos.map((r) => (
              <option key={r} value={r} style={{ background: '#313335' }}>
                {r === 'all' ? 'All repos' : r}
              </option>
            ))}
          </select>

          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            style={{ ...selectStyle, background: '#313335' }}
          >
            <option value="all" style={{ background: '#313335' }}>All priorities</option>
            <option value="critical" style={{ background: '#313335' }}>Critical</option>
            <option value="high" style={{ background: '#313335' }}>High</option>
            <option value="normal" style={{ background: '#313335' }}>Normal</option>
            <option value="low" style={{ background: '#313335' }}>Low</option>
          </select>

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors shrink-0"
            style={{
              background: '#3592C4',
              color: '#FFFFFF',
              border: '1px solid #3592C4',
              borderRadius: '4px',
            }}
            onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.background = '#2a7aaa'}
            onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.background = '#3592C4'}
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
        <div
          className="hidden md:flex pb-4 flex-1"
          style={{ border: '1px solid #515151', borderRadius: '4px', overflowX: 'auto', overflowY: 'hidden' }}
        >
          {COLUMNS.map((col) => (
            <KanbanColumn
              key={col.id}
              id={col.id}
              title={col.title}
              color={col.color}
              tasks={tasksByStatus[col.id]}
              onTaskClick={setSelectedTask}
              onTaskDelete={handleDeleteTask}
              onTaskRequeue={handleRequeuTask}
            />
          ))}
        </div>

        {/* Mobile: single column */}
        <div className="md:hidden flex flex-col flex-1">
          <div className="flex items-center justify-between mb-3">
            <button
              onClick={() => setMobileColIndex(i => Math.max(0, i - 1))}
              disabled={mobileColIndex === 0}
              className="p-2 transition-colors disabled:opacity-30"
              style={{ color: '#808080' }}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-2">
              <span className="text-xs" style={{ color: COLUMNS[mobileColIndex].color }}>●</span>
              <span className="text-xs uppercase tracking-wider" style={{ color: '#BABABA' }}>
                {COLUMNS[mobileColIndex].title}
              </span>
              <span className="text-xs font-mono" style={{ color: '#808080' }}>
                {tasksByStatus[COLUMNS[mobileColIndex].id].length}
              </span>
            </div>
            <button
              onClick={() => setMobileColIndex(i => Math.min(COLUMNS.length - 1, i + 1))}
              disabled={mobileColIndex === COLUMNS.length - 1}
              className="p-2 transition-colors disabled:opacity-30"
              style={{ color: '#808080' }}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          <div className="flex justify-center gap-1.5 mb-3">
            {COLUMNS.map((_, i) => (
              <button
                key={i}
                onClick={() => setMobileColIndex(i)}
                className="w-1.5 h-1.5 rounded-full transition-colors"
                style={{ background: i === mobileColIndex ? '#3592C4' : '#515151' }}
              />
            ))}
          </div>
          <div className="flex-1 overflow-y-auto">
            <KanbanColumn
              key={COLUMNS[mobileColIndex].id}
              id={COLUMNS[mobileColIndex].id}
              title={COLUMNS[mobileColIndex].title}
              color={COLUMNS[mobileColIndex].color}
              tasks={tasksByStatus[COLUMNS[mobileColIndex].id]}
              onTaskClick={setSelectedTask}
              onTaskDelete={handleDeleteTask}
              onTaskRequeue={handleRequeuTask}
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

      {selectedTask && (
        <TaskDetail task={selectedTask} onClose={() => setSelectedTask(null)} onStatusChange={handleStatusChange} />
      )}
      {showAddModal && (
        <AddTaskModal onClose={() => setShowAddModal(false)} onAdd={handleAddTask} />
      )}
    </div>
  )
}
