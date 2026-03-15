'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import type { Event } from '@/lib/api'
import {
  GitPullRequest, CheckCircle, XCircle, Bug, Rocket,
  Package, User, Zap, AlertCircle, Tag, Filter, Loader2
} from 'lucide-react'

// --- Mock events inlined (client component can't use async server data directly) ---
const ALL_EVENTS: Event[] = [
  { id: '1', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-15T13:00:00Z', description: 'Task "Database migration script" assigned to developer', related_id: '6', related_type: 'task' },
  { id: '2', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-15T12:30:00Z', description: 'PR #26 created for "Add rate limiting"', related_id: '26', related_type: 'pr' },
  { id: '3', type: 'agent.idle', payload: {}, source: 'orchestrator', created_at: '2026-03-15T12:00:00Z', description: 'Agent pm transitioned to idle state' },
  { id: '4', type: 'deploy.staging', payload: {}, source: 'ci', created_at: '2026-03-15T11:00:00Z', description: 'Release v1.2.0-rc1 deployed to staging', related_id: '3', related_type: 'release' },
  { id: '5', type: 'pr.ci.passed', payload: {}, source: 'github', created_at: '2026-03-15T10:30:00Z', description: 'CI passed for PR #25', related_id: '25', related_type: 'pr' },
  { id: '6', type: 'bug.found', payload: {}, source: 'tester', created_at: '2026-03-15T09:00:00Z', description: 'Bug found: login page styling breaks on mobile', related_id: '2', related_type: 'task' },
  { id: '7', type: 'task.created', payload: {}, source: 'pm', created_at: '2026-03-15T08:30:00Z', description: 'New task created: "Database migration script"', related_id: '6', related_type: 'task' },
  { id: '8', type: 'pr.merged', payload: {}, source: 'github', created_at: '2026-03-15T08:00:00Z', description: 'PR #22 merged: Write unit tests for TaskQueue', related_id: '22', related_type: 'pr' },
  { id: '9', type: 'agent.running', payload: {}, source: 'orchestrator', created_at: '2026-03-15T07:30:00Z', description: 'Agent tester started task "E2E tests for checkout flow"' },
  { id: '10', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-15T07:25:00Z', description: 'Task "E2E tests for checkout flow" assigned to tester', related_id: '7', related_type: 'task' },
  { id: '11', type: 'pr.review_requested', payload: {}, source: 'developer', created_at: '2026-03-15T07:00:00Z', description: 'Review requested for PR #25 from tester', related_id: '25', related_type: 'pr' },
  { id: '12', type: 'task.in_progress', payload: {}, source: 'developer', created_at: '2026-03-15T06:30:00Z', description: 'Task "Database migration script" moved to in_progress', related_id: '6', related_type: 'task' },
  { id: '13', type: 'release.ready', payload: {}, source: 'orchestrator', created_at: '2026-03-14T17:00:00Z', description: 'Release v1.2.0-rc1 is ready for approval', related_id: '3', related_type: 'release' },
  { id: '14', type: 'deploy.production', payload: {}, source: 'ci', created_at: '2026-03-14T10:00:00Z', description: 'Release v1.1.0 deployed to production', related_id: '2', related_type: 'release' },
  { id: '15', type: 'release.approved', payload: {}, source: 'user', created_at: '2026-03-14T09:30:00Z', description: 'Release v1.1.0 approved by user', related_id: '2', related_type: 'release' },
  { id: '16', type: 'pr.ci.failed', payload: {}, source: 'github', created_at: '2026-03-14T09:00:00Z', description: 'CI failed for PR #20 — 3 tests failed', related_id: '20', related_type: 'pr' },
  { id: '17', type: 'bug.resolved', payload: {}, source: 'developer', created_at: '2026-03-14T08:30:00Z', description: 'Bug resolved: navbar overflow on small screens' },
  { id: '18', type: 'task.done', payload: {}, source: 'developer', created_at: '2026-03-14T08:00:00Z', description: 'Task "Setup CI/CD pipeline" marked done', related_id: '5', related_type: 'task' },
  { id: '19', type: 'pr.merged', payload: {}, source: 'github', created_at: '2026-03-14T07:45:00Z', description: 'PR #18 merged: Setup CI/CD pipeline', related_id: '18', related_type: 'pr' },
  { id: '20', type: 'agent.failed', payload: {}, source: 'developer', created_at: '2026-03-14T06:00:00Z', description: 'Agent developer failed on task "Mobile responsive navbar"' },
  { id: '21', type: 'bug.found', payload: {}, source: 'tester', created_at: '2026-03-13T18:00:00Z', description: 'Bug found: API rate limit not applied to /health endpoint', related_id: '3', related_type: 'task' },
  { id: '22', type: 'pr.ci.passed', payload: {}, source: 'github', created_at: '2026-03-13T17:00:00Z', description: 'CI passed for PR #18', related_id: '18', related_type: 'pr' },
  { id: '23', type: 'task.created', payload: {}, source: 'ba', created_at: '2026-03-13T16:00:00Z', description: 'New task created: "Optimize database queries"', related_id: '9', related_type: 'task' },
  { id: '24', type: 'deploy.staging', payload: {}, source: 'ci', created_at: '2026-03-13T15:00:00Z', description: 'Release v1.1.0 deployed to staging', related_id: '2', related_type: 'release' },
  { id: '25', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-13T14:00:00Z', description: 'PR #22 created: Write unit tests for TaskQueue', related_id: '22', related_type: 'pr' },
  { id: '26', type: 'agent.running', payload: {}, source: 'orchestrator', created_at: '2026-03-13T13:30:00Z', description: 'Agent tester started task "Write unit tests for TaskQueue"' },
  { id: '27', type: 'task.assigned', payload: {}, source: 'orchestrator', created_at: '2026-03-13T13:00:00Z', description: 'Task "Write unit tests for TaskQueue" assigned to tester', related_id: '4', related_type: 'task' },
  { id: '28', type: 'task.created', payload: {}, source: 'pm', created_at: '2026-03-13T12:00:00Z', description: 'New task created: "Write unit tests for TaskQueue"', related_id: '4', related_type: 'task' },
  { id: '29', type: 'pr.created', payload: {}, source: 'developer', created_at: '2026-03-13T11:00:00Z', description: 'PR #18 created: Setup CI/CD pipeline', related_id: '18', related_type: 'pr' },
  { id: '30', type: 'task.in_progress', payload: {}, source: 'developer', created_at: '2026-03-13T10:30:00Z', description: 'Task "Setup CI/CD pipeline" moved to in_progress', related_id: '5', related_type: 'task' },
  { id: '31', type: 'release.created', payload: {}, source: 'pm', created_at: '2026-03-13T10:00:00Z', description: 'Release v1.1.0 created (draft)', related_id: '2', related_type: 'release' },
  { id: '32', type: 'agent.idle', payload: {}, source: 'orchestrator', created_at: '2026-03-13T09:00:00Z', description: 'Agent ba completed analysis and returned to idle' },
  { id: '33', type: 'bug.triaged', payload: {}, source: 'ba', created_at: '2026-03-12T17:00:00Z', description: 'Bug triaged: session token expiry too short — marked high priority' },
  { id: '34', type: 'deploy.production', payload: {}, source: 'ci', created_at: '2026-03-12T15:00:00Z', description: 'Release v1.0.2 deployed to production', related_id: '1', related_type: 'release' },
  { id: '35', type: 'release.approved', payload: {}, source: 'user', created_at: '2026-03-12T14:30:00Z', description: 'Release v1.0.2 approved by user', related_id: '1', related_type: 'release' },
]

// --- Event config ---
type EventConfig = { icon: React.ElementType; color: string; bg: string }

function getEventConfig(type: string): EventConfig {
  const prefix = type.split('.')[0]
  const map: Record<string, EventConfig> = {
    'task.created': { icon: Zap, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    'task.assigned': { icon: User, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
    'task.in_progress': { icon: Zap, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
    'task.done': { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
    'task.failed': { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
    'pr.created': { icon: GitPullRequest, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    'pr.merged': { icon: CheckCircle, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
    'pr.ci.passed': { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
    'pr.ci.failed': { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
    'pr.review_requested': { icon: GitPullRequest, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    'deploy.staging': { icon: Rocket, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
    'deploy.production': { icon: Rocket, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
    'bug.found': { icon: Bug, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
    'bug.resolved': { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
    'bug.triaged': { icon: Bug, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20' },
    'agent.running': { icon: Zap, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
    'agent.idle': { icon: User, color: 'text-gray-400', bg: 'bg-gray-500/10 border-gray-500/20' },
    'agent.failed': { icon: AlertCircle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
    'release.created': { icon: Tag, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    'release.ready': { icon: Package, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    'release.approved': { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
  }

  if (map[type]) return map[type]

  const prefixDefaults: Record<string, EventConfig> = {
    task: { icon: Zap, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    pr: { icon: GitPullRequest, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    deploy: { icon: Rocket, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
    bug: { icon: Bug, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
    agent: { icon: User, color: 'text-gray-400', bg: 'bg-gray-500/10 border-gray-500/20' },
    release: { icon: Package, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
  }
  return prefixDefaults[prefix] ?? { icon: Zap, color: 'text-gray-400', bg: 'bg-gray-500/10 border-gray-500/20' }
}

// --- Filter categories ---
type FilterCategory = 'all' | 'task' | 'pr' | 'deploy' | 'bug' | 'agent' | 'release'

const FILTERS: { value: FilterCategory; label: string; icon: React.ElementType }[] = [
  { value: 'all', label: 'All', icon: Filter },
  { value: 'task', label: 'Tasks', icon: Zap },
  { value: 'pr', label: 'PRs', icon: GitPullRequest },
  { value: 'deploy', label: 'Deploys', icon: Rocket },
  { value: 'bug', label: 'Bugs', icon: Bug },
  { value: 'agent', label: 'Agents', icon: User },
  { value: 'release', label: 'Releases', icon: Package },
]

function formatTime(dateString: string) {
  const date = new Date(dateString)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days > 0) return `${days}d ago`
  if (hours > 0) return `${hours}h ago`
  if (minutes > 0) return `${minutes}m ago`
  return 'just now'
}

function formatFullDate(dateString: string) {
  return new Date(dateString).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

const PAGE_SIZE = 10

export default function EventsPage() {
  const router = useRouter()
  const [filter, setFilter] = useState<FilterCategory>('all')
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(false)
  const loaderRef = useRef<HTMLDivElement>(null)

  const filtered = filter === 'all'
    ? ALL_EVENTS
    : ALL_EVENTS.filter(e => e.type.startsWith(filter + '.'))

  const visible = filtered.slice(0, page * PAGE_SIZE)
  const hasMore = visible.length < filtered.length

  // Reset pagination when filter changes
  useEffect(() => {
    setPage(1)
  }, [filter])

  // Intersection observer for infinite scroll
  const loadMore = useCallback(() => {
    if (isLoading || !hasMore) return
    setIsLoading(true)
    setTimeout(() => {
      setPage(p => p + 1)
      setIsLoading(false)
    }, 400)
  }, [isLoading, hasMore])

  useEffect(() => {
    const el = loaderRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      entries => { if (entries[0].isIntersecting) loadMore() },
      { rootMargin: '100px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loadMore])

  function handleEventClick(event: Event) {
    if (!event.related_id || !event.related_type) return
    if (event.related_type === 'task') router.push(`/tasks`)
    else if (event.related_type === 'release') router.push(`/releases/${event.related_id}`)
    else if (event.related_type === 'pr') {
      // PRs link externally — no internal page, skip navigation
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-white">Activity Feed</h2>
        <p className="text-gray-400 text-sm mt-1">Chronological log of all system events</p>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        {FILTERS.map(f => {
          const Icon = f.icon
          const active = filter === f.value
          return (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                active
                  ? 'bg-blue-500/20 border border-blue-500/40 text-blue-400'
                  : 'bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {f.label}
              {f.value !== 'all' && (
                <span className={`text-xs rounded px-1 ${active ? 'bg-blue-500/30 text-blue-300' : 'bg-gray-700 text-gray-500'}`}>
                  {ALL_EVENTS.filter(e => e.type.startsWith(f.value + '.')).length}
                </span>
              )}
            </button>
          )
        })}
        <span className="ml-auto text-xs text-gray-600">
          {filtered.length} events
        </span>
      </div>

      {/* Event feed */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {visible.length === 0 ? (
          <div className="p-12 text-center text-gray-500 text-sm">No events for this filter.</div>
        ) : (
          <div className="divide-y divide-gray-800">
            {visible.map(event => {
              const config = getEventConfig(event.type)
              const Icon = config.icon
              const clickable = !!event.related_id && event.related_type !== 'pr'

              return (
                <div
                  key={event.id}
                  onClick={() => handleEventClick(event)}
                  className={`flex items-start gap-4 px-5 py-4 transition-colors ${
                    clickable ? 'hover:bg-gray-800/60 cursor-pointer' : ''
                  }`}
                >
                  {/* Icon */}
                  <div className={`p-2 rounded-lg border shrink-0 mt-0.5 ${config.bg}`}>
                    <Icon className={`w-3.5 h-3.5 ${config.color}`} />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm text-gray-200 leading-snug">
                          {event.description ?? event.type}
                        </p>
                        <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                          <span className="font-mono text-gray-600">{event.type}</span>
                          <span>·</span>
                          <span>{event.source}</span>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <span className="text-xs text-gray-500 whitespace-nowrap" title={formatFullDate(event.created_at)}>
                          {formatTime(event.created_at)}
                        </span>
                        {clickable && (
                          <p className="text-xs text-blue-500/60 mt-0.5">→ view</p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Loader sentinel */}
        <div ref={loaderRef} className="h-4" />
        {isLoading && (
          <div className="flex justify-center py-4 border-t border-gray-800">
            <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
          </div>
        )}
        {!hasMore && visible.length > 0 && (
          <div className="py-4 text-center text-xs text-gray-600 border-t border-gray-800">
            All {filtered.length} events loaded
          </div>
        )}
      </div>
    </div>
  )
}
