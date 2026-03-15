import { getTasks } from '@/lib/api'
import { KanbanBoard } from '@/components/tasks/KanbanBoard'

export default async function TasksPage() {
  const tasks = await getTasks()

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
