'use client'

import { useEffect, useState } from 'react'
import { getAlerts, getAlertStats, resolveAlert, deleteAlert, type Alert, type AlertStats } from '@/lib/api'
import { Loader2, AlertTriangle, CheckCircle, Trash2, RefreshCw, Bell, BellOff } from 'lucide-react'
import { formatDistanceToNow } from '@/lib/utils'

const severityConfig = {
  critical: { color: '#CC4E4E', bg: '#CC4E4E22', icon: '🚨', label: 'Critical' },
  high: { color: '#CC7832', bg: '#CC783222', icon: '🔴', label: 'High' },
  medium: { color: '#E5C07B', bg: '#E5C07B22', icon: '🟡', label: 'Medium' },
  low: { color: '#6A8759', bg: '#6A875922', icon: '🟢', label: 'Low' },
}

const typeLabels: Record<string, string> = {
  task_failed: '❌ Task Failed',
  api_error: '🔴 API Error',
  task_stuck: '⏱️ Task Stuck',
  agent_stuck: '🔒 Agent Stuck',
  orchestrator_error: '💀 Orchestrator Error',
  custom: '⚠️ Custom',
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [stats, setStats] = useState<AlertStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'unresolved'>('unresolved')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  async function loadData() {
    setLoading(true)
    const [a, s] = await Promise.all([
      getAlerts(filter === 'unresolved'),
      getAlertStats()
    ])
    setAlerts(a)
    setStats(s)
    setLoading(false)
  }

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 30000)
    return () => clearInterval(interval)
  }, [filter])

  async function handleResolve(id: string) {
    await resolveAlert(id)
    loadData()
  }

  async function handleDelete(id: string) {
    await deleteAlert(id)
    loadData()
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Alerts</h1>
          <p className="text-xs text-gray-500">System monitoring and incident tracking</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="p-2 rounded hover:bg-[#3C3F41]"
          style={{ color: '#808080' }}
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          <div className="p-3 rounded" style={{ background: '#2B2B2B', border: '1px solid #515151' }}>
            <p className="text-2xl font-bold text-white">{stats.unresolved}</p>
            <p className="text-xs text-gray-500">Unresolved</p>
          </div>
          <div className="p-3 rounded" style={{ background: '#2B2B2B', border: '1px solid #CC4E4E44' }}>
            <p className="text-2xl font-bold" style={{ color: '#CC4E4E' }}>{stats.critical}</p>
            <p className="text-xs text-gray-500">Critical</p>
          </div>
          <div className="p-3 rounded" style={{ background: '#2B2B2B', border: '1px solid #CC783244' }}>
            <p className="text-2xl font-bold" style={{ color: '#CC7832' }}>{stats.high}</p>
            <p className="text-xs text-gray-500">High</p>
          </div>
          <div className="p-3 rounded" style={{ background: '#2B2B2B', border: '1px solid #515151' }}>
            <p className="text-2xl font-bold text-white">{stats.total}</p>
            <p className="text-xs text-gray-500">Total</p>
          </div>
        </div>
      )}

      {/* Filter */}
      <div className="flex gap-2">
        {(['unresolved', 'all'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className="px-3 py-1 rounded text-xs font-medium"
            style={{
              background: filter === f ? '#3592C4' : '#3C3F41',
              color: filter === f ? '#FFF' : '#808080'
            }}
          >
            {f === 'unresolved' ? 'Unresolved' : 'All'}
          </button>
        ))}
      </div>

      {/* Alerts list */}
      <div className="space-y-2">
        {loading && alerts.length === 0 ? (
          <div className="flex justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
          </div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <BellOff className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No alerts</p>
          </div>
        ) : (
          alerts.map(alert => {
            const cfg = severityConfig[alert.severity] || severityConfig.medium
            const expanded = expandedId === alert.id
            return (
              <div
                key={alert.id}
                className="rounded overflow-hidden"
                style={{ 
                  background: '#2B2B2B', 
                  border: `1px solid ${alert.resolved ? '#515151' : cfg.color}44`,
                  opacity: alert.resolved ? 0.6 : 1
                }}
              >
                <div
                  className="flex items-center gap-3 p-3 cursor-pointer"
                  onClick={() => setExpandedId(expanded ? null : alert.id)}
                >
                  <span className="text-lg">{cfg.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: cfg.bg, color: cfg.color }}>
                        {cfg.label}
                      </span>
                      <span className="text-xs text-gray-500">
                        {typeLabels[alert.type] || alert.type}
                      </span>
                    </div>
                    <p className="text-sm text-white mt-1 truncate">{alert.title}</p>
                    <p className="text-xs text-gray-500">{formatDistanceToNow(alert.created_at)}</p>
                  </div>
                  {alert.resolved ? (
                    <span className="flex items-center gap-1 text-xs" style={{ color: '#6A8759' }}>
                      <CheckCircle className="w-3 h-3" /> Resolved
                    </span>
                  ) : (
                    <div className="flex gap-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleResolve(alert.id) }}
                        className="p-1.5 rounded hover:bg-[#515151]"
                        title="Resolve"
                      >
                        <CheckCircle className="w-4 h-4" style={{ color: '#6A8759' }} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(alert.id) }}
                        className="p-1.5 rounded hover:bg-[#515151]"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" style={{ color: '#CC4E4E' }} />
                      </button>
                    </div>
                  )}
                </div>
                {expanded && alert.message && (
                  <div className="px-3 pb-3 pt-1" style={{ borderTop: '1px solid #515151' }}>
                    <pre className="text-xs whitespace-pre-wrap overflow-x-auto p-2 rounded" style={{ background: '#1E1F22', color: '#9E9E9E' }}>
                      {alert.message}
                    </pre>
                    {alert.source && (
                      <p className="text-xs mt-2 text-gray-500">Source: {alert.source}</p>
                    )}
                    {alert.resolved_by && (
                      <p className="text-xs mt-1 text-gray-500">
                        Resolved by {alert.resolved_by} {alert.resolved_at && formatDistanceToNow(alert.resolved_at)}
                      </p>
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
