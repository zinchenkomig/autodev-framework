'use client'

import { useState, useEffect } from 'react'
import { type Task, type TaskStatus, type TaskLog, updateTask, getTaskLogs, restartTask, requestChanges } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { X, GitPullRequest, GitBranch, ChevronDown, ChevronRight, RefreshCw, FileText, RotateCcw, Loader2 } from 'lucide-react'
import { PriorityBadge } from '@/components/Badge'

interface TaskDetailProps {
  task: Task | null
  onClose: () => void
  onStatusChange?: (taskId: string, newStatus: TaskStatus) => void
}

const STATUS_PILLS: { id: TaskStatus; label: string }[] = [
  { id: 'queued',      label: 'Queued'      },
  { id: 'in_progress', label: 'In Progress' },
  { id: 'autoreview',  label: 'Auto Review'  },
  { id: 'qa_testing',   label: 'QA Testing'   },
  { id: 'ready_to_release', label: 'Ready to Release' },
  { id: 'staging',     label: 'Staging'     },
  { id: 'released',    label: 'Released'    },
]

const STATUS_DOT: Record<TaskStatus, string> = {
  queued:      '#808080',
  assigned:    '#9876AA',
  in_progress: '#CC7832',
  autoreview:  '#3592C4',
  qa_testing:   '#E5C07B',
  review:      '#3592C4',
  staging:     '#E5C07B',
  ready_to_release: '#9876AA',
  released:    '#6A8759',
  failed:      '#CC4E4E',
}

const levelConfig: Record<string, { color: string; label: string }> = {
  info:    { color: '#9E9E9E', label: 'INFO' },
  warning: { color: '#CC7832', label: 'WARN' },
  error:   { color: '#CC4E4E', label: 'ERR' },
}

function LogEntry({ log }: { log: TaskLog }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = levelConfig[log.level] || levelConfig.info
  const hasDetails = log.details && log.details.length > 0
  
  return (
    <div style={{ borderBottom: '1px solid #3C3F41' }}>
      <div
        className={`flex items-start gap-2 px-2 py-1.5 ${hasDetails ? 'cursor-pointer hover:bg-[#3C3F41]' : ''}`}
        onClick={() => hasDetails && setExpanded(!expanded)}
        style={{ fontSize: '11px' }}
      >
        <span style={{ color: '#515151', width: '12px', marginTop: '2px' }}>
          {hasDetails ? (expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />) : null}
        </span>
        <span className="px-1 rounded font-bold" style={{ color: cfg.color, fontSize: '10px' }}>{cfg.label}</span>
        <span className="flex-1" style={{ color: '#BABABA', wordBreak: 'break-word' }}>{log.message}</span>
      </div>
      {expanded && log.details && (
        <div 
          className="px-3 pb-2 pt-1 whitespace-pre-wrap overflow-x-auto"
          style={{ 
            background: '#1E1F22', 
            fontSize: '10px', 
            color: '#9E9E9E', 
            maxHeight: '300px',
            overflowY: 'auto',
            fontFamily: 'monospace'
          }}
        >
          {log.details}
        </div>
      )}
    </div>
  )
}

