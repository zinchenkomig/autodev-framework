'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { getAgentMonitors, getAgentRuns, getAgentLogs, toggleAgent, type AgentMonitor, type AgentRun, type AgentLog, type AgentLogLevel } from '@/lib/api'
import { AgentRunsTable } from '@/components/agents/AgentRunsTable'
import { Loader2, ChevronDown, ChevronRight, RefreshCw, Power, PowerOff } from 'lucide-react'

// Agent order by importance
const AGENT_ORDER = ['developer', 'pm', 'project_manager', 'tester', 'release_manager']

function sortAgents(agents: AgentMonitor[]): AgentMonitor[] {
  return [...agents].sort((a, b) => {
    const aIdx = AGENT_ORDER.findIndex(r => a.role.toLowerCase().includes(r))
    const bIdx = AGENT_ORDER.findIndex(r => b.role.toLowerCase().includes(r))
    return (aIdx === -1 ? 999 : aIdx) - (bIdx === -1 ? 999 : bIdx)
  })
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

function LogRow({ log }: { log: AgentLog }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = levelConfig[log.level] ?? levelConfig.info

  return (
    <div style={{ borderBottom: '1px solid #3C3F41', fontFamily: 'monospace' }}>
      <div
        className="flex items-start gap-2 px-3 py-1.5 cursor-pointer hover:bg-[#3C3F41] transition-colors"
        onClick={() => log.details && setExpanded(e => !e)}
        style={{ fontSize: '12px' }}
      >
        <span style={{ color: '#515151', flexShrink: 0, marginTop: '2px', width: '12px' }}>
          {log.details ? (expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />) : null}
        </span>
        <span style={{ color: '#808080', flexShrink: 0, minWidth: '155px' }}>{formatTs(log.created_at)}</span>
        <span className="px-1 rounded text-xs font-bold" style={{ color: cfg.color, background: cfg.bg, flexShrink: 0, lineHeight: '18px' }}>{cfg.label}</span>
        <span style={{ color: '#BABABA', flex: 1, wordBreak: 'break-word' }}>{log.message}</span>
      </div>
      {expanded && log.details && (
        <div className="px-4 pb-3 pt-1" style={{ background: '#1E1F22', borderTop: '1px solid #3C3F41', fontFamily: 'monospace', fontSize: '11px', color: '#9E9E9E', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '400px', overflowY: 'auto' }}>
          {log.details}
        </div>
      )}
    </div>
  )
}

const statusColors: Record<string, { dot: string; text: string }> = {
  idle: { dot: '#6A8759', text: '#808080' },
  working: { dot: '#3592C4', text: '#3592C4' },
  failed: { dot: '#CC4E4E', text: '#CC4E4E' },
}

const roleIcons: Record<string, string> = {
  developer: '👨‍💻',
  pm: '📋',
  project_manager: '📋',
  tester: '🧪',
  release_manager: '🚀',
}

function AgentCard({ agent, selected, onClick, onToggle, toggling }: { agent: AgentMonitor; selected: boolean; onClick: () => void; onToggle: () => void; toggling?: boolean }) {
  const colors = statusColors[agent.status] || statusColors.idle
  const icon = Object.entries(roleIcons).find(([k]) => agent.role.toLowerCase().includes(k))?.[1] || '🤖'
  
  return (
    <div
      onClick={onClick}
      className="cursor-pointer transition-all"
      style={{
        background: selected ? '#3C3F41' : '#2B2B2B',
        border: `2px solid ${selected ? '#3592C4' : '#515151'}`,
        borderRadius: '6px',
        padding: '12px',
        opacity: agent.enabled ? 1 : 0.5,
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{icon}</span>
        <span className="font-medium text-white text-sm flex-1">{agent.role}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          disabled={toggling}
          className="p-1 rounded hover:bg-[#515151] transition-colors disabled:opacity-50"
          title={agent.enabled ? 'Disable agent' : 'Enable agent'}
        >
          {toggling ? (
            <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
          ) : agent.enabled ? (
            <Power className="w-4 h-4 text-green-500" />
          ) : (
            <PowerOff className="w-4 h-4 text-gray-500" />
          )}
        </button>
      </div>
      <div className="flex items-center gap-2">
        <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: colors.dot }} className={agent.status === 'working' ? 'animate-pulse' : ''} />
        <span style={{ color: colors.text, fontSize: '12px' }}>{agent.status}</span>
      </div>
      {agent.current_task_title && (
        <p className="mt-2 text-xs truncate" style={{ color: '#808080' }}>{agent.current_task_title}</p>
      )}
    </div>
  )
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentMonitor[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [logs, setLogs] = useState<AgentLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [levelFilter, setLevelFilter] = useState<AgentLogLevel | 'all'>('all')
  const [togglingAgent, setTogglingAgent] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = async () => {
    const [a, r] = await Promise.all([getAgentMonitors(), getAgentRuns()])
    const sorted = sortAgents(a)
    setAgents(sorted)
    setRuns(r)
    setLoading(false)
    // Auto-select first agent if none selected
    if (!selectedAgent && sorted.length > 0) {
      setSelectedAgent(sorted[0].id)
    }
  }

  const fetchLogs = useCallback(async () => {
    if (!selectedAgent) return
    setLogsLoading(true)
    try {
      const data = await getAgentLogs(selectedAgent, 100)
      setLogs(data)
    } finally {
      setLogsLoading(false)
    }
  }, [selectedAgent])

  useEffect(() => {
    fetchData()
  }, [])

  useEffect(() => {
    if (selectedAgent) fetchLogs()
  }, [selectedAgent, fetchLogs])

  // Auto-refresh
  const anyWorking = agents.some(a => a.status === 'working')
  const selectedIsWorking = agents.find(a => a.id === selectedAgent)?.status === 'working'
  
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (anyWorking || selectedIsWorking) {
      intervalRef.current = setInterval(() => {
        fetchData()
        if (selectedAgent) fetchLogs()
      }, 10_000)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [anyWorking, selectedIsWorking, selectedAgent])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  const filteredLogs = levelFilter === 'all' ? logs : logs.filter(l => l.level === levelFilter)

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">Agents</h1>
        <p className="text-xs text-gray-500">Click on agent to view logs</p>
      </div>

      {/* Agent Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {agents.map(agent => (
          <AgentCard
            key={agent.id}
            agent={agent}
            selected={agent.id === selectedAgent}
            onClick={() => setSelectedAgent(agent.id)}
            toggling={togglingAgent === agent.id}
            onToggle={async () => {
              setTogglingAgent(agent.id)
              try {
                await toggleAgent(agent.id)
                await fetchData()
              } catch (err) {
                console.error('Failed to toggle agent', err)
              } finally {
                setTogglingAgent(null)
              }
            }}
          />
        ))}
      </div>

      {/* Logs */}
      {selectedAgent && (
        <div style={{ background: '#2B2B2B', border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
          {/* Toolbar */}
          <div className="flex items-center gap-3 px-3 py-2 flex-wrap" style={{ borderBottom: '1px solid #515151', background: '#313335' }}>
            <span className="text-sm font-medium text-white">{agents.find(a => a.id === selectedAgent)?.role} Logs</span>
            
            {/* Level filter */}
            <div className="flex items-center gap-1 ml-4" style={{ fontSize: '12px' }}>
              {(['all', 'info', 'warning', 'error'] as const).map(lvl => (
                <button
                  key={lvl}
                  onClick={() => setLevelFilter(lvl)}
                  style={{
                    padding: '2px 8px', borderRadius: '3px', border: '1px solid',
                    borderColor: levelFilter === lvl ? '#808080' : '#3C3F41',
                    background: levelFilter === lvl ? '#3C3F41' : 'transparent',
                    color: lvl === 'all' ? '#BABABA' : lvl === 'info' ? '#9E9E9E' : lvl === 'warning' ? '#CC7832' : '#CC4E4E',
                    cursor: 'pointer', fontFamily: 'monospace', fontSize: '11px',
                  }}
                >
                  {lvl === 'all' ? 'all' : lvl === 'info' ? 'INFO' : lvl === 'warning' ? 'WARN' : 'ERR'}
                </button>
              ))}
            </div>

            {/* Refresh */}
            <div className="flex items-center gap-2 ml-auto">
              {selectedIsWorking && (
                <span className="flex items-center gap-1 text-xs" style={{ color: '#6A8759' }}>
                  <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', background: '#6A8759' }} className="animate-pulse" />
                  live
                </span>
              )}
              <button onClick={fetchLogs} disabled={logsLoading} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#808080', padding: '2px' }}>
                <RefreshCw className={`w-3.5 h-3.5 ${logsLoading ? 'animate-spin' : ''}`} />
              </button>
              <span style={{ color: '#515151', fontSize: '11px', fontFamily: 'monospace' }}>{filteredLogs.length}</span>
            </div>
          </div>

          {/* Log entries */}
          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
            {filteredLogs.length === 0 ? (
              <p className="py-8 text-center" style={{ color: '#515151', fontSize: '12px', fontFamily: 'monospace' }}>
                {logsLoading ? 'Loading…' : 'No logs'}
              </p>
            ) : (
              filteredLogs.map(log => <LogRow key={log.id} log={log} />)
            )}
          </div>
        </div>
      )}

      {/* Runs Table */}
      <div>
        <div className="text-sm font-medium text-white mb-2">Recent Runs</div>
        <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
          <AgentRunsTable runs={runs} />
        </div>
      </div>
    </div>
  )
}
