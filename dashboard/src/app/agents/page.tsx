'use client'

import { useEffect, useState } from 'react'
import { getAgentMonitors, getAgentRuns, type AgentMonitor, type AgentRun } from '@/lib/api'
import { AgentMonitorCard } from '@/components/agents/AgentMonitorCard'
import { AgentRunsTable } from '@/components/agents/AgentRunsTable'
import { Loader2 } from 'lucide-react'

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentMonitor[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getAgentMonitors(), getAgentRuns()]).then(([a, r]) => {
      setAgents(a)
      setRuns(r)
      setLoading(false)
    })
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  const working = agents.filter((a) => a.status === 'working').length
  const failed = agents.filter((a) => a.status === 'failed').length

  return (
    <div className="space-y-8 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Agents</h1>
          <p className="text-xs mt-0.5" style={{ color: '#808080' }}>Real-time status</p>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span className="flex items-center gap-1.5">
            <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#6A8759' }} className="animate-status-pulse" />
            <span style={{ color: '#6A8759' }} className="font-mono font-bold">{working}</span>
            <span style={{ color: '#808080' }}>working</span>
          </span>
          {failed > 0 && (
            <span className="flex items-center gap-1.5">
              <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#CC4E4E' }} />
              <span style={{ color: '#CC4E4E' }} className="font-mono font-bold">{failed}</span>
              <span style={{ color: '#808080' }}>failed</span>
            </span>
          )}
          <span style={{ color: '#808080' }} className="font-mono">{agents.length} total</span>
        </div>
      </div>

      {/* Agent Cards */}
      {agents.length === 0 ? (
        <p className="text-xs py-8" style={{ color: '#808080' }}>No agents</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {agents.map((agent) => (
            <AgentMonitorCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}

      {/* Runs Table */}
      <div>
        <div className="section-heading">Agent Runs</div>
        <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
          <AgentRunsTable runs={runs} />
        </div>
      </div>
    </div>
  )
}
