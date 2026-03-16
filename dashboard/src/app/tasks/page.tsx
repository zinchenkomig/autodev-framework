'use client'

import { useEffect, useState } from 'react'
import { getTasks, type Task } from '@/lib/api'
import { KanbanBoard } from '@/components/tasks/KanbanBoard'
import { Loader2 } from 'lucide-react'

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getTasks().then((t) => {
      setTasks(t)
      setLoading(false)
    })
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full space-y-4">
      <div>
        <h2 className="text-2xl font-bold text-white">Tasks</h2>
        <p className="text-gray-400 text-sm mt-1">Kanban board — drag cards to update status</p>
      </div>

      <KanbanBoard initialTasks={tasks} />
    </div>
  )
}
