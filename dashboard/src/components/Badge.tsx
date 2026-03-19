import { type Priority, type TaskStatus } from '@/lib/api'

const priorityConfig: Record<Priority, { bg: string; color: string; label: string }> = {
  critical: { bg: '#CC4E4E',           color: '#FFFFFF', label: 'critical' },
  high:     { bg: '#CC7832',           color: '#FFFFFF', label: 'high'     },
  normal:   { bg: '#3592C4',           color: '#FFFFFF', label: 'normal'   },
  low:      { bg: 'rgba(81,81,81,0.5)', color: '#BABABA', label: 'low'     },
}

const statusConfig: Record<TaskStatus, { label: string; color: string; bg: string }> = {
  queued:      { label: 'queued',      color: '#808080', bg: 'rgba(128,128,128,0.15)' },
  assigned:    { label: 'assigned',    color: '#9876AA', bg: 'rgba(152,118,170,0.15)' },
  in_progress: { label: 'in progress', color: '#CC7832', bg: 'rgba(204,120,50,0.15)'  },
  review:      { label: 'review',      color: '#3592C4', bg: 'rgba(53,146,196,0.15)'  },
  done:        { label: 'done',        color: '#6A8759', bg: 'rgba(106,135,89,0.15)'  },
  ready_to_release: { label: 'ready', color: '#9876AA', bg: 'rgba(152,118,170,0.15)' },
  failed:      { label: 'failed',      color: '#CC4E4E', bg: 'rgba(204,78,78,0.15)'   },
}

interface PriorityBadgeProps {
  priority: Priority
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  const cfg = priorityConfig[priority]
  return (
    <span
      className="inline-flex items-center text-xs font-medium px-1.5 py-0.5 rounded"
      style={{ color: cfg.color, background: cfg.bg }}
    >
      {cfg.label}
    </span>
  )
}

interface StatusBadgeProps {
  status: TaskStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const cfg = statusConfig[status]
  return (
    <span
      className="text-xs font-mono px-1.5 py-0.5 rounded"
      style={{ color: cfg.color, background: cfg.bg }}
    >
      {cfg.label}
    </span>
  )
}

interface AgentStatusBadgeProps {
  status: 'idle' | 'running' | 'failed'
}

export function AgentStatusBadge({ status }: AgentStatusBadgeProps) {
  const configs = {
    idle:    { dot: '#808080', label: 'idle'    },
    running: { dot: '#6A8759', label: 'running' },
    failed:  { dot: '#CC4E4E', label: 'failed'  },
  }
  const cfg = configs[status]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: cfg.dot }}>
      <span
        style={{
          display: 'inline-block',
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          background: cfg.dot,
        }}
      />
      <span style={{ color: '#BABABA' }}>{cfg.label}</span>
    </span>
  )
}
