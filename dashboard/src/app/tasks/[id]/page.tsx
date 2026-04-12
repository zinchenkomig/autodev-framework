'use client'

import { useEffect, useState } from 'react'
import { use } from 'react'
import { notFound, useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  getTask, getTasks, getTaskLogs,
  updateTask, restartTask, restartStagingTask, requestChanges,
  type Task, type TaskStatus, type TaskLog,
} from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { PriorityBadge, StatusBadge } from '@/components/Badge'
import {
  ArrowLeft, GitPullRequest, GitBranch, ExternalLink,
  ChevronDown, ChevronRight, RefreshCw, FileText,
  RotateCcw, Loader2, Link2,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Status config
// ---------------------------------------------------------------------------

const STATUS_PILLS: { id: TaskStatus; label: string }[] = [
  { id: 'queued',           label: 'Queued'           },
  { id: 'in_progress',      label: 'In Progress'      },
  { id: 'autoreview',       label: 'Auto Review'      },
  { id: 'qa_testing',       label: 'QA Testing'       },
  { id: 'ready_to_release', label: 'Ready to Release' },
  { id: 'staging',          label: 'Staging'          },
  { id: 'released',         label: 'Released'         },
]

const STATUS_COLORS: Record<string, string> = {
  queued: '#808080', assigned: '#9876AA', in_progress: '#CC7832',
  autoreview: '#3592C4', qa_testing: '#E5C07B', review: '#3592C4',
  ready_to_release: '#9876AA', staging: '#E5C07B', released: '#6A8759',
  failed: '#CC4E4E',
}

const levelConfig: Record<string, { color: string; label: string }> = {
  info:       { color: '#9E9E9E', label: 'INFO' },
  warning:    { color: '#CC7832', label: 'WARN' },
  error:      { color: '#CC4E4E', label: 'ERR'  },
  transition: { color: '#3592C4', label: '→'   },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatLogTime(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' +
      d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return '' }
}

// ---------------------------------------------------------------------------
// Log components
// ---------------------------------------------------------------------------

function LogEntry({ log }: { log: TaskLog }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = levelConfig[log.level] || levelConfig.info
  const hasDetails = log.details && log.details.length > 0

  return (
    <div style={{ borderBottom: '1px solid #3C3F41' }}>
      <div
        className={`flex items-start gap-2 px-3 py-1.5 ${hasDetails ? 'cursor-pointer hover:bg-[#3C3F41]' : ''}`}
        onClick={() => hasDetails && setExpanded(!expanded)}
        style={{ fontSize: '11px' }}
      >
        <span style={{ color: '#515151', width: '12px', marginTop: '2px' }}>
          {hasDetails ? (expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />) : null}
        </span>
        <span className="font-mono shrink-0" style={{ color: '#616161', fontSize: '10px' }}>{formatLogTime(log.created_at)}</span>
        <span className="px-1 rounded font-bold" style={{ color: cfg.color, fontSize: '10px' }}>{cfg.label}</span>
        <span className="flex-1" style={{ color: '#BABABA', wordBreak: 'break-word' }}>{log.message}</span>
      </div>
      {expanded && log.details && (
        <div
          className="px-4 pb-2 pt-1 whitespace-pre-wrap overflow-x-auto"
          style={{ background: '#1E1F22', fontSize: '10px', color: '#9E9E9E', maxHeight: '300px', overflowY: 'auto', fontFamily: 'monospace' }}
        >
          {log.details}
        </div>
      )}
    </div>
  )
}

interface LogBlock { status: string; reason: string; timestamp: string; logs: TaskLog[] }

function groupLogsByStatus(logs: TaskLog[]): LogBlock[] {
  const blocks: LogBlock[] = []
  let currentBlock: LogBlock | null = null
  const sorted = [...logs].reverse()
  for (const log of sorted) {
    if (log.level === 'transition') {
      const match = log.message.match(/→\s*(\S+)(?:\s*\((.+)\))?/)
      currentBlock = { status: match?.[1] || 'unknown', reason: match?.[2] || '', timestamp: log.created_at, logs: [] }
      blocks.push(currentBlock)
    } else {
      if (!currentBlock) { currentBlock = { status: '', reason: '', timestamp: log.created_at, logs: [] }; blocks.push(currentBlock) }
      currentBlock.logs.push(log)
    }
  }
  return blocks.reverse()
}

function StatusDivider({ block }: { block: LogBlock }) {
  const color = STATUS_COLORS[block.status] || '#808080'
  return (
    <div className="flex items-center gap-3 px-3 py-2" style={{ background: `${color}15`, borderBottom: `2px solid ${color}40` }}>
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
      <span className="text-xs font-bold uppercase tracking-wider" style={{ color }}>{block.status || 'initial'}</span>
      {block.reason && <span className="text-xs" style={{ color: '#808080' }}>{block.reason}</span>}
      <span className="ml-auto text-xs font-mono" style={{ color: '#616161' }}>{formatLogTime(block.timestamp)}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dependency link component
// ---------------------------------------------------------------------------

function DependencyLink({ taskId, allTasks }: { taskId: string; allTasks: Task[] }) {
  const dep = allTasks.find(t => t.id === taskId)
  if (!dep) {
    return (
      <span className="text-xs font-mono" style={{ color: '#515151' }}>
        {taskId.slice(0, 8)}...
      </span>
    )
  }
  const color = STATUS_COLORS[dep.status] || '#808080'
  return (
    <Link
      href={`/tasks/${dep.id}`}
      className="flex items-center gap-2 px-3 py-2 rounded transition-colors"
      style={{ background: '#3C3F41', border: '1px solid #515151' }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = '#414345' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '#3C3F41' }}
    >
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
      <span className="text-xs flex-1 min-w-0 truncate" style={{ color: '#BABABA' }}>
        {dep.ticket_number && <span className="font-mono mr-1" style={{ color: '#808080' }}>#{dep.ticket_number}</span>}
        {dep.title}
      </span>
      <span className="text-xs shrink-0" style={{ color }}>{dep.status}</span>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TaskDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const [task, setTask] = useState<Task | null | undefined>(undefined)
  const [allTasks, setAllTasks] = useState<Task[]>([])
  const [logs, setLogs] = useState<TaskLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [showLogs, setShowLogs] = useState(true)
  const [saving, setSaving] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [restartResult, setRestartResult] = useState<string[] | null>(null)
  const [changesComment, setChangesComment] = useState('')
  const [requestingChanges, setRequestingChanges] = useState(false)
  const [changesResult, setChangesResult] = useState<string | null>(null)

  useEffect(() => {
    getTask(id).then(t => setTask(t))
    getTasks().then(t => setAllTasks(t))
  }, [id])

  useEffect(() => {
    if (task) {
      loadLogs()
      if (task.status === 'staging') setChangesComment(task.description || '')
    }
  }, [task?.id])

  async function loadLogs() {
    if (!task) return
    setLogsLoading(true)
    try { setLogs(await getTaskLogs(task.id, 100)) } catch { /* */ }
    finally { setLogsLoading(false) }
  }

  if (task === undefined) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} /></div>
  }
  if (task === null) { notFound(); return null }

  const status = task.status

  async function handleStatusClick(newStatus: TaskStatus) {
    if (!task || newStatus === task.status || saving) return
    setSaving(true)
    try {
      await updateTask(task.id, { status: newStatus })
      setTask({ ...task, status: newStatus })
    } catch { /* */ }
    finally { setSaving(false) }
  }

  // Tasks that depend ON this task
  const dependents = allTasks.filter(t => t.depends_on?.includes(task.id))

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Back */}
      <Link href="/tasks" className="inline-flex items-center gap-1.5 text-xs transition-colors" style={{ color: '#808080' }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = '#FFFFFF' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = '#808080' }}
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Tasks
      </Link>

      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <PriorityBadge priority={task.priority} />
          <StatusBadge status={status} />
          {task.story_points > 0 && (
            <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ color: '#E5C07B', background: 'rgba(229,192,123,0.15)' }}>
              {task.story_points}SP
            </span>
          )}
        </div>
        <h1 className="text-lg font-semibold" style={{ color: '#FFFFFF' }}>
          {task.ticket_number && <span className="font-mono mr-2" style={{ color: '#808080' }}>#{task.ticket_number}</span>}
          {task.title}
        </h1>
      </div>

      {/* Meta */}
      <div className="flex items-center gap-4 flex-wrap text-xs" style={{ color: '#808080' }}>
        {task.repo && <span className="font-mono">{task.repo}</span>}
        <span>by {task.created_by}</span>
        <span>{formatDate(task.created_at)}</span>
        {task.assigned_to && <span>assigned to <span style={{ color: '#9876AA' }}>{task.assigned_to}</span></span>}
      </div>

      {/* Status picker */}
      <div className="pt-2" style={{ borderTop: '1px solid #3C3F41' }}>
        <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Status</p>
        <div className="flex flex-wrap gap-2">
          {STATUS_PILLS.map(({ id: sid, label }) => {
            const isActive = status === sid
            const dot = STATUS_COLORS[sid]
            return (
              <button key={sid} disabled={saving} onClick={() => handleStatusClick(sid)}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all disabled:opacity-60"
                style={{ border: `1px solid ${isActive ? dot : '#515151'}`, background: isActive ? `${dot}22` : 'transparent', color: isActive ? dot : '#808080' }}
              >
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: isActive ? dot : '#515151' }} />
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Description */}
      {task.description && (
        <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
          <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Description</p>
          <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: '#BABABA' }}>{task.description}</p>
        </div>
      )}

      {/* Links: branch, PR */}
      {(task.branch || task.pr_url) && (
        <div className="flex items-center gap-3 flex-wrap">
          {task.branch && (
            <a href={`https://github.com/${task.repo}/tree/${task.branch}`} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors"
              style={{ color: '#9876AA', background: 'rgba(152,118,170,0.12)', border: '1px solid rgba(152,118,170,0.25)' }}
            >
              <GitBranch className="w-3.5 h-3.5" /> {task.branch}
            </a>
          )}
          {task.pr_url && (
            <a href={task.pr_url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors"
              style={{ color: '#6A8759', background: 'rgba(106,135,89,0.12)', border: '1px solid rgba(106,135,89,0.25)' }}
            >
              <GitPullRequest className="w-3.5 h-3.5" /> PR #{task.pr_number} <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      )}

      {/* Dependencies */}
      {task.depends_on && task.depends_on.length > 0 && (
        <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
          <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>
            <Link2 className="w-3 h-3 inline mr-1" /> Depends on ({task.depends_on.length})
          </p>
          <div className="space-y-1.5">
            {task.depends_on.map(depId => (
              <DependencyLink key={depId} taskId={depId} allTasks={allTasks} />
            ))}
          </div>
        </div>
      )}

      {/* Dependents (tasks that depend on this one) */}
      {dependents.length > 0 && (
        <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
          <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>
            <Link2 className="w-3 h-3 inline mr-1" /> Blocked by this ({dependents.length})
          </p>
          <div className="space-y-1.5">
            {dependents.map(dep => (
              <DependencyLink key={dep.id} taskId={dep.id} allTasks={allTasks} />
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      {(status === 'ready_to_release') && (
        <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
          <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Feedback</p>
          <textarea value={changesComment} onChange={e => setChangesComment(e.target.value)}
            placeholder="Describe what needs changes..." rows={3}
            className="w-full px-3 py-2 rounded text-sm resize-none outline-none"
            style={{ background: '#1E1F22', border: '1px solid #515151', color: '#BABABA' }} />
          <button onClick={async () => {
            if (!changesComment.trim()) return
            setRequestingChanges(true); setChangesResult(null)
            try { const r = await requestChanges(task.id, changesComment); setChangesResult(`Created: ${r.followup_title}`); setChangesComment('') }
            catch (e) { setChangesResult('Error: ' + String(e)) }
            finally { setRequestingChanges(false) }
          }} disabled={requestingChanges || !changesComment.trim()}
            className="mt-2 flex items-center gap-2 px-3 py-2 rounded text-xs font-medium disabled:opacity-50"
            style={{ background: '#CC783222', color: '#CC7832', border: '1px solid #CC7832' }}
          >{requestingChanges ? <Loader2 className="w-3 h-3 animate-spin" /> : null} Request changes</button>
          {changesResult && <p className="text-xs mt-2" style={{ color: changesResult.startsWith('Error') ? '#CC4E4E' : '#6A8759' }}>{changesResult}</p>}
        </div>
      )}

      {(status === 'staging') && (
        <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
          <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Restart from Staging</p>
          <textarea value={changesComment} onChange={e => setChangesComment(e.target.value)}
            placeholder="Task description..." rows={4}
            className="w-full px-3 py-2 rounded text-sm resize-none outline-none"
            style={{ background: '#1E1F22', border: '1px solid #515151', color: '#BABABA' }} />
          <button onClick={async () => {
            setRestarting(true); setRestartResult(null)
            try { const r = await restartStagingTask(task.id, changesComment); setRestartResult(r.actions); setTask({ ...task, status: 'queued' }) }
            catch (e) { setRestartResult(['Error: ' + String(e)]) }
            finally { setRestarting(false) }
          }} disabled={restarting}
            className="mt-2 flex items-center gap-2 px-3 py-2 rounded text-xs font-medium disabled:opacity-50"
            style={{ background: '#CC4E4E22', color: '#CC4E4E', border: '1px solid #CC4E4E' }}
          >{restarting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />} Restart (Revert & Requeue)</button>
          {restartResult && (
            <div className="mt-2 p-2 rounded text-xs" style={{ background: '#1E1F22', border: '1px solid #515151' }}>
              {restartResult.map((a, i) => <p key={i} style={{ color: a.startsWith('Error') ? '#CC4E4E' : '#6A8759' }}>{a}</p>)}
            </div>
          )}
        </div>
      )}

      {(['failed', 'autoreview', 'review', 'in_progress'].includes(status)) && (
        <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
          <button onClick={async () => {
            setRestarting(true); setRestartResult(null)
            try { const r = await restartTask(task.id); setRestartResult(r.actions); setTask({ ...task, status: 'queued' }) }
            catch (e) { setRestartResult(['Error: ' + String(e)]) }
            finally { setRestarting(false) }
          }} disabled={restarting}
            className="flex items-center gap-2 px-3 py-2 rounded text-xs font-medium disabled:opacity-50"
            style={{ background: '#CC783222', color: '#CC7832', border: '1px solid #CC7832' }}
          >{restarting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />} Full Restart</button>
          <p className="text-xs mt-1" style={{ color: '#515151' }}>Deletes branch, closes PR, resets to queue</p>
          {restartResult && (
            <div className="mt-2 p-2 rounded text-xs" style={{ background: '#1E1F22', border: '1px solid #515151' }}>
              {restartResult.map((a, i) => <p key={i} style={{ color: a.startsWith('Error') ? '#CC4E4E' : '#6A8759' }}>{a}</p>)}
            </div>
          )}
        </div>
      )}

      {/* Agent Logs */}
      <div className="pt-4" style={{ borderTop: '1px solid #3C3F41' }}>
        <div className="flex items-center justify-between mb-2">
          <button onClick={() => setShowLogs(!showLogs)}
            className="flex items-center gap-2 text-xs uppercase tracking-wider" style={{ color: '#808080' }}
          >
            <FileText className="w-3 h-3" /> Agent Logs ({logs.length})
            {showLogs ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
          <button onClick={loadLogs} disabled={logsLoading}
            className="p-1 rounded hover:bg-[#3C3F41]" style={{ color: '#808080' }}
          >
            <RefreshCw className={`w-3 h-3 ${logsLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        {showLogs && (
          <div className="rounded overflow-hidden" style={{ background: '#1E1F22', border: '1px solid #515151', maxHeight: '600px', overflowY: 'auto' }}>
            {logs.length === 0 ? (
              <p className="text-xs text-center py-4" style={{ color: '#515151' }}>{logsLoading ? 'Loading...' : 'No logs yet'}</p>
            ) : (() => {
              const blocks = groupLogsByStatus(logs)
              if (blocks.length <= 1 && blocks[0]?.status === '') return logs.map(log => <LogEntry key={log.id} log={log} />)
              return blocks.map((block, i) => (
                <div key={i}>
                  {block.status && <StatusDivider block={block} />}
                  {block.logs.map(log => <LogEntry key={log.id} log={log} />)}
                </div>
              ))
            })()}
          </div>
        )}
      </div>
    </div>
  )
}
