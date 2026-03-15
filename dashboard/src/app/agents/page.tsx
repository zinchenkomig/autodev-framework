import { getAgentMonitors, getAgentRuns } from '@/lib/api'
import { AgentMonitorCard } from '@/components/agents/AgentMonitorCard'
import { AgentRunsTable } from '@/components/agents/AgentRunsTable'
import { Activity } from 'lucide-react'

export default async function AgentsPage() {
  const [agents, runs] = await Promise.all([getAgentMonitors(), getAgentRuns()])

  const working = agents.filter((a) => a.status === 'working').length
  const failed = agents.filter((a) => a.status === 'failed').length

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Agent Monitor</h2>
          <p className="text-gray-400 text-sm mt-1">
            Real-time status of all AI agents in the system
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
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

      {/* Agent Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        {agents.map((agent) => (
          <AgentMonitorCard key={agent.id} agent={agent} />
        ))}
      </div>

      {/* Agent Runs Table */}
      <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-white font-semibold text-lg">Agent Runs</h3>
            <p className="text-gray-500 text-sm">Recent execution history across all agents</p>
          </div>
          <span className="text-xs text-gray-600 bg-gray-700/40 px-2 py-1 rounded-full">
            {runs.length} records
          </span>
        </div>
        <AgentRunsTable runs={runs} />
      </div>
    </div>
  )
}
