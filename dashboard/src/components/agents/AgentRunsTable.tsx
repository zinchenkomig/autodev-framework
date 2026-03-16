import { type AgentRun } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

interface AgentRunsTableProps {
  runs: AgentRun[]
}

const statusColor: Record<AgentRun['run_status'], string> = {
  success:   'text-[#22C55E]',
  failed:    'text-[#EF4444]',
  running:   'text-[#F59E0B]',
  cancelled: 'text-[#3F3F46]',
}

export function AgentRunsTable({ runs }: AgentRunsTableProps) {
  if (runs.length === 0) {
    return (
      <div className="py-10 text-center text-[#3F3F46] text-sm">
        No runs
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#1F1F23]">
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Agent</th>
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Task</th>
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Status</th>
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Duration</th>
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Tokens</th>
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Cost</th>
            <th className="text-left py-2.5 pr-4 text-xs text-[#71717A] uppercase tracking-wider font-normal">Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-b border-[#1F1F23] hover:bg-white/[0.02] transition-colors">
              <td className="py-3 pr-4">
                <span className="text-[#FAFAFA] text-xs">{run.agent_role}</span>
              </td>
              <td className="py-3 pr-4">
                <span className="text-[#71717A] text-xs truncate max-w-[200px] block">{run.task_title}</span>
              </td>
              <td className="py-3 pr-4">
                <span className={`text-xs font-mono ${statusColor[run.run_status]}`}>
                  {run.run_status}
                </span>
              </td>
              <td className="py-3 pr-4 text-[#71717A] text-xs font-mono">
                {run.duration ?? '—'}
              </td>
              <td className="py-3 pr-4 text-[#71717A] text-xs font-mono">
                {run.tokens != null ? run.tokens.toLocaleString() : '—'}
              </td>
              <td className="py-3 pr-4 text-[#71717A] text-xs font-mono">
                {run.cost != null ? `$${run.cost.toFixed(4)}` : '—'}
              </td>
              <td className="py-3 text-[#3F3F46] text-xs">
                {formatDistanceToNow(run.started_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
