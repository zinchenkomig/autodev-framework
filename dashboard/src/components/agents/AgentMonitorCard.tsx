'use client'

import { type AgentMonitor, type AgentMonitorStatus } from '@/lib/api'
import { StatusIndicator } from './StatusIndicator'
import { formatDistanceToNow } from '@/lib/utils'
import {
  Bot,
  Code2,
  TestTube2,
  Briefcase,
  Package,
  Play,
  Square,
  Clock,
  BarChart2,
  CheckCircle2,
} from 'lucide-react'

const roleIcons: Record<string, React.ReactNode> = {
  'Product Manager': <Briefcase className="w-5 h-5" />,
  'Developer': <Code2 className="w-5 h-5" />,
  'Tester': <TestTube2 className="w-5 h-5" />,
  'Business Analyst': <BarChart2 className="w-5 h-5" />,
  'Release Manager': <Package className="w-5 h-5" />,
}

interface AgentMonitorCardProps {
  agent: AgentMonitor
}

export function AgentMonitorCard({ agent }: AgentMonitorCardProps) {
  const statusColorMap: Record<AgentMonitorStatus, string> = {
    idle: 'border-gray-700/50',
    working: 'border-green-500/30',
    failed: 'border-red-500/30',
  }

  const bgMap: Record<AgentMonitorStatus, string> = {
    idle: 'bg-gray-700',
    working: 'bg-green-500/10',
    failed: 'bg-red-500/10',
  }

  const iconColorMap: Record<AgentMonitorStatus, string> = {
    idle: 'text-gray-400',
    working: 'text-green-400',
    failed: 'text-red-400',
  }

  const statusLabelMap: Record<AgentMonitorStatus, string> = {
    idle: 'Idle',
    working: 'Working',
    failed: 'Failed',
  }

  const statusTextMap: Record<AgentMonitorStatus, string> = {
    idle: 'text-gray-400',
    working: 'text-green-400',
    failed: 'text-red-400',
  }

  const icon = roleIcons[agent.role] ?? <Bot className="w-5 h-5" />
  const successRate =
    agent.total_runs > 0
      ? Math.round(((agent.total_runs - agent.total_failures) / agent.total_runs) * 100)
      : 100

  return (
    <div
      className={`bg-gray-800/50 border ${statusColorMap[agent.status]} rounded-xl p-5 hover:border-gray-600 transition-all flex flex-col gap-4`}
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${bgMap[agent.status]}`}>
            <span className={iconColorMap[agent.status]}>{icon}</span>
          </div>
          <div>
            <h3 className="text-white font-semibold">{agent.role}</h3>
            <p className="text-gray-500 text-xs font-mono">{agent.id}</p>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 text-xs font-medium ${statusTextMap[agent.status]}`}>
          <StatusIndicator status={agent.status} size="sm" />
          {statusLabelMap[agent.status]}
        </div>
      </div>

      {/* Current task */}
      <div className="min-h-[40px]">
        {agent.current_task_title ? (
          <div className="bg-gray-900/50 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-400 mb-0.5">Current Task</p>
            <p className="text-sm text-gray-200 truncate">{agent.current_task_title}</p>
          </div>
        ) : (
          <div className="bg-gray-900/30 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-600 italic">No active task</p>
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-gray-900/40 rounded-lg p-2">
          <p className="text-xs text-gray-500 mb-0.5 flex items-center justify-center gap-1">
            <BarChart2 className="w-3 h-3" /> Runs
          </p>
          <p className="text-white font-semibold text-sm">{agent.total_runs}</p>
        </div>
        <div className="bg-gray-900/40 rounded-lg p-2">
          <p className="text-xs text-gray-500 mb-0.5 flex items-center justify-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> Success
          </p>
          <p className={`font-semibold text-sm ${successRate >= 80 ? 'text-green-400' : successRate >= 60 ? 'text-yellow-400' : 'text-red-400'}`}>
            {successRate}%
          </p>
        </div>
        <div className="bg-gray-900/40 rounded-lg p-2">
          <p className="text-xs text-gray-500 mb-0.5 flex items-center justify-center gap-1">
            <Clock className="w-3 h-3" /> Avg
          </p>
          <p className="text-white font-semibold text-sm">{agent.avg_time}</p>
        </div>
      </div>

      {/* Last run */}
      {agent.last_run_at && (
        <p className="text-xs text-gray-500">
          Last run: {formatDistanceToNow(agent.last_run_at)}
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-2 mt-auto">
        <button
          className="flex-1 flex items-center justify-center gap-1.5 bg-green-500/10 hover:bg-green-500/20 text-green-400 border border-green-500/30 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
        >
          <Play className="w-3 h-3" /> Trigger
        </button>
        <button
          className="flex-1 flex items-center justify-center gap-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          disabled={agent.status !== 'working'}
        >
          <Square className="w-3 h-3" /> Stop
        </button>
      </div>
    </div>
  )
}
