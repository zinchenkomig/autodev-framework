import { type Task } from '@/lib/api'
import { PriorityBadge, StatusBadge } from './Badge'
import { formatDistanceToNow } from '@/lib/utils'

interface TaskTableProps {
  tasks: Task[]
}

export function TaskTable({ tasks }: TaskTableProps) {
  if (tasks.length === 0) {
    return (
      <div className="py-10 text-center text-sm" style={{ color: '#808080' }}>
        No tasks
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr style={{ background: '#313335', borderBottom: '1px solid #515151' }}>
            <th className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium" style={{ color: '#808080' }}>Title</th>
            <th className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium" style={{ color: '#808080' }}>Priority</th>
            <th className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium" style={{ color: '#808080' }}>Status</th>
            <th className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium hidden md:table-cell" style={{ color: '#808080' }}>Assigned</th>
            <th className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium hidden lg:table-cell" style={{ color: '#808080' }}>Repo</th>
            <th className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium hidden sm:table-cell" style={{ color: '#808080' }}>Updated</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task, i) => (
            <tr
              key={task.id}
              style={{
                background: i % 2 === 0 ? '#3C3F41' : '#313335',
                borderBottom: '1px solid #414345',
              }}
              onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = '#414345'}
              onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = i % 2 === 0 ? '#3C3F41' : '#313335'}
              className="transition-colors"
            >
              <td className="py-3 px-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm truncate max-w-[220px]" style={{ color: '#FFFFFF' }}>{task.title}</span>
                  {task.pr_number && (
                    <span className="text-xs font-mono" style={{ color: '#3592C4' }}>PR#{task.pr_number}</span>
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
                <span className="text-xs" style={{ color: '#9876AA' }}>{task.assigned_to ?? '—'}</span>
              </td>
              <td className="py-3 px-4 hidden lg:table-cell">
                <span className="text-xs font-mono" style={{ color: '#808080' }}>{task.repo}</span>
              </td>
              <td className="py-3 px-4 hidden sm:table-cell">
                <span className="text-xs" style={{ color: '#808080' }}>{formatDistanceToNow(task.updated_at)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
