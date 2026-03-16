import { type Agent } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

interface AgentCardProps {
  agent: Agent
}

const statusDot: Record<string, string> = {
  running: 'text-[#22C55E]',
  idle:    'text-[#3F3F46]',
  failed:  'text-[#EF4444]',
}

export function AgentCard({ agent }: AgentCardProps) {
  const dot = statusDot[agent.status] ?? 'text-[#3F3F46]'

  return (
    <div className="py-3 border-b border-[#1F1F23] last:border-b-0 hover:bg-white/[0.02] transition-colors px-1">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className={`text-xs ${dot}`}>●</span>
          <span className="text-sm text-[#FAFAFA]">{agent.role}</span>
        </div>
        <span className="text-xs text-[#3F3F46] font-mono">{agent.total_runs} runs</span>
      </div>

      {agent.current_task_title && (
        <p className="text-xs text-[#71717A] truncate ml-4">{agent.current_task_title}</p>
      )}

      <div className="flex items-center justify-between mt-1 ml-4">
        <span className="text-xs font-mono text-[#3F3F46]">{agent.id}</span>
        {agent.last_run_at && (
          <span className="text-xs text-[#3F3F46]">{formatDistanceToNow(agent.last_run_at)}</span>
        )}
      </div>
    </div>
  )
}
