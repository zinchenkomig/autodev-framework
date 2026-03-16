'use client'

import { type AgentMonitor, type AgentMonitorStatus } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { Play, Square } from 'lucide-react'

interface AgentMonitorCardProps {
  agent: AgentMonitor
}

const statusConfig: Record<AgentMonitorStatus, { color: string; label: string; pulse: boolean }> = {
  idle:    { color: '#808080', label: 'idle',    pulse: false },
  working: { color: '#6A8759', label: 'working', pulse: true  },
  failed:  { color: '#CC4E4E', label: 'failed',  pulse: false },
}

export function AgentMonitorCard({ agent }: AgentMonitorCardProps) {
  const cfg = statusConfig[agent.status]
  const successRate =
    agent.total_runs > 0
      ? Math.round(((agent.total_runs - agent.total_failures) / agent.total_runs) * 100)
      : 100

  const successColor = successRate >= 80 ? '#6A8759' : successRate >= 50 ? '#CC7832' : '#CC4E4E'

  return (
    <div
      className="flex flex-col gap-3 transition-all"
      style={{
        background: '#3C3F41',
        border: '1px solid #515151',
        borderRadius: '4px',
        padding: '14px',
      }}
      onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.borderColor = '#808080'}
      onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.borderColor = '#515151'}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cfg.pulse ? 'animate-status-pulse' : ''}
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: cfg.color,
              flexShrink: 0,
            }}
          />
          <span className="text-sm font-semibold" style={{ color: '#FFFFFF' }}>{agent.role}</span>
        </div>
        <span
          className="text-xs font-mono px-1.5 py-0.5 rounded"
          style={{ color: cfg.color, background: `${cfg.color}20` }}
        >
          {cfg.label}
        </span>
      </div>

      <p className="text-xs font-mono" style={{ color: '#808080' }}>{agent.id}</p>

      {/* Current task */}
      <div
        style={{
          background: '#313335',
          borderLeft: `3px solid ${cfg.color}`,
          padding: '6px 10px',
          borderRadius: '0 4px 4px 0',
        }}
      >
        {agent.current_task_title ? (
          <p className="text-xs truncate" style={{ color: '#BABABA' }}>{agent.current_task_title}</p>
        ) : (
          <p className="text-xs" style={{ color: '#515151' }}>no active task</p>
        )}
      </div>

      {/* Stats grid */}
      <div
        className="grid grid-cols-3 gap-2"
        style={{
          background: '#313335',
          borderRadius: '4px',
          padding: '8px',
        }}
      >
        <div className="text-center">
          <p className="text-xs font-mono font-bold" style={{ color: '#BABABA' }}>{agent.total_runs}</p>
          <p className="text-xs" style={{ color: '#808080' }}>runs</p>
        </div>
        <div className="text-center">
          <p className="text-xs font-mono font-bold" style={{ color: successColor }}>{successRate}%</p>
          <p className="text-xs" style={{ color: '#808080' }}>success</p>
        </div>
        <div className="text-center">
          <p className="text-xs font-mono font-bold" style={{ color: '#BABABA' }}>{agent.avg_time}</p>
          <p className="text-xs" style={{ color: '#808080' }}>avg</p>
        </div>
      </div>

      {agent.last_run_at && (
        <p className="text-xs" style={{ color: '#808080' }}>
          last run: {formatDistanceToNow(agent.last_run_at)} ago
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs transition-colors"
          style={{
            border: '1px solid #515151',
            color: '#BABABA',
            borderRadius: '3px',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#6A8759'
            ;(e.currentTarget as HTMLButtonElement).style.borderColor = '#6A8759'
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#BABABA'
            ;(e.currentTarget as HTMLButtonElement).style.borderColor = '#515151'
          }}
        >
          <Play className="w-3 h-3" /> Trigger
        </button>
        <button
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          style={{
            border: '1px solid #515151',
            color: '#BABABA',
            borderRadius: '3px',
          }}
          disabled={agent.status !== 'working'}
          onMouseEnter={e => {
            if (agent.status === 'working') {
              (e.currentTarget as HTMLButtonElement).style.color = '#CC4E4E'
              ;(e.currentTarget as HTMLButtonElement).style.borderColor = '#CC4E4E'
            }
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.color = '#BABABA'
            ;(e.currentTarget as HTMLButtonElement).style.borderColor = '#515151'
          }}
        >
          <Square className="w-3 h-3" /> Stop
        </button>
      </div>
    </div>
  )
}
