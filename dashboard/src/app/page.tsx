'use client'

import { useEffect, useState } from 'react'
import { getStats, getTasks, getAgents, getEvents, type DashboardStats, type Task, type Agent, type Event } from '@/lib/api'
import { StatCard } from '@/components/StatCard'
import { TaskTable } from '@/components/TaskTable'
import { AgentCard } from '@/components/AgentCard'
import { EventFeed } from '@/components/EventFeed'
import { Loader2, CheckSquare, Bot, GitPullRequest, Package } from 'lucide-react'

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      const [s, t, a, e] = await Promise.all([
        getStats(),
        getTasks(),
        getAgents(),
        getEvents(),
      ])
      setStats(s)
      setTasks(t)
      setAgents(a)
      setEvents(e)
      setLoading(false)
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  const recentTasks = tasks.slice(0, 10)
  const recentEvents = events.slice(0, 10)

  return (
    <div className="space-y-8 max-w-7xl">
      {/* Page title */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Dashboard</h1>
        <p className="text-xs mt-0.5" style={{ color: '#808080' }}>AutoDev Framework — Overview</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Active Tasks"
          value={stats?.active_tasks ?? 0}
          trend={stats?.task_trend}
          description="vs last week"
          accentColor="#3592C4"
          icon={<CheckSquare size={18} />}
        />
        <StatCard
          label="Running Agents"
          value={stats?.running_agents ?? 0}
          trend={stats?.agent_trend}
          description="of total"
          accentColor="#6A8759"
          icon={<Bot size={18} />}
        />
        <StatCard
          label="Open PRs"
          value={stats?.open_prs ?? 0}
          trend={stats?.pr_trend}
          description="awaiting review"
          accentColor="#CC7832"
          icon={<GitPullRequest size={18} />}
        />
        <StatCard
          label="Latest Release"
          value={stats?.latest_release ?? '—'}
          description="on staging"
          accentColor="#9876AA"
          icon={<Package size={18} />}
        />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Recent Tasks + Agents */}
        <div className="xl:col-span-2 space-y-6">
          {/* Recent Tasks */}
          <div>
            <div className="section-heading">Recent Tasks</div>
            <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
              <div className="overflow-x-auto">
                <TaskTable tasks={recentTasks} />
              </div>
            </div>
          </div>

          {/* Agents */}
          <div>
            <div className="section-heading">Agents</div>
            <div style={{ border: '1px solid #515151', borderRadius: '4px' }}>
              {agents.length === 0 ? (
                <p className="text-xs text-center py-8" style={{ color: '#808080' }}>No agents</p>
              ) : (
                <div className="px-4">
                  {agents.map((agent) => (
                    <AgentCard key={agent.id} agent={agent} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Activity Feed */}
        <div>
          <div className="section-heading">Activity Feed</div>
          <div style={{ border: '1px solid #515151', borderRadius: '4px', padding: '12px 16px' }}>
            <EventFeed events={recentEvents} />
          </div>
        </div>
      </div>
    </div>
  )
}
