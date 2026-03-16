import { type AgentRun } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

interface AgentRunsTableProps {
  runs: AgentRun[]
}

const statusConfig: Record<AgentRun['run_status'], { color: string; bg: string }> = {
  success:   { color: '#6A8759', bg: 'rgba(106,135,89,0.15)'  },
  failed:    { color: '#CC4E4E', bg: 'rgba(204,78,78,0.15)'   },
  running:   { color: '#CC7832', bg: 'rgba(204,120,50,0.15)'  },
  cancelled: { color: '#808080', bg: 'rgba(128,128,128,0.1)'  },
}

export function AgentRunsTable({ runs }: AgentRunsTableProps) {
  if (runs.length === 0) {
    return (
      <div className="py-10 text-center text-sm" style={{ color: '#808080' }}>
        No runs
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr style={{ background: '#313335', borderBottom: '1px solid #515151' }}>
            {['Agent', 'Task', 'Status', 'Duration', 'Tokens', 'Cost', 'Started'].map(h => (
              <th key={h} className="text-left py-2.5 px-4 text-xs uppercase tracking-wider font-medium" style={{ color: '#808080' }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run, i) => {
            const cfg = statusConfig[run.run_status]
            return (
              <tr
                key={run.id}
                style={{
                  background: i % 2 === 0 ? '#3C3F41' : '#313335',
                  borderBottom: '1px solid #414345',
                }}
                onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = '#414345'}
                onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = i % 2 === 0 ? '#3C3F41' : '#313335'}
                className="transition-colors"
              >
                <td className="py-3 px-4">
                  <span className="text-xs font-medium" style={{ color: '#BABABA' }}>{run.agent_role}</span>
                </td>
                <td className="py-3 px-4">
                  <span className="text-xs truncate max-w-[200px] block" style={{ color: '#808080' }}>{run.task_title}</span>
                </td>
                <td className="py-3 px-4">
                  <span
                    className="text-xs font-mono px-1.5 py-0.5 rounded"
                    style={{ color: cfg.color, background: cfg.bg }}
                  >
                    {run.run_status}
                  </span>
                </td>
                <td className="py-3 px-4 font-mono text-xs" style={{ color: '#808080' }}>
                  {run.duration ?? '—'}
                </td>
                <td className="py-3 px-4 font-mono text-xs" style={{ color: '#808080' }}>
                  {run.tokens != null ? run.tokens.toLocaleString() : '—'}
                </td>
                <td className="py-3 px-4 font-mono text-xs" style={{ color: '#FFC66D' }}>
                  {run.cost != null ? `$${run.cost.toFixed(4)}` : '—'}
                </td>
                <td className="py-3 px-4 text-xs" style={{ color: '#808080' }}>
                  {formatDistanceToNow(run.started_at)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
