'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { getAgentLogs, type AgentLog, type AgentLogLevel, type AgentMonitor } from '@/lib/api'

interface AgentLogsViewerProps {
  agents: AgentMonitor[]
}

const levelConfig: Record<AgentLogLevel, { color: string; bg: string; label: string }> = {
  info:    { color: '#9E9E9E', bg: '#9E9E9E22', label: 'INFO' },
  warning: { color: '#CC7832', bg: '#CC783222', label: 'WARN' },
  error:   { color: '#CC4E4E', bg: '#CC4E4E22', label: 'ERR ' },
}

function formatTs(iso: string) {
  const d = new Date(iso)
  return d.toISOString().replace('T', ' ').slice(0, 19)
}

interface LogRowProps {
  log: AgentLog
}

function LogRow({ log }: LogRowProps) {
  const [expanded, setExpanded] = useState(false)
  const cfg = levelConfig[log.level] ?? levelConfig.info

  return (
    <div
      style={{ borderBottom: '1px solid #3C3F41', fontFamily: 'monospace' }}
    >
      <div
        className="flex items-start gap-2 px-3 py-1.5 cursor-pointer hover:bg-[#3C3F41] transition-colors"
        onClick={() => log.details && setExpanded(e => !e)}
        style={{ fontSize: '12px' }}
      >
        {/* expand toggle */}
        <span style={{ color: '#515151', flexShrink: 0, marginTop: '2px', width: '12px' }}>
          {log.details
            ? (expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />)
            : null
          }
        </span>

        {/* timestamp */}
        <span style={{ color: '#808080', flexShrink: 0, minWidth: '155px' }}>
          {formatTs(log.created_at)}
        </span>

        {/* level badge */}
        <span
          className="px-1 rounded text-xs font-bold"
          style={{ color: cfg.color, background: cfg.bg, flexShrink: 0, lineHeight: '18px' }}
        >
          {cfg.label}
        </span>

        {/* message */}
        <span style={{ color: '#BABABA', flex: 1, wordBreak: 'break-word' }}>
          {log.message}
        </span>
      </div>

      {/* details panel */}
      {expanded && log.details && (
        <div
          className="px-4 pb-3 pt-1"
          style={{
            background: '#1E1F22',
            borderTop: '1px solid #3C3F41',
            fontFamily: 'monospace',
            fontSize: '11px',
            color: '#9E9E9E',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: '400px',
            overflowY: 'auto',
          }}
        >
          {log.details}
        </div>
      )}
    </div>
  )
}

export function AgentLogsViewer({ agents }: AgentLogsViewerProps) {
  const [selectedAgent, setSelectedAgent] = useState<string>(agents[0]?.id ?? '')
  const [logs, setLogs] = useState<AgentLog[]>([])
  const [levelFilter, setLevelFilter] = useState<AgentLogLevel | 'all'>('all')
  const [loading, setLoading] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const currentAgent = agents.find(a => a.id === selectedAgent)
  const isWorking = currentAgent?.status === 'working'

  const fetchLogs = useCallback(async () => {
    if (!selectedAgent) return
    setLoading(true)
    try {
      const data = await getAgentLogs(selectedAgent, 100)
      setLogs(data)
    } finally {
      setLoading(false)
    }
  }, [selectedAgent])

  // Initial + agent change fetch
  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  // Auto-refresh every 10s when working
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (isWorking) {
      intervalRef.current = setInterval(fetchLogs, 10_000)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [isWorking, fetchLogs])

  const filteredLogs = levelFilter === 'all'
    ? logs
    : logs.filter(l => l.level === levelFilter)

  return (
    <div
      style={{
        background: '#2B2B2B',
        border: '1px solid #515151',
        borderRadius: '4px',
        overflow: 'hidden',
      }}
    >
      {/* Toolbar */}
      <div
        className="flex items-center gap-3 px-3 py-2 flex-wrap"
        style={{ borderBottom: '1px solid #515151', background: '#313335' }}
      >
        {/* Agent selector */}
        <select
          value={selectedAgent}
          onChange={e => setSelectedAgent(e.target.value)}
          style={{
            background: '#3C3F41',
            border: '1px solid #515151',
            color: '#BABABA',
            borderRadius: '3px',
            padding: '2px 6px',
            fontSize: '12px',
            fontFamily: 'monospace',
          }}
        >
          {agents.map(a => (
            <option key={a.id} value={a.id}>{a.role}</option>
          ))}
        </select>

        {/* Level filter */}
        <div className="flex items-center gap-1" style={{ fontSize: '12px' }}>
          {(['all', 'info', 'warning', 'error'] as const).map(lvl => (
            <button
              key={lvl}
              onClick={() => setLevelFilter(lvl)}
              style={{
                padding: '2px 8px',
                borderRadius: '3px',
                border: '1px solid',
                borderColor: levelFilter === lvl ? '#808080' : '#3C3F41',
                background: levelFilter === lvl ? '#3C3F41' : 'transparent',
                color: lvl === 'all' ? '#BABABA'
                  : lvl === 'info' ? '#9E9E9E'
                  : lvl === 'warning' ? '#CC7832'
                  : '#CC4E4E',
                cursor: 'pointer',
                fontFamily: 'monospace',
                fontSize: '11px',
              }}
            >
              {lvl === 'all' ? 'all' : lvl === 'info' ? 'INFO' : lvl === 'warning' ? 'WARN' : 'ERR'}
            </button>
          ))}
        </div>

        {/* Status + refresh */}
        <div className="flex items-center gap-2 ml-auto">
          {isWorking && (
            <span className="flex items-center gap-1 text-xs" style={{ color: '#6A8759' }}>
              <span
                style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', background: '#6A8759' }}
                className="animate-status-pulse"
              />
              live
            </span>
          )}
          <button
            onClick={fetchLogs}
            disabled={loading}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer',
              color: '#808080',
              padding: '2px',
            }}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <span style={{ color: '#515151', fontSize: '11px', fontFamily: 'monospace' }}>
            {filteredLogs.length} entries
          </span>
        </div>
      </div>

      {/* Log entries */}
      <div style={{ maxHeight: '480px', overflowY: 'auto' }}>
        {filteredLogs.length === 0 ? (
          <p
            className="py-8 text-center"
            style={{ color: '#515151', fontSize: '12px', fontFamily: 'monospace' }}
          >
            {loading ? 'Loading…' : 'No logs found'}
          </p>
        ) : (
          filteredLogs.map(log => <LogRow key={log.id} log={log} />)
        )}
      </div>
    </div>
  )
}
