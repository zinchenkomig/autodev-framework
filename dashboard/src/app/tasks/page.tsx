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
        <Loader2 className="w-4 h-4 text-[#3F3F46] animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full space-y-6">
      <div>
        <h1 className="text-sm font-semibold text-[#FAFAFA]">Tasks</h1>
        <p className="text-xs text-[#71717A] mt-0.5">Drag cards to update status</p>
      </div>

      <KanbanBoard initialTasks={tasks} />
    </div>
  )
}
