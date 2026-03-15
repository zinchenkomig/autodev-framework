import { type Priority, type TaskStatus } from '@/lib/api'

const priorityConfig: Record<Priority, { label: string; className: string }> = {
  critical: { label: 'Critical', className: 'bg-red-500/20 text-red-400 border border-red-500/30' },
  high: { label: 'High', className: 'bg-orange-500/20 text-orange-400 border border-orange-500/30' },
  normal: { label: 'Normal', className: 'bg-blue-500/20 text-blue-400 border border-blue-500/30' },
  low: { label: 'Low', className: 'bg-gray-500/20 text-gray-400 border border-gray-500/30' },
}

const statusConfig: Record<TaskStatus, { label: string; className: string }> = {
  queued: { label: 'Queued', className: 'bg-gray-500/20 text-gray-400 border border-gray-500/30' },
  assigned: { label: 'Assigned', className: 'bg-purple-500/20 text-purple-400 border border-purple-500/30' },
  in_progress: { label: 'In Progress', className: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' },
  review: { label: 'Review', className: 'bg-blue-500/20 text-blue-400 border border-blue-500/30' },
  done: { label: 'Done', className: 'bg-green-500/20 text-green-400 border border-green-500/30' },
  failed: { label: 'Failed', className: 'bg-red-500/20 text-red-400 border border-red-500/30' },
}

interface PriorityBadgeProps {
  priority: Priority
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  const config = priorityConfig[priority]
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${config.className}`}>
      {config.label}
    </span>
  )
}

interface StatusBadgeProps {
  status: TaskStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status]
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${config.className}`}>
      {config.label}
    </span>
  )
}

interface AgentStatusBadgeProps {
  status: 'idle' | 'running' | 'failed'
}

export function AgentStatusBadge({ status }: AgentStatusBadgeProps) {
  const configs = {
    idle: { label: 'Idle', className: 'bg-gray-500/20 text-gray-400 border border-gray-500/30', dot: 'bg-gray-400' },
    running: { label: 'Running', className: 'bg-green-500/20 text-green-400 border border-green-500/30', dot: 'bg-green-400 animate-pulse' },
    failed: { label: 'Failed', className: 'bg-red-500/20 text-red-400 border border-red-500/30', dot: 'bg-red-400' },
  }
  const config = configs[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium ${config.className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  )
}
