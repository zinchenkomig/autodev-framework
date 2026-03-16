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
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full space-y-6">
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Tasks</h1>
        <p className="text-xs mt-0.5" style={{ color: '#808080' }}>Drag cards to update status</p>
      </div>

      <KanbanBoard initialTasks={tasks} />
    </div>
  )
}
