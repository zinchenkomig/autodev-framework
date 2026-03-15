import { type Task } from '@/lib/api'
import { PriorityBadge, StatusBadge } from './Badge'
import { formatDistanceToNow } from '@/lib/utils'

interface TaskTableProps {
  tasks: Task[]
}

export function TaskTable({ tasks }: TaskTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800">
            <th className="text-left py-3 px-4 text-gray-400 font-medium">Title</th>
            <th className="text-left py-3 px-4 text-gray-400 font-medium">Priority</th>
            <th className="text-left py-3 px-4 text-gray-400 font-medium">Status</th>
            <th className="text-left py-3 px-4 text-gray-400 font-medium">Assigned</th>
            <th className="text-left py-3 px-4 text-gray-400 font-medium">Repo</th>
            <th className="text-left py-3 px-4 text-gray-400 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
              <td className="py-3 px-4">
                <div className="flex items-center gap-2">
                  <span className="text-white font-medium truncate max-w-[220px]">{task.title}</span>
                  {task.issue_number && (
                    <span className="text-gray-500 text-xs">#{task.issue_number}</span>
                  )}
                  {task.pr_number && (
                    <span className="text-blue-400 text-xs">PR#{task.pr_number}</span>
                  )}
                </div>
              </td>
              <td className="py-3 px-4">
                <PriorityBadge priority={task.priority} />
              </td>
              <td className="py-3 px-4">
                <StatusBadge status={task.status} />
              </td>
              <td className="py-3 px-4">
                <span className="text-gray-300">{task.assigned_to ?? '—'}</span>
              </td>
              <td className="py-3 px-4">
                <span className="text-gray-400 font-mono text-xs">{task.repo}</span>
              </td>
              <td className="py-3 px-4">
                <span className="text-gray-500 text-xs">{formatDistanceToNow(task.updated_at)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
