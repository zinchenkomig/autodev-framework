'use client'

import { useEffect, useState } from 'react'
import {
  getMetricsDashboard, getMetricsCost, getMetricsSpeed, getMetricsQuality,
  type MetricsDashboardStats, type CostSummary, type SpeedMetrics, type QualityMetrics,
} from '@/lib/metrics-api'
import { Loader2 } from 'lucide-react'

export default function MetricsPage() {
  const [dashboard, setDashboard] = useState<MetricsDashboardStats | null>(null)
  const [cost, setCost] = useState<CostSummary | null>(null)
  const [speed, setSpeed] = useState<SpeedMetrics | null>(null)
  const [quality, setQuality] = useState<QualityMetrics | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getMetricsDashboard(),
      getMetricsCost(30),
      getMetricsSpeed(30),
      getMetricsQuality(30),
    ]).then(([d, c, s, q]) => {
      setDashboard(d)
      setCost(c)
      setSpeed(s)
      setQuality(q)
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

  if (!cost || !speed || !quality) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Metrics &amp; Analytics</h1>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>Last 30 days</p>
        </div>
        <div
          className="p-12 text-center"
          style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
        >
          <p style={{ color: '#808080' }}>No metrics data. API unavailable.</p>
        </div>
      </div>
    )
  }

  const maxDailyCost = Math.max(...cost.cost_by_day.map(d => d.value), 0.001)

  const cardStyle = {
    background: '#3C3F41',
    border: '1px solid #515151',
    borderRadius: '4px',
    padding: '16px',
  }

  const sectionStyle = {
    background: '#3C3F41',
    border: '1px solid #515151',
    borderRadius: '4px',
    overflow: 'hidden' as const,
  }

  const headerStyle = {
    borderBottom: '1px solid #515151',
    padding: '12px 20px',
    background: '#313335',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Metrics &amp; Analytics</h1>
        <p className="text-xs mt-1" style={{ color: '#808080' }}>Last 30 days</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Total Cost (30d)</p>
          <p className="text-2xl font-bold" style={{ color: '#FFC66D' }}>${cost.total_cost_usd.toFixed(4)}</p>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>{cost.total_tokens.toLocaleString()} tokens</p>
        </div>
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Avg Cost / Task</p>
          <p className="text-2xl font-bold" style={{ color: '#3592C4' }}>${cost.avg_cost_per_task.toFixed(4)}</p>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>{cost.period_days}d window</p>
        </div>
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Success Rate</p>
          <p className="text-2xl font-bold" style={{ color: '#6A8759' }}>
            {(quality.agent_success_rate * 100).toFixed(1)}%
          </p>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>{quality.total_runs} runs total</p>
        </div>
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Throughput</p>
          <p className="text-2xl font-bold" style={{ color: '#9876AA' }}>
            {speed.throughput_tasks_per_day.toFixed(2)}
          </p>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>tasks / day</p>
        </div>
      </div>

      {/* Cost chart */}
      <div style={sectionStyle}>
        <div style={headerStyle}>
          <h3 className="text-sm font-semibold" style={{ color: '#FFC66D' }}>Daily Cost (USD)</h3>
        </div>
        <div className="p-5">
          {cost.cost_by_day.length === 0 ? (
            <p className="text-sm text-center py-8" style={{ color: '#808080' }}>No cost data for this period.</p>
          ) : (
            <div className="flex items-end gap-1 h-40">
              {cost.cost_by_day.map((d) => {
                const heightPct = (d.value / maxDailyCost) * 100
                return (
                  <div
                    key={d.date}
                    className="flex-1 flex flex-col items-center gap-1 group"
                    title={`${d.date}: $${d.value.toFixed(4)}`}
                  >
                    <div
                      className="w-full rounded-t-sm transition-all"
                      style={{
                        height: `${Math.max(heightPct, 2)}%`,
                        background: '#3592C4',
                      }}
                      onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.background = '#4da8e0'}
                      onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.background = '#3592C4'}
                    />
                    <span className="text-[9px] rotate-45 origin-left hidden sm:block truncate w-8" style={{ color: '#515151' }}>
                      {d.date.slice(5)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Speed metrics table */}
      <div style={sectionStyle}>
        <div style={headerStyle}>
          <h3 className="text-sm font-semibold" style={{ color: '#FFC66D' }}>Speed Metrics</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid #515151', background: '#2B2B2B' }}>
                <th className="text-left px-5 py-3 text-xs font-medium uppercase tracking-wide" style={{ color: '#808080' }}>Metric</th>
                <th className="text-right px-5 py-3 text-xs font-medium uppercase tracking-wide" style={{ color: '#808080' }}>Value</th>
              </tr>
            </thead>
            <tbody>
              {[
                { label: 'Avg Issue → PR',  value: `${speed.avg_issue_to_pr_hours.toFixed(1)} hrs` },
                { label: 'Avg PR → Merge',  value: `${speed.avg_pr_to_merge_hours.toFixed(1)} hrs` },
                { label: 'Tasks Completed', value: speed.tasks_completed },
                { label: 'Throughput',      value: `${speed.throughput_tasks_per_day.toFixed(2)} tasks/day` },
              ].map((row, i, arr) => (
                <tr
                  key={row.label}
                  style={{
                    borderBottom: i < arr.length - 1 ? '1px solid #414345' : 'none',
                    background: i % 2 === 0 ? '#3C3F41' : '#313335',
                  }}
                >
                  <td className="px-5 py-3" style={{ color: '#BABABA' }}>{row.label}</td>
                  <td className="px-5 py-3 text-right font-mono" style={{ color: '#FFFFFF' }}>{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Agent success rates */}
      <div style={sectionStyle}>
        <div style={headerStyle}>
          <h3 className="text-sm font-semibold" style={{ color: '#FFC66D' }}>Agent Success Rates</h3>
        </div>
        <div className="p-5 space-y-4">
          {Object.keys(quality.success_rate_by_agent).length === 0 ? (
            <p className="text-sm text-center py-4" style={{ color: '#808080' }}>No agent data for this period.</p>
          ) : (
            Object.entries(quality.success_rate_by_agent).map(([agentId, rate]) => {
              const pct = Math.round(rate * 100)
              const barColor = pct >= 80 ? '#6A8759' : pct >= 50 ? '#CC7832' : '#CC4E4E'
              return (
                <div key={agentId}>
                  <div className="flex justify-between mb-1.5">
                    <span className="text-sm" style={{ color: '#BABABA' }}>{agentId}</span>
                    <span className="text-sm font-medium font-mono" style={{ color: barColor }}>{pct}%</span>
                  </div>
                  <div className="w-full h-2 rounded-full" style={{ background: '#2B2B2B' }}>
                    <div
                      className="h-2 rounded-full transition-all"
                      style={{ width: `${pct}%`, background: barColor }}
                    />
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Quality summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Bugs Found (Tester)</p>
          <p className="text-2xl font-bold" style={{ color: '#CC4E4E' }}>{quality.bugs_found_by_tester}</p>
        </div>
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Code Churn</p>
          <p className="text-2xl font-bold" style={{ color: '#CC7832' }}>{quality.code_churn}</p>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>tasks re-run &gt;1×</p>
        </div>
        <div style={cardStyle}>
          <p className="text-xs uppercase tracking-wide mb-2" style={{ color: '#808080' }}>Failed Runs</p>
          <p className="text-2xl font-bold" style={{ color: '#CC7832' }}>{quality.failed_runs}</p>
          <p className="text-xs mt-1" style={{ color: '#808080' }}>of {quality.total_runs} total</p>
        </div>
      </div>

      {/* Cost by agent */}
      {Object.keys(cost.cost_by_agent).length > 0 && (
        <div style={sectionStyle}>
          <div style={headerStyle}>
            <h3 className="text-sm font-semibold" style={{ color: '#FFC66D' }}>Cost by Agent</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid #515151', background: '#2B2B2B' }}>
                  <th className="text-left px-5 py-3 text-xs font-medium uppercase tracking-wide" style={{ color: '#808080' }}>Agent</th>
                  <th className="text-right px-5 py-3 text-xs font-medium uppercase tracking-wide" style={{ color: '#808080' }}>Cost (USD)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(cost.cost_by_agent)
                  .sort(([, a], [, b]) => b - a)
                  .map(([agentId, agentCost], i, arr) => (
                    <tr
                      key={agentId}
                      style={{
                        borderBottom: i < arr.length - 1 ? '1px solid #414345' : 'none',
                        background: i % 2 === 0 ? '#3C3F41' : '#313335',
                      }}
                    >
                      <td className="px-5 py-3" style={{ color: '#BABABA' }}>{agentId}</td>
                      <td className="px-5 py-3 text-right font-mono" style={{ color: '#FFC66D' }}>${(agentCost as number).toFixed(4)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
