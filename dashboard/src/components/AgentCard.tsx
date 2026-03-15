import { type Agent } from '@/lib/api'
import { AgentStatusBadge } from './Badge'
import { Bot, Activity, AlertTriangle } from 'lucide-react'
import { formatDistanceToNow } from '@/lib/utils'

interface AgentCardProps {
  agent: Agent
}

export function AgentCard({ agent }: AgentCardProps) {
  return (
    <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl p-4 hover:border-gray-600 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${
            agent.status === 'running' ? 'bg-green-500/10' :
            agent.status === 'failed' ? 'bg-red-500/10' : 'bg-gray-700'
          }`}>
            <Bot className={`w-5 h-5 ${
              agent.status === 'running' ? 'text-green-400' :
              agent.status === 'failed' ? 'text-red-400' : 'text-gray-400'
            }`} />
          </div>
          <div>
            <h3 className="text-white font-semibold">{agent.role}</h3>
            <p className="text-gray-500 text-xs font-mono">{agent.id}</p>
          </div>
        </div>
        <AgentStatusBadge status={agent.status} />
      </div>

      {agent.current_task_title && (
        <div className="bg-gray-900/50 rounded-lg px-3 py-2 mb-3">
          <p className="text-xs text-gray-400 mb-0.5">Current Task</p>
          <p className="text-sm text-gray-200 truncate">{agent.current_task_title}</p>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-gray-500">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Activity className="w-3 h-3" />
            {agent.total_runs} runs
          </span>
          {agent.total_failures > 0 && (
            <span className="flex items-center gap-1 text-red-400">
              <AlertTriangle className="w-3 h-3" />
              {agent.total_failures} failures
            </span>
          )}
        </div>
        {agent.last_run_at && (
          <span>Last: {formatDistanceToNow(agent.last_run_at)}</span>
        )}
      </div>
    </div>
  )
}
