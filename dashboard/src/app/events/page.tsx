'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import type { Event } from '@/lib/api'
import { Loader2 } from 'lucide-react'

// ─── Mock events ──────────────────────────────────────────────────────────────
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

// ─── Color + icon map ─────────────────────────────────────────────────────────

const eventConfig: Record<string, { color: string; category: string }> = {
  'task.created':      { color: '#3592C4', category: 'task' },
  'task.assigned':     { color: '#9876AA', category: 'task' },
  'task.in_progress':  { color: '#CC7832', category: 'task' },
  'task.done':         { color: '#6A8759', category: 'task' },
  'pr.created':        { color: '#3592C4', category: 'pr'   },
  'pr.merged':         { color: '#6A8759', category: 'pr'   },
  'pr.ci.passed':      { color: '#6A8759', category: 'pr'   },
  'pr.ci.failed':      { color: '#CC4E4E', category: 'pr'   },
  'pr.review_requested': { color: '#9876AA', category: 'pr' },
  'deploy.staging':    { color: '#CC7832', category: 'deploy' },
  'deploy.production': { color: '#6A8759', category: 'deploy' },
  'bug.found':         { color: '#CC4E4E', category: 'bug'  },
  'bug.resolved':      { color: '#6A8759', category: 'bug'  },
  'bug.triaged':       { color: '#CC7832', category: 'bug'  },
  'agent.running':     { color: '#CC7832', category: 'agent' },
  'agent.idle':        { color: '#808080', category: 'agent' },
  'agent.failed':      { color: '#CC4E4E', category: 'agent' },
  'release.created':   { color: '#3592C4', category: 'release' },
  'release.ready':     { color: '#9876AA', category: 'release' },
  'release.approved':  { color: '#6A8759', category: 'release' },
}

// ─── Filters ──────────────────────────────────────────────────────────────────

type FilterCategory = 'all' | 'task' | 'pr' | 'deploy' | 'bug' | 'agent' | 'release'

const FILTERS: { value: FilterCategory; label: string }[] = [
  { value: 'all',     label: 'All' },
  { value: 'task',    label: 'Tasks' },
  { value: 'pr',      label: 'PRs' },
  { value: 'deploy',  label: 'Deploys' },
  { value: 'bug',     label: 'Bugs' },
  { value: 'agent',   label: 'Agents' },
  { value: 'release', label: 'Releases' },
]

function formatTime(dateString: string) {
  const diff = Date.now() - new Date(dateString).getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days > 0) return `${days}d`
  if (hours > 0) return `${hours}h`
  if (minutes > 0) return `${minutes}m`
  return 'now'
}

const PAGE_SIZE = 15

export default function EventsPage() {
  const router = useRouter()
  const [filter, setFilter] = useState<FilterCategory>('all')
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(false)
  const loaderRef = useRef<HTMLDivElement>(null)

  const filtered = filter === 'all'
    ? ALL_EVENTS
    : ALL_EVENTS.filter(e => {
        const cfg = eventConfig[e.type]
        return cfg?.category === filter
      })

  const visible = filtered.slice(0, page * PAGE_SIZE)
  const hasMore = visible.length < filtered.length

  useEffect(() => { setPage(1) }, [filter])

  const loadMore = useCallback(() => {
    if (isLoading || !hasMore) return
    setIsLoading(true)
    setTimeout(() => {
      setPage(p => p + 1)
      setIsLoading(false)
    }, 300)
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
    if (event.related_type === 'task') router.push('/tasks')
    else if (event.related_type === 'release') router.push(`/releases/${event.related_id}`)
  }

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Events</h1>
        <p className="text-xs mt-0.5" style={{ color: '#808080' }}>{filtered.length} events</p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 no-scrollbar flex-wrap">
        {FILTERS.map(f => {
          const active = filter === f.value
          const count = f.value === 'all'
            ? ALL_EVENTS.length
            : ALL_EVENTS.filter(e => {
                const cfg = eventConfig[e.type]
                return cfg?.category === f.value
              }).length
          return (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className="px-3 py-1.5 text-xs transition-colors shrink-0"
              style={{
                border: '1px solid',
                borderColor: active ? '#3592C4' : '#515151',
                background: active ? '#3C3F41' : 'transparent',
                color: active ? '#FFFFFF' : '#808080',
                borderRadius: '4px',
              }}
              onMouseEnter={e => {
                if (!active) {
                  (e.currentTarget as HTMLButtonElement).style.borderColor = '#808080'
                  ;(e.currentTarget as HTMLButtonElement).style.color = '#BABABA'
                }
              }}
              onMouseLeave={e => {
                if (!active) {
                  (e.currentTarget as HTMLButtonElement).style.borderColor = '#515151'
                  ;(e.currentTarget as HTMLButtonElement).style.color = '#808080'
                }
              }}
            >
              {f.label}
              {f.value !== 'all' && (
                <span className="ml-1.5 font-mono" style={{ color: active ? '#808080' : '#515151' }}>{count}</span>
              )}
            </button>
          )
        })}
      </div>

      {/* Event list */}
      <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
        {visible.length === 0 ? (
          <div className="py-10 text-center text-xs" style={{ color: '#808080' }}>No events</div>
        ) : (
          visible.map((event, idx) => {
            const cfg = eventConfig[event.type]
            const color = cfg?.color ?? '#808080'
            const clickable = !!event.related_id && event.related_type !== 'pr'
            const isOdd = idx % 2 === 0

            return (
              <div
                key={event.id}
                onClick={() => handleEventClick(event)}
                className="flex items-center gap-3 px-4 py-2.5 transition-colors"
                style={{
                  background: isOdd ? '#2B2B2B' : '#313335',
                  cursor: clickable ? 'pointer' : 'default',
                  borderBottom: idx < visible.length - 1 ? '1px solid #414345' : 'none',
                }}
                onMouseEnter={e => {
                  if (clickable) (e.currentTarget as HTMLDivElement).style.background = '#353739'
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLDivElement).style.background = isOdd ? '#2B2B2B' : '#313335'
                }}
              >
                <span
                  style={{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: color,
                    flexShrink: 0,
                  }}
                />
                <span className="text-xs flex-1 min-w-0 truncate" style={{ color: '#BABABA' }}>
                  {event.description ?? event.type}
                </span>
                <span className="text-xs font-mono shrink-0" style={{ color: '#808080' }}>{formatTime(event.created_at)}</span>
              </div>
            )
          })
        )}
      </div>

      {/* Infinite scroll sentinel */}
      <div ref={loaderRef} className="h-2" />
      {isLoading && (
        <div className="flex justify-center py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: '#3592C4' }} />
        </div>
      )}
      {!hasMore && visible.length > 0 && (
        <p className="text-center text-xs py-2" style={{ color: '#808080' }}>
          All {filtered.length} events loaded
        </p>
      )}
    </div>
  )
}
