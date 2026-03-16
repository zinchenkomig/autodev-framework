import { type Task } from '@/lib/api'
import { PriorityBadge, StatusBadge } from './Badge'
import { formatDistanceToNow } from '@/lib/utils'

interface TaskTableProps {
  tasks: Task[]
}

export function TaskTable({ tasks }: TaskTableProps) {
  if (tasks.length === 0) {
    return (
      <div className="py-10 text-center text-[#3F3F46] text-sm">
        No tasks
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#1F1F23]">
            <th className="text-left py-2.5 px-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Title</th>
            <th className="text-left py-2.5 px-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Priority</th>
            <th className="text-left py-2.5 px-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Status</th>
            <th className="text-left py-2.5 px-4 text-xs text-[#71717A] uppercase tracking-wider font-normal hidden md:table-cell">Assigned</th>
            <th className="text-left py-2.5 px-4 text-xs text-[#71717A] uppercase tracking-wider font-normal hidden lg:table-cell">Repo</th>
            <th className="text-left py-2.5 px-4 text-xs text-[#71717A] uppercase tracking-wider font-normal hidden sm:table-cell">Updated</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} className="border-b border-[#1F1F23] hover:bg-white/[0.02] transition-colors">
              <td className="py-3 px-4">
                <div className="flex items-center gap-2">
                  <span className="text-[#FAFAFA] text-sm truncate max-w-[220px]">{task.title}</span>
                  {task.pr_number && (
                    <span className="text-[#6366F1] text-xs font-mono">PR#{task.pr_number}</span>
                  )}
                </div>
              </td>
              <td className="py-3 px-4">
                <PriorityBadge priority={task.priority} />
              </td>
              <td className="py-3 px-4">
                <StatusBadge status={task.status} />
              </td>
              <td className="py-3 px-4 hidden md:table-cell">
                <span className="text-[#71717A] text-xs">{task.assigned_to ?? '—'}</span>
              </td>
              <td className="py-3 px-4 hidden lg:table-cell">
                <span className="text-[#3F3F46] font-mono text-xs">{task.repo}</span>
              </td>
              <td className="py-3 px-4 hidden sm:table-cell">
                <span className="text-[#3F3F46] text-xs">{formatDistanceToNow(task.updated_at)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
