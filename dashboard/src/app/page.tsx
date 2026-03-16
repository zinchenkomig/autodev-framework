'use client'

import { useEffect, useState } from 'react'
import { getStats, getTasks, getAgents, getEvents, type DashboardStats, type Task, type Agent, type Event } from '@/lib/api'
import { StatCard } from '@/components/StatCard'
import { TaskTable } from '@/components/TaskTable'
import { AgentCard } from '@/components/AgentCard'
import { EventFeed } from '@/components/EventFeed'
import { Loader2 } from 'lucide-react'

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
        <Loader2 className="w-4 h-4 text-[#3F3F46] animate-spin" />
      </div>
    )
  }

  const recentTasks = tasks.slice(0, 10)
  const recentEvents = events.slice(0, 10)

  return (
    <div className="space-y-10 max-w-7xl">
      {/* Page title */}
      <div>
        <h1 className="text-sm font-semibold text-[#FAFAFA]">Dashboard</h1>
        <p className="text-xs text-[#71717A] mt-0.5">AutoDev Framework</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-px border border-[#1F1F23]">
        <StatCard
          label="Active Tasks"
          value={stats?.active_tasks ?? 0}
          trend={stats?.task_trend}
          description="vs last week"
        />
        <StatCard
          label="Running Agents"
          value={stats?.running_agents ?? 0}
          trend={stats?.agent_trend}
          description="of total"
        />
        <StatCard
          label="Open PRs"
          value={stats?.open_prs ?? 0}
          trend={stats?.pr_trend}
          description="awaiting review"
        />
        <StatCard
          label="Latest Release"
          value={stats?.latest_release ?? '—'}
          description="on staging"
        />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        {/* Recent Tasks + Agents */}
        <div className="xl:col-span-2 space-y-8">
          {/* Recent Tasks */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <p className="text-xs text-[#71717A] uppercase tracking-wider">Recent Tasks</p>
              <span className="text-xs text-[#3F3F46]">last 10</span>
            </div>
            <div className="border border-[#1F1F23] overflow-hidden">
              <div className="overflow-x-auto">
                <TaskTable tasks={recentTasks} />
              </div>
            </div>
          </div>

          {/* Agents */}
          <div>
            <div className="mb-4">
              <p className="text-xs text-[#71717A] uppercase tracking-wider">Agents</p>
            </div>
            <div className="border border-[#1F1F23]">
              {agents.length === 0 ? (
                <p className="text-xs text-[#3F3F46] text-center py-8">No agents</p>
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
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs text-[#71717A] uppercase tracking-wider">Activity</p>
            <span className="text-xs text-[#3F3F46]">last 10</span>
          </div>
          <div className="border border-[#1F1F23] px-4 py-2">
            <EventFeed events={recentEvents} />
          </div>
        </div>
      </div>
    </div>
  )
}
