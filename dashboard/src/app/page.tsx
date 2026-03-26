'use client'

import { useEffect, useState } from 'react'
import { getStats, getTasks, getAgentMonitors, getEvents, type DashboardStats, type Task, type AgentMonitor, type Event } from '@/lib/api'
import { StatCard } from '@/components/StatCard'
import { EventFeed } from '@/components/EventFeed'
import { Loader2, CheckSquare, Bot, GitPullRequest, Package, Clock, AlertCircle, User, Link2 } from 'lucide-react'
import Link from 'next/link'

const roleIcons: Record<string, string> = {
  developer: '👨‍💻',
  pm: '📋',
  project_manager: '📋',
  tester: '🧪',
  release_manager: '🚀',
}

const statusColors: Record<string, string> = {
  queued: '#808080',
  in_progress: '#3592C4',
  review: '#CC7832',
  ready_to_release: '#9876AA',
  released: '#6A8759',
  failed: '#CC4E4E',
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [agents, setAgents] = useState<AgentMonitor[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      const [s, t, a, e] = await Promise.all([
        getStats(),
        getTasks(),
        getAgentMonitors(),
        getEvents(),
      ])
      setStats(s)
      setTasks(t)
      setAgents(a)
      setEvents(e)
      setLoading(false)
    }
    load()
    
    // Auto-refresh every 30s
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  // Categorize tasks
  const workingAgents = agents.filter(a => a.status === 'working')
  const waitingForMe = tasks.filter(t => t.status === 'staging')
  const blockedTasks = tasks.filter(t => t.status === 'queued' && t.depends_on && t.depends_on.length > 0)
  const inProgress = tasks.filter(t => t.status === 'in_progress')
  const recentEvents = events.slice(0, 8)

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Page title */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Dashboard</h1>
        <p className="text-xs mt-0.5" style={{ color: '#808080' }}>AutoDev Framework — Status Overview</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Active Tasks"
          value={stats?.active_tasks ?? 0}
          trend={stats?.task_trend}
          description="in progress"
          accentColor="#3592C4"
          icon={<CheckSquare size={18} />}
        />
        <StatCard
          label="Waiting for Review"
          value={waitingForMe.length}
          description="need your attention"
          accentColor="#CC7832"
          icon={<User size={18} />}
        />
        <StatCard
          label="Blocked"
          value={blockedTasks.length}
          description="waiting for dependencies"
          accentColor="#9876AA"
          icon={<Link2 size={18} />}
        />
        <StatCard
          label="Running Agents"
          value={workingAgents.length}
          description={`of ${agents.length} total`}
          accentColor="#6A8759"
          icon={<Bot size={18} />}
        />
      </div>

      {/* Main content */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left column - Status sections */}
        <div className="xl:col-span-2 space-y-6">
          
          {/* Who's Working on What */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium text-white flex items-center gap-2">
                <Bot className="w-4 h-4" style={{ color: '#6A8759' }} />
                Who's Working on What
              </h2>
            </div>
            <div className="space-y-2">
              {workingAgents.length === 0 ? (
                <div className="p-4 rounded" style={{ background: '#2B2B2B', border: '1px solid #515151' }}>
                  <p className="text-xs text-gray-500">All agents idle</p>
                </div>
              ) : (
                workingAgents.map(agent => {
                  const icon = Object.entries(roleIcons).find(([k]) => agent.role.toLowerCase().includes(k))?.[1] || '🤖'
                  return (
                    <div 
                      key={agent.id}
                      className="flex items-center gap-3 p-3 rounded"
                      style={{ background: '#2B2B2B', border: '1px solid #515151' }}
                    >
                      <span className="text-lg">{icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white">{agent.role}</p>
                        {agent.current_task_title && (
                          <p className="text-xs text-gray-400 truncate">{agent.current_task_title}</p>
                        )}
                      </div>
                      <span className="flex items-center gap-1.5 text-xs" style={{ color: '#6A8759' }}>
                        <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: '#6A8759' }} />
                        working
                      </span>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* Waiting for Me */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium text-white flex items-center gap-2">
                <AlertCircle className="w-4 h-4" style={{ color: '#CC7832' }} />
                Waiting for Review ({waitingForMe.length})
              </h2>
              {waitingForMe.length > 0 && (
                <Link href="/tasks" className="text-xs" style={{ color: '#3592C4' }}>View all →</Link>
              )}
            </div>
            <div className="space-y-2">
              {waitingForMe.length === 0 ? (
                <div className="p-4 rounded" style={{ background: '#2B2B2B', border: '1px solid #515151' }}>
                  <p className="text-xs text-gray-500">No tasks waiting for review</p>
                </div>
              ) : (
                waitingForMe.slice(0, 5).map(task => (
                  <Link 
                    key={task.id}
                    href={`/tasks?id=${task.id}`}
                    className="flex items-center gap-3 p-3 rounded hover:bg-[#3C3F41] transition-colors"
                    style={{ background: '#2B2B2B', border: '1px solid #515151' }}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white truncate">{task.title}</p>
                      <p className="text-xs text-gray-500">{task.repo}</p>
                    </div>
                    {task.pr_url && (
                      <a 
                        href={task.pr_url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        className="text-xs px-2 py-1 rounded"
                        style={{ background: 'rgba(106,135,89,0.2)', color: '#6A8759' }}
                      >
                        PR
                      </a>
                    )}
                    <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(204,120,50,0.2)', color: '#CC7832' }}>
                      review
                    </span>
                  </Link>
                ))
              )}
            </div>
          </div>

          {/* Blocked Tasks */}
          {blockedTasks.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-medium text-white flex items-center gap-2">
                  <Clock className="w-4 h-4" style={{ color: '#9876AA' }} />
                  Blocked ({blockedTasks.length})
                </h2>
              </div>
              <div className="space-y-2">
                {blockedTasks.slice(0, 5).map(task => {
                  const depTasks = task.depends_on?.map(depId => tasks.find(t => t.id === depId)).filter(Boolean) || []
                  return (
                    <div 
                      key={task.id}
                      className="p-3 rounded"
                      style={{ background: '#2B2B2B', border: '1px solid #515151' }}
                    >
                      <p className="text-sm text-white truncate">{task.title}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-gray-500">Waiting for:</span>
                        {depTasks.map(dep => (
                          <span 
                            key={dep!.id}
                            className="text-xs px-1.5 py-0.5 rounded truncate max-w-[150px]"
                            style={{ 
                              background: `${statusColors[dep!.status]}22`,
                              color: statusColors[dep!.status]
                            }}
                          >
                            {dep!.title.slice(0, 30)}...
                          </span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* In Progress */}
          {inProgress.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-medium text-white flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" style={{ color: '#3592C4' }} />
                  In Progress ({inProgress.length})
                </h2>
              </div>
              <div className="space-y-2">
                {inProgress.map(task => (
                  <div 
                    key={task.id}
                    className="flex items-center gap-3 p-3 rounded"
                    style={{ background: '#2B2B2B', border: '1px solid #515151' }}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white truncate">{task.title}</p>
                      <p className="text-xs text-gray-500">{task.repo}</p>
                    </div>
                    <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(53,146,196,0.2)', color: '#3592C4' }}>
                      in progress
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right column - Activity Feed */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-white">Activity Feed</h2>
            <Link href="/events" className="text-xs" style={{ color: '#3592C4' }}>View all →</Link>
          </div>
          <div style={{ background: '#2B2B2B', border: '1px solid #515151', borderRadius: '4px', padding: '12px 16px' }}>
            <EventFeed events={recentEvents} />
          </div>
        </div>
      </div>
    </div>
  )
}
