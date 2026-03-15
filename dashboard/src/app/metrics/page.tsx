import { getMetricsDashboard, getMetricsCost, getMetricsSpeed, getMetricsQuality } from '@/lib/metrics-api'

export default async function MetricsPage() {
  const [dashboard, cost, speed, quality] = await Promise.all([
    getMetricsDashboard(),
    getMetricsCost(30),
    getMetricsSpeed(30),
    getMetricsQuality(30),
  ])

  const maxDailyCost = Math.max(...(cost.cost_by_day.map(d => d.value)), 0.001)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-white">Metrics &amp; Analytics</h2>
        <p className="text-gray-400 text-sm mt-1">Last 30 days</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Total Cost (30d)</p>
          <p className="text-white text-2xl font-bold mt-1">${cost.total_cost_usd.toFixed(4)}</p>
          <p className="text-gray-500 text-xs mt-1">{cost.total_tokens.toLocaleString()} tokens</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Avg Cost / Task</p>
          <p className="text-white text-2xl font-bold mt-1">${cost.avg_cost_per_task.toFixed(4)}</p>
          <p className="text-gray-500 text-xs mt-1">{cost.period_days}d window</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Success Rate</p>
          <p className="text-white text-2xl font-bold mt-1">
            {(quality.agent_success_rate * 100).toFixed(1)}%
          </p>
          <p className="text-gray-500 text-xs mt-1">{quality.total_runs} runs total</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Throughput</p>
          <p className="text-white text-2xl font-bold mt-1">
            {speed.throughput_tasks_per_day.toFixed(2)}
          </p>
          <p className="text-gray-500 text-xs mt-1">tasks / day</p>
        </div>
      </div>

      {/* Cost chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800">
          <h3 className="text-white font-semibold">Daily Cost (USD)</h3>
        </div>
        <div className="p-5">
          {cost.cost_by_day.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-8">No cost data for this period.</p>
          ) : (
            <div className="flex items-end gap-1 h-32">
              {cost.cost_by_day.map((d) => {
                const heightPct = (d.value / maxDailyCost) * 100
                return (
                  <div
                    key={d.date}
                    className="flex-1 flex flex-col items-center gap-1 group"
                    title={`${d.date}: $${d.value.toFixed(4)}`}
                  >
                    <div
                      className="w-full bg-indigo-500 group-hover:bg-indigo-400 rounded-t transition-all"
                      style={{ height: `${Math.max(heightPct, 2)}%` }}
                    />
                    <span className="text-gray-600 text-[9px] rotate-45 origin-left hidden sm:block truncate w-8">
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
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800">
          <h3 className="text-white font-semibold">Speed Metrics</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-5 py-3 text-gray-400 font-medium">Metric</th>
                <th className="text-right px-5 py-3 text-gray-400 font-medium">Value</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-gray-800/50">
                <td className="px-5 py-3 text-gray-300">Avg Issue → PR</td>
                <td className="px-5 py-3 text-white text-right">
                  {speed.avg_issue_to_pr_hours.toFixed(1)} hrs
                </td>
              </tr>
              <tr className="border-b border-gray-800/50">
                <td className="px-5 py-3 text-gray-300">Avg PR → Merge</td>
                <td className="px-5 py-3 text-white text-right">
                  {speed.avg_pr_to_merge_hours.toFixed(1)} hrs
                </td>
              </tr>
              <tr className="border-b border-gray-800/50">
                <td className="px-5 py-3 text-gray-300">Tasks Completed</td>
                <td className="px-5 py-3 text-white text-right">{speed.tasks_completed}</td>
              </tr>
              <tr>
                <td className="px-5 py-3 text-gray-300">Throughput</td>
                <td className="px-5 py-3 text-white text-right">
                  {speed.throughput_tasks_per_day.toFixed(2)} tasks/day
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Agent success rates */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800">
          <h3 className="text-white font-semibold">Agent Success Rates</h3>
        </div>
        <div className="p-5 space-y-3">
          {Object.keys(quality.success_rate_by_agent).length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-4">No agent data for this period.</p>
          ) : (
            Object.entries(quality.success_rate_by_agent).map(([agentId, rate]) => {
              const pct = Math.round(rate * 100)
              const barColor = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500'
              return (
                <div key={agentId}>
                  <div className="flex justify-between mb-1">
                    <span className="text-gray-300 text-sm">{agentId}</span>
                    <span className="text-white text-sm font-medium">{pct}%</span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-2">
                    <div
                      className={`${barColor} h-2 rounded-full transition-all`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Quality summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Bugs Found (Tester)</p>
          <p className="text-red-400 text-2xl font-bold mt-1">{quality.bugs_found_by_tester}</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Code Churn</p>
          <p className="text-yellow-400 text-2xl font-bold mt-1">{quality.code_churn}</p>
          <p className="text-gray-500 text-xs mt-1">tasks re-run &gt;1×</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs uppercase tracking-wide">Failed Runs</p>
          <p className="text-orange-400 text-2xl font-bold mt-1">{quality.failed_runs}</p>
          <p className="text-gray-500 text-xs mt-1">of {quality.total_runs} total</p>
        </div>
      </div>

      {/* Cost by agent */}
      {Object.keys(cost.cost_by_agent).length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800">
            <h3 className="text-white font-semibold">Cost by Agent</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-5 py-3 text-gray-400 font-medium">Agent</th>
                  <th className="text-right px-5 py-3 text-gray-400 font-medium">Cost (USD)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(cost.cost_by_agent)
                  .sort(([, a], [, b]) => b - a)
                  .map(([agentId, agentCost]) => (
                    <tr key={agentId} className="border-b border-gray-800/50">
                      <td className="px-5 py-3 text-gray-300">{agentId}</td>
                      <td className="px-5 py-3 text-white text-right">${agentCost.toFixed(4)}</td>
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
