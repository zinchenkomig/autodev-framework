import { type Agent } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

interface AgentCardProps {
  agent: Agent
}

const statusConfig: Record<string, { color: string; label: string; pulse: boolean }> = {
  running: { color: '#6A8759', label: 'running', pulse: true  },
  idle:    { color: '#808080', label: 'idle',    pulse: false },
  failed:  { color: '#CC4E4E', label: 'failed',  pulse: false },
}

export function AgentCard({ agent }: AgentCardProps) {
  const cfg = statusConfig[agent.status] ?? statusConfig.idle

  return (
    <div
      className="py-3 transition-colors"
      style={{ borderBottom: '1px solid #414345' }}
      onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.background = '#353739'}
      onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.background = 'transparent'}
    >
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span
            className={cfg.pulse ? 'animate-status-pulse' : ''}
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: cfg.color,
              flexShrink: 0,
            }}
          />
          <span className="text-sm font-medium" style={{ color: '#FFFFFF' }}>{agent.role}</span>
          <span
            className="text-xs px-1.5 py-0.5 rounded font-mono"
            style={{ color: cfg.color, background: `${cfg.color}20` }}
          >
            {cfg.label}
          </span>
        </div>
        <span className="text-xs font-mono" style={{ color: '#808080' }}>{agent.total_runs} runs</span>
      </div>

      {agent.current_task_title && (
        <p className="text-xs truncate ml-5" style={{ color: '#BABABA' }}>{agent.current_task_title}</p>
      )}

      <div className="flex items-center justify-between mt-1 ml-5">
        <span className="text-xs font-mono" style={{ color: '#808080' }}>{agent.id}</span>
        {agent.last_run_at && (
          <span className="text-xs" style={{ color: '#808080' }}>{formatDistanceToNow(agent.last_run_at)}</span>
        )}
      </div>
    </div>
  )
}
