import { type AgentRun } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

interface AgentRunsTableProps {
  runs: AgentRun[]
}

const statusStyles: Record<AgentRun['run_status'], string> = {
  success: 'bg-green-500/20 text-green-400 border border-green-500/30',
  failed: 'bg-red-500/20 text-red-400 border border-red-500/30',
  running: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
  cancelled: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
}

const statusLabels: Record<AgentRun['run_status'], string> = {
  success: 'Success',
  failed: 'Failed',
  running: 'Running',
  cancelled: 'Cancelled',
}

export function AgentRunsTable({ runs }: AgentRunsTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 border-b border-gray-700/50">
            <th className="pb-3 pr-4 font-medium">Agent</th>
            <th className="pb-3 pr-4 font-medium">Task</th>
            <th className="pb-3 pr-4 font-medium">Status</th>
            <th className="pb-3 pr-4 font-medium">Duration</th>
            <th className="pb-3 pr-4 font-medium">Tokens</th>
            <th className="pb-3 pr-4 font-medium">Cost</th>
            <th className="pb-3 pr-4 font-medium">Started</th>
            <th className="pb-3 font-medium">Finished</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700/30">
          {runs.map((run) => (
            <tr key={run.id} className="hover:bg-gray-800/30 transition-colors">
              <td className="py-3 pr-4">
                <span className="text-gray-300 font-medium">{run.agent_role}</span>
                <br />
                <span className="text-gray-600 text-xs font-mono">{run.agent_id}</span>
              </td>
              <td className="py-3 pr-4">
                <span className="text-gray-300 truncate max-w-[200px] block">{run.task_title}</span>
              </td>
              <td className="py-3 pr-4">
                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusStyles[run.run_status]}`}>
                  {statusLabels[run.run_status]}
                </span>
              </td>
              <td className="py-3 pr-4 text-gray-400 tabular-nums">
                {run.duration ?? '—'}
              </td>
              <td className="py-3 pr-4 text-gray-400 tabular-nums">
                {run.tokens != null ? run.tokens.toLocaleString() : '—'}
              </td>
              <td className="py-3 pr-4 text-gray-400 tabular-nums">
                {run.cost != null ? `$${run.cost.toFixed(4)}` : '—'}
              </td>
              <td className="py-3 pr-4 text-gray-500 text-xs">
                {formatDistanceToNow(run.started_at)}
              </td>
              <td className="py-3 text-gray-500 text-xs">
                {run.finished_at ? formatDistanceToNow(run.finished_at) : <span className="text-yellow-500">In progress</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