export function TaskDetail({ task, onClose, onStatusChange }: TaskDetailProps) {
  const [currentStatus, setCurrentStatus] = useState<TaskStatus | null>(null)
  const [saving, setSaving] = useState(false)
  const [logs, setLogs] = useState<TaskLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [showLogs, setShowLogs] = useState(true)
  const [restarting, setRestarting] = useState(false)
  const [restartResult, setRestartResult] = useState<string[] | null>(null)
  const [changesComment, setChangesComment] = useState('')
  const [requestingChanges, setRequestingChanges] = useState(false)
  const [changesResult, setChangesResult] = useState<string | null>(null)

  const effectiveStatus: TaskStatus = currentStatus ?? (task?.status ?? 'queued')

  useEffect(() => {
    if (task) {
      setCurrentStatus(null)
      loadLogs()
    }
  }, [task?.id])

  async function loadLogs() {
    if (!task) return
    setLogsLoading(true)
    try {
      const data = await getTaskLogs(task.id, 50)
      setLogs(data)
    } catch (e) {
      console.error('Failed to load logs', e)
    } finally {
      setLogsLoading(false)
    }
  }

  if (!task) return null

  async function handleStatusClick(status: TaskStatus) {
    if (!task || status === effectiveStatus || saving) return
    setSaving(true)
    try {
      await updateTask(task.id, { status })
      setCurrentStatus(status)
      onStatusChange?.(task.id, status)
    } catch (err) {
      console.warn('[TaskDetail] status update failed', err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40" onClick={onClose} />

      <div
        className="fixed right-0 top-0 h-full w-full md:max-w-lg z-50 flex flex-col"
        style={{ background: '#2B2B2B', borderLeft: '1px solid #515151' }}
      >
        {/* Header */}
        <div
          className="flex items-start gap-3 px-5 py-4"
          style={{ borderBottom: '1px solid #515151' }}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <PriorityBadge priority={task.priority} />
              <span 
                className="text-xs px-2 py-0.5 rounded"
                style={{ background: `${STATUS_DOT[effectiveStatus]}22`, color: STATUS_DOT[effectiveStatus] }}
              >
                {effectiveStatus}
              </span>
            </div>
            <p className="text-sm leading-snug" style={{ color: '#FFFFFF' }}>{task.title}</p>
          </div>
          <button
            onClick={onClose}
            className="transition-colors shrink-0"
            style={{ color: '#515151' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#808080')}
            onMouseLeave={e => (e.currentTarget.style.color = '#515151')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

          {/* Status picker */}
          <div>
            <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Status</p>
            <div className="flex flex-wrap gap-2">
              {STATUS_PILLS.map(({ id, label }) => {
                const isActive = effectiveStatus === id
                const dot = STATUS_DOT[id]
                return (
                  <button
                    key={id}
                    disabled={saving}
                    onClick={() => handleStatusClick(id)}
                    className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium transition-all disabled:opacity-60"
                    style={{
                      border: `1px solid ${isActive ? dot : '#515151'}`,
                      background: isActive ? `${dot}22` : 'transparent',
                      color: isActive ? dot : '#808080',
                      cursor: saving ? 'not-allowed' : isActive ? 'default' : 'pointer',
                    }}
                  >
                    <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: isActive ? dot : '#515151' }} />
                    {label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Request Changes (for ready_to_release) */}
          {effectiveStatus === 'ready_to_release' && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Feedback</p>
              <textarea
                value={changesComment}
                onChange={e => setChangesComment(e.target.value)}
                placeholder="Опиши что нужно доработать..."
                className="w-full px-3 py-2 rounded text-xs resize-none outline-none"
                rows={3}
                style={{ background: '#1E1F22', border: '1px solid #515151', color: '#BABABA' }}
              />
              <button
                onClick={async () => {
                  if (!task || !changesComment.trim()) return
                  setRequestingChanges(true)
                  setChangesResult(null)
                  try {
                    const result = await requestChanges(task.id, changesComment)
                    setChangesResult(`✅ Создана задача: ${result.followup_title}`)
                    setChangesComment('')
                  } catch (e) {
                    setChangesResult('❌ Ошибка: ' + String(e))
                  } finally {
                    setRequestingChanges(false)
                  }
                }}
                disabled={requestingChanges || !changesComment.trim()}
                className="mt-2 flex items-center gap-2 px-3 py-2 rounded text-xs font-medium transition-colors disabled:opacity-50"
                style={{ background: '#CC783222', color: '#CC7832', border: '1px solid #CC7832' }}
              >
                {requestingChanges ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Создать задачу на правки
              </button>
              {changesResult && (
                <p className="text-xs mt-2" style={{ color: changesResult.startsWith('✅') ? '#6A8759' : '#CC4E4E' }}>
                  {changesResult}
                </p>
              )}
            </div>
          )}

          {/* Actions */}
          {(effectiveStatus === 'failed' || effectiveStatus === 'autoreview' || effectiveStatus === 'review' || effectiveStatus === 'in_progress') && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Actions</p>
              <button
                onClick={async () => {
                  if (!task) return
                  setRestarting(true)
                  setRestartResult(null)
                  try {
                    const result = await restartTask(task.id)
                    setRestartResult(result.actions)
                    setCurrentStatus('queued')
                    onStatusChange?.(task.id, 'queued')
                  } catch (e) {
                    setRestartResult(['Error: ' + String(e)])
                  } finally {
                    setRestarting(false)
                  }
                }}
                disabled={restarting}
                className="flex items-center gap-2 px-3 py-2 rounded text-xs font-medium transition-colors disabled:opacity-50"
                style={{ background: '#CC783222', color: '#CC7832', border: '1px solid #CC7832' }}
              >
                {restarting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                Full Restart
              </button>
              <p className="text-xs mt-1" style={{ color: '#515151' }}>
                Deletes branch, closes PR, resets to queue
              </p>
              {restartResult && (
                <div className="mt-2 p-2 rounded text-xs" style={{ background: '#1E1F22', border: '1px solid #515151' }}>
                  {restartResult.map((action, i) => (
                    <p key={i} style={{ color: action.startsWith('Error') ? '#CC4E4E' : '#6A8759' }}>{action}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Description */}
          {task.description && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-1" style={{ color: '#808080' }}>Description</p>
              <p className="text-xs leading-relaxed" style={{ color: '#BABABA' }}>{task.description}</p>
            </div>
          )}

          {/* Details */}
          <div>
            <p className="text-xs uppercase tracking-wider mb-2" style={{ color: '#808080' }}>Details</p>
            <div className="rounded p-2 space-y-1" style={{ background: '#3C3F41', border: '1px solid #515151' }}>
              {[
                ['Repository', task.repo],
                ['Created by', task.created_by],
                ['Created', formatDistanceToNow(task.created_at)],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: '#515151' }}>{label}</span>
                  <span className="text-xs font-mono" style={{ color: '#808080' }}>{value}</span>
                </div>
              ))}

              {task.depends_on && task.depends_on.length > 0 && (
                <div className="flex items-center justify-between pt-1" style={{ borderTop: '1px solid #515151' }}>
                  <span className="text-xs" style={{ color: '#515151' }}>Depends on</span>
                  <span className="text-xs font-mono" style={{ color: '#CC7832' }}>{task.depends_on.length} task(s)</span>
                </div>
              )}

              {task.branch && (
                <div className="flex items-center justify-between pt-1" style={{ borderTop: '1px solid #515151' }}>
                  <span className="text-xs" style={{ color: '#515151' }}>Branch</span>
                  <a href={`https://github.com/${task.repo}/tree/${task.branch}`} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs font-mono hover:opacity-80" style={{ color: '#9876AA' }}>
                    <GitBranch className="w-3 h-3" /> {task.branch.slice(0, 20)}...
                  </a>
                </div>
              )}

              {task.pr_url && (
                <div className="flex items-center justify-between pt-1" style={{ borderTop: '1px solid #515151' }}>
                  <span className="text-xs" style={{ color: '#515151' }}>Pull Request</span>
                  <a href={task.pr_url} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs hover:opacity-80" style={{ color: '#6A8759' }}>
                    <GitPullRequest className="w-3 h-3" /> View PR
                  </a>
                </div>
              )}
            </div>
          </div>

          {/* Agent Logs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <button 
                onClick={() => setShowLogs(!showLogs)}
                className="flex items-center gap-2 text-xs uppercase tracking-wider"
                style={{ color: '#808080' }}
              >
                <FileText className="w-3 h-3" />
                Agent Logs ({logs.length})
                {showLogs ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              </button>
              <button 
                onClick={loadLogs} 
                disabled={logsLoading}
                className="p-1 rounded hover:bg-[#3C3F41]"
                style={{ color: '#808080' }}
              >
                <RefreshCw className={`w-3 h-3 ${logsLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>
            
            {showLogs && (
              <div 
                className="rounded overflow-hidden"
                style={{ background: '#1E1F22', border: '1px solid #515151', maxHeight: '400px', overflowY: 'auto' }}
              >
                {logs.length === 0 ? (
                  <p className="text-xs text-center py-4" style={{ color: '#515151' }}>
                    {logsLoading ? 'Loading...' : 'No logs yet'}
                  </p>
                ) : (
                  logs.map(log => <LogEntry key={log.id} log={log} />)
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
