'use client'

import { useEffect, useState } from 'react'
import { getAgentMonitors, getAgentRuns, type AgentMonitor, type AgentRun } from '@/lib/api'
import { AgentMonitorCard } from '@/components/agents/AgentMonitorCard'
import { AgentRunsTable } from '@/components/agents/AgentRunsTable'
import { Activity, Loader2 } from 'lucide-react'

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
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  const working = agents.filter((a) => a.status === 'working').length
  const failed = agents.filter((a) => a.status === 'failed').length

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-white">Agent Monitor</h2>
          <p className="text-gray-400 text-sm mt-1">
            Real-time status of all AI agents in the system
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm flex-wrap">
          <span className="flex items-center gap-1.5 text-green-400">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-green-400" />
            </span>
            {working} working
          </span>
          {failed > 0 && (
            <span className="flex items-center gap-1.5 text-red-400">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              {failed} failed
            </span>
          )}
          <span className="flex items-center gap-1.5 text-gray-500">
            <Activity className="w-3.5 h-3.5" />
            {agents.length} total agents
          </span>
        </div>
      </div>

      {/* Agent Cards Grid – 1 col on mobile, 2 on sm, 3 on lg, 5 on xl */}
      {agents.length === 0 ? (
        <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl p-12 text-center">
          <p className="text-gray-500 text-sm">Нет агентов</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {agents.map((agent) => (
            <AgentMonitorCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}

      {/* Agent Runs Table */}
      <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl p-4 md:p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-white font-semibold text-lg">Agent Runs</h3>
            <p className="text-gray-500 text-sm">Recent execution history across all agents</p>
          </div>
          <span className="text-xs text-gray-600 bg-gray-700/40 px-2 py-1 rounded-full">
            {runs.length} records
          </span>
        </div>
        {/* horizontal scroll on mobile */}
        <div className="overflow-x-auto">
          <AgentRunsTable runs={runs} />
        </div>
      </div>
    </div>
  )
}
