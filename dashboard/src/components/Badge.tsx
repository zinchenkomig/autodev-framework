import { type Priority, type TaskStatus } from '@/lib/api'

const priorityDot: Record<Priority, { color: string; label: string }> = {
  critical: { color: 'text-[#EF4444]', label: 'critical' },
  high:     { color: 'text-[#F59E0B]', label: 'high' },
  normal:   { color: 'text-[#71717A]', label: 'normal' },
  low:      { color: 'text-[#3F3F46]', label: 'low' },
}

const statusConfig: Record<TaskStatus, { label: string; color: string }> = {
  queued:      { label: 'queued',      color: 'text-[#71717A]' },
  assigned:    { label: 'assigned',    color: 'text-[#A78BFA]' },
  in_progress: { label: 'in progress', color: 'text-[#F59E0B]' },
  review:      { label: 'review',      color: 'text-[#6366F1]' },
  done:        { label: 'done',        color: 'text-[#22C55E]' },
  failed:      { label: 'failed',      color: 'text-[#EF4444]' },
}

interface PriorityBadgeProps {
  priority: Priority
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  const config = priorityDot[priority]
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${config.color}`}>
      ●<span className="text-[#71717A]">{config.label}</span>
    </span>
  )
}

interface StatusBadgeProps {
  status: TaskStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status]
  return (
    <span className={`text-xs font-mono ${config.color}`}>
      {config.label}
    </span>
  )
}

interface AgentStatusBadgeProps {
  status: 'idle' | 'running' | 'failed'
}

export function AgentStatusBadge({ status }: AgentStatusBadgeProps) {
  const configs = {
    idle:    { dot: 'text-[#3F3F46]',  label: 'idle' },
    running: { dot: 'text-[#22C55E]',  label: 'running' },
    failed:  { dot: 'text-[#EF4444]',  label: 'failed' },
  }
  const config = configs[status]
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${config.dot}`}>
      ●<span className="text-[#71717A]">{config.label}</span>
    </span>
  )
}
