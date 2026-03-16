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
        <Loader2 className="w-4 h-4 text-[#3F3F46] animate-spin" />
      </div>
    )
  }

  const working = agents.filter((a) => a.status === 'working').length
  const failed = agents.filter((a) => a.status === 'failed').length

  return (
    <div className="space-y-10 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-[#FAFAFA]">Agents</h1>
          <p className="text-xs text-[#71717A] mt-0.5">Real-time status</p>
        </div>
        <div className="flex items-center gap-4 text-xs text-[#71717A]">
          <span>
            <span className="text-[#22C55E] font-mono">{working}</span> working
          </span>
          {failed > 0 && (
            <span>
              <span className="text-[#EF4444] font-mono">{failed}</span> failed
            </span>
          )}
          <span className="text-[#3F3F46]">{agents.length} total</span>
        </div>
      </div>

      {/* Agent Cards */}
      {agents.length === 0 ? (
        <p className="text-xs text-[#3F3F46] py-8">No agents</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {agents.map((agent) => (
            <AgentMonitorCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}

      {/* Runs Table */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs text-[#71717A] uppercase tracking-wider">Agent Runs</p>
          <span className="text-xs text-[#3F3F46] font-mono">{runs.length} records</span>
        </div>
        <div className="border border-[#1F1F23] overflow-x-auto">
          <AgentRunsTable runs={runs} />
        </div>
      </div>
    </div>
  )
}
