'use client'

import { useEffect, useState } from 'react'
import { getStats, getTasks, getAgents, getEvents, type DashboardStats, type Task, type Agent, type Event } from '@/lib/api'
import { StatCard } from '@/components/StatCard'
import { TaskTable } from '@/components/TaskTable'
import { AgentCard } from '@/components/AgentCard'
import { EventFeed } from '@/components/EventFeed'
import { ListTodo, Bot, GitPullRequest, Tag, Loader2 } from 'lucide-react'

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
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  const recentTasks = tasks.slice(0, 10)
  const recentEvents = events.slice(0, 10)

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div>
        <h2 className="text-2xl font-bold text-white">Dashboard</h2>
        <p className="text-gray-400 text-sm mt-1">AutoDev Framework overview</p>
      </div>

      {/* Stat cards – 2 cols on mobile, 4 on lg */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Active Tasks"
          value={stats!.active_tasks}
          icon={ListTodo}
          trend={stats!.task_trend}
          description="vs last week"
        />
        <StatCard
          label="Running Agents"
          value={stats!.running_agents}
          icon={Bot}
          trend={stats!.agent_trend}
          description="of 4 total"
        />
        <StatCard
          label="Open PRs"
          value={stats!.open_prs}
          icon={GitPullRequest}
          trend={stats!.pr_trend}
          description="awaiting review"
        />
        <StatCard
          label="Latest Release"
          value={stats!.latest_release ?? '—'}
          icon={Tag}
          description="on staging"
        />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Recent Tasks + Agent Status */}
        <div className="xl:col-span-2 space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h3 className="text-white font-semibold">Recent Tasks</h3>
              <span className="text-xs text-gray-500">Last 10</span>
            </div>
            {/* horizontal scroll on mobile */}
            <div className="overflow-x-auto">
              <TaskTable tasks={recentTasks} />
            </div>
          </div>

          {/* Agent Status – 1 col on mobile, 2 on sm */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800">
              <h3 className="text-white font-semibold">Agent Status</h3>
            </div>
            <div className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
              {agents.map((agent) => (
                <AgentCard key={agent.id} agent={agent} />
              ))}
            </div>
          </div>
        </div>

        {/* Activity Feed */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h3 className="text-white font-semibold">Activity Feed</h3>
            <span className="text-xs text-gray-500">Last 10</span>
          </div>
          <div className="p-5">
            <EventFeed events={recentEvents} />
          </div>
        </div>
      </div>
    </div>
  )
}
