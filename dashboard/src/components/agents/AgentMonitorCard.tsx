'use client'

import { type AgentMonitor, type AgentMonitorStatus } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { Play, Square } from 'lucide-react'

interface AgentMonitorCardProps {
  agent: AgentMonitor
}

const statusDot: Record<AgentMonitorStatus, string> = {
  idle:    'text-[#3F3F46]',
  working: 'text-[#22C55E]',
  failed:  'text-[#EF4444]',
}

export function AgentMonitorCard({ agent }: AgentMonitorCardProps) {
  const dot = statusDot[agent.status]
  const successRate =
    agent.total_runs > 0
      ? Math.round(((agent.total_runs - agent.total_failures) / agent.total_runs) * 100)
      : 100

  return (
    <div className="border border-[#1F1F23] p-4 hover:border-[#3F3F46] transition-colors flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`text-xs ${dot}`}>●</span>
          <span className="text-sm text-[#FAFAFA]">{agent.role}</span>
        </div>
        <span className="text-xs text-[#3F3F46] font-mono">{agent.status}</span>
      </div>

      <p className="text-xs text-[#3F3F46] font-mono">{agent.id}</p>

      {/* Current task */}
      {agent.current_task_title ? (
        <p className="text-xs text-[#71717A] truncate border-l-2 border-[#1F1F23] pl-2">
          {agent.current_task_title}
        </p>
      ) : (
        <p className="text-xs text-[#3F3F46] border-l-2 border-[#1F1F23] pl-2">idle</p>
      )}

      {/* Stats */}
      <div className="flex items-center gap-4 text-xs">
        <span className="text-[#3F3F46]">
          <span className="font-mono text-[#71717A]">{agent.total_runs}</span> runs
        </span>
        <span className="text-[#3F3F46]">
          <span className={`font-mono ${successRate >= 80 ? 'text-[#22C55E]' : 'text-[#EF4444]'}`}>{successRate}%</span>
        </span>
        <span className="text-[#3F3F46]">{agent.avg_time}</span>
      </div>

      {agent.last_run_at && (
        <p className="text-xs text-[#3F3F46]">
          {formatDistanceToNow(agent.last_run_at)} ago
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button className="flex-1 flex items-center justify-center gap-1 border border-[#1F1F23] text-[#71717A] hover:text-[#22C55E] hover:border-[#22C55E]/30 px-2 py-1.5 text-xs transition-colors">
          <Play className="w-3 h-3" /> Trigger
        </button>
        <button
          className="flex-1 flex items-center justify-center gap-1 border border-[#1F1F23] text-[#71717A] hover:text-[#EF4444] hover:border-[#EF4444]/30 px-2 py-1.5 text-xs transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          disabled={agent.status !== 'working'}
        >
          <Square className="w-3 h-3" /> Stop
        </button>
      </div>
    </div>
  )
}
