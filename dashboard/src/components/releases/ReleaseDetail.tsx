'use client'

import { useEffect, useState } from 'react'
import { updateRelease, approveRelease, unapproveRelease, type Release, type Task, type ReleaseStatus } from '@/lib/api'
import { CheckSquare, Square, GitPullRequest, ExternalLink, Loader2 } from 'lucide-react'

interface Props {
  release: Release
  allTasks: Task[]
  onUpdated: (r: Release) => void
}

const STATUS_ORDER: ReleaseStatus[] = ['draft', 'staging', 'testing', 'approved', 'deployed']

const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  draft:           { color: '#808080',  bg: 'rgba(128,128,128,0.15)', label: 'draft'    },
  staging:         { color: '#CC7832',  bg: 'rgba(204,120,50,0.15)',  label: 'staging'  },
  testing:         { color: '#FFC66D',  bg: 'rgba(255,198,109,0.15)', label: 'testing'  },
  pending_approval:{ color: '#6A8759',  bg: 'rgba(106,135,89,0.15)',  label: 'pending'  },
  approved:        { color: '#6A8759',  bg: 'rgba(106,135,89,0.15)',  label: 'approved' },
  deployed:        { color: '#3592C4',  bg: 'rgba(53,146,196,0.15)',  label: 'deployed' },
  failed:          { color: '#FF6B6B',  bg: 'rgba(255,107,107,0.15)', label: 'failed'   },
}

function priorityColor(p: string): string {
  switch (p) {
    case 'critical': return '#FF6B6B'
    case 'high': return '#CC7832'
    case 'normal': return '#6A8759'
    case 'low': return '#808080'
    default: return '#808080'
  }
}

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

function generateTestPlan(tasks: Task[]): string[] {
  const items: string[] = []
  const seen = new Set<string>()

  for (const task of tasks) {
    const text = (task.title + ' ' + (task.description ?? '')).toLowerCase()
    if ((text.includes('frontend') || text.includes('ui') || text.includes('interface')) && !seen.has('frontend')) {
      items.push('Открыть staging и проверить UI')
      seen.add('frontend')
    }
    if ((text.includes('backend') || text.includes('api') || text.includes('endpoint')) && !seen.has('backend')) {
      items.push('Проверить API endpoints')
      seen.add('backend')
    }
    if ((text.includes('bug') || text.includes('fix') || text.includes('баг') || text.includes('ошибк')) && !seen.has('bug')) {
      items.push('Убедиться что баг исправлен')
      seen.add('bug')
    }
  }

  if (items.length === 0) {
    items.push('Провести smoke-тестирование основных функций')
  }

  items.push('Проверить логи на отсутствие ошибок')
  items.push('Убедиться что все задачи работают корректно в staging')

  return items
}

const LS_KEY = (releaseId: string) => `release_checklist_${releaseId}`

function loadChecked(releaseId: string): Set<string> {
  try {
    const raw = localStorage.getItem(LS_KEY(releaseId))
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch {
    return new Set()
  }
}

function saveChecked(releaseId: string, checked: Set<string>) {
  try {
    localStorage.setItem(LS_KEY(releaseId), JSON.stringify(Array.from(checked)))
  } catch {}
}

export default function ReleaseDetail({ release, allTasks, onUpdated }: Props) {
  const [checked, setChecked] = useState<Set<string>>(() => loadChecked(release.id))
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reload checked when release changes
  useEffect(() => {
    setChecked(loadChecked(release.id))
  }, [release.id])

  // Resolve task objects from IDs
  const taskMap = new Map(allTasks.map((t) => [t.id, t]))
  const releaseTasks = release.tasks
    .map((id) => taskMap.get(id))
    .filter(Boolean) as Task[]

  const checkedCount = releaseTasks.filter((t) => checked.has(t.id)).length
  const totalCount = releaseTasks.length
  const progressPct = totalCount > 0 ? Math.round((checkedCount / totalCount) * 100) : 0

  function toggleChecked(taskId: string) {
    const next = new Set(checked)
    if (next.has(taskId)) {
      next.delete(taskId)
    } else {
      next.add(taskId)
    }
    setChecked(next)
    saveChecked(release.id, next)
  }

  const testPlan = generateTestPlan(releaseTasks)

  const cfg = statusConfig[release.status] ?? statusConfig.draft

  async function handleAction(action: 'staging' | 'approve' | 'unapprove' | 'production') {
    setActionLoading(true)
    setError(null)
    try {
      let updated: Release
      if (action === 'staging') {
        updated = await updateRelease(release.id, { status: 'staging' })
      } else if (action === 'approve') {
        updated = await approveRelease(release.id)
      } else if (action === 'unapprove') {
        updated = await unapproveRelease(release.id)
      } else {
        updated = await updateRelease(release.id, { status: 'deployed' })
      }
      onUpdated(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed')
    } finally {
      setActionLoading(false)
    }
  }

  const canDeployStaging = release.status === 'draft'
  const canApprove = release.status === 'staging' || release.status === 'testing'
  const canUnapprove = release.status === 'approved' || release.status === 'staging' || release.status === 'testing'
  const canDeployProd = release.status === 'approved'

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div
        className="p-5"
        style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xl font-bold font-mono" style={{ color: '#FFC66D' }}>
                {release.version}
              </span>
              <span
                className="text-xs font-medium px-2 py-0.5 font-mono"
                style={{ color: cfg.color, background: cfg.bg, borderRadius: '3px' }}
              >
                {cfg.label}
              </span>
            </div>
            <p className="text-xs" style={{ color: '#808080' }}>
              Создан {formatDate(release.created_at)}
            </p>

            {/* Status pipeline */}
            <div className="flex items-center gap-1 mt-3">
              {STATUS_ORDER.map((s, i) => {
                const sCfg = statusConfig[s] ?? statusConfig.draft
                const isCurrent = release.status === s
                const isPast = STATUS_ORDER.indexOf(release.status as ReleaseStatus) > i
                return (
                  <div key={s} className="flex items-center gap-1">
                    <span
                      className="text-xs px-1.5 py-0.5 font-mono"
                      style={{
                        color: isCurrent ? sCfg.color : isPast ? '#6A8759' : '#515151',
                        fontWeight: isCurrent ? 'bold' : 'normal',
                      }}
                    >
                      {sCfg.label}
                    </span>
                    {i < STATUS_ORDER.length - 1 && (
                      <span style={{ color: '#515151', fontSize: '10px' }}>→</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Tasks section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs uppercase tracking-wider font-medium" style={{ color: '#808080' }}>
            Задачи в релизе
          </h2>
          <span className="text-xs font-mono" style={{ color: '#808080' }}>
            {checkedCount}/{totalCount} проверено
          </span>
        </div>

        {/* Progress bar */}
        {totalCount > 0 && (
          <div
            className="h-1 mb-4 rounded-full overflow-hidden"
            style={{ background: '#515151' }}
          >
            <div
              className="h-full transition-all duration-300"
              style={{
                width: `${progressPct}%`,
                background: progressPct === 100 ? '#6A8759' : '#3592C4',
              }}
            />
          </div>
        )}

        <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
          {releaseTasks.length === 0 ? (
            <p className="text-xs text-center py-6" style={{ color: '#808080' }}>
              Нет задач в релизе
            </p>
          ) : (
            releaseTasks.map((task, idx) => (
              <div
                key={task.id}
                className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                style={{
                  background: checked.has(task.id) ? 'rgba(106,135,89,0.08)' : '#3C3F41',
                  borderBottom: idx < releaseTasks.length - 1 ? '1px solid #515151' : 'none',
                }}
                onClick={() => toggleChecked(task.id)}
                onMouseEnter={(e) => {
                  if (!checked.has(task.id))
                    (e.currentTarget as HTMLDivElement).style.background = '#414345'
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.background = checked.has(task.id)
                    ? 'rgba(106,135,89,0.08)' : '#3C3F41'
                }}
              >
                {checked.has(task.id) ? (
                  <CheckSquare className="w-4 h-4 shrink-0" style={{ color: '#6A8759' }} />
                ) : (
                  <Square className="w-4 h-4 shrink-0" style={{ color: '#515151' }} />
                )}
                <span
                  className="text-sm flex-1 truncate"
                  style={{
                    color: checked.has(task.id) ? '#6A8759' : '#A9B7C6',
                    textDecoration: checked.has(task.id) ? 'line-through' : 'none',
                  }}
                >
                  {task.title}
                </span>
                {task.repo && (
                  <span
                    className="text-xs px-1.5 py-0.5 font-mono shrink-0"
                    style={{
                      background: 'rgba(81,81,81,0.4)',
                      border: '1px solid #515151',
                      borderRadius: '3px',
                      color: '#808080',
                    }}
                  >
                    {task.repo}
                  </span>
                )}
                <span
                  className="text-xs px-1.5 py-0.5 font-mono shrink-0"
                  style={{
                    background: `${priorityColor(task.priority)}22`,
                    border: `1px solid ${priorityColor(task.priority)}44`,
                    borderRadius: '3px',
                    color: priorityColor(task.priority),
                  }}
                >
                  {task.priority}
                </span>
                {task.pr_number && (
                  <a
                    href={`#pr-${task.pr_number}`}
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1 text-xs shrink-0"
                    style={{ color: '#3592C4' }}
                  >
                    <GitPullRequest className="w-3 h-3" />
                    #{task.pr_number}
                  </a>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Test plan */}
      <div>
        <h2 className="text-xs uppercase tracking-wider font-medium mb-3" style={{ color: '#808080' }}>
          Что проверить
        </h2>
        <div
          className="p-4 space-y-2"
          style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
        >
          {testPlan.map((item, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-xs mt-0.5 shrink-0 font-mono" style={{ color: '#3592C4' }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              <span className="text-sm" style={{ color: '#A9B7C6' }}>{item}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Reports */}
      <div>
        <h2 className="text-xs uppercase tracking-wider font-medium mb-3" style={{ color: '#808080' }}>
          Отчёты
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div
            className="p-4"
            style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
          >
            <p className="text-xs font-medium mb-2" style={{ color: '#FFC66D' }}>BA Report</p>
            <p className="text-xs" style={{ color: '#515151', fontStyle: 'italic' }}>
              — будет заполняться
            </p>
          </div>
          <div
            className="p-4"
            style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
          >
            <p className="text-xs font-medium mb-2" style={{ color: '#FFC66D' }}>QA Report</p>
            <p className="text-xs" style={{ color: '#515151', fontStyle: 'italic' }}>
              — будет заполняться
            </p>
          </div>
        </div>
      </div>

      {error && (
        <p className="text-xs" style={{ color: '#FF6B6B' }}>{error}</p>
      )}

      {/* Action buttons */}
      {(canDeployStaging || canApprove || canDeployProd) && (
        <div
          className="flex items-center gap-3 p-4"
          style={{ background: '#2B2B2B', border: '1px solid #515151', borderRadius: '4px' }}
        >
          {actionLoading && (
            <Loader2 className="w-4 h-4 animate-spin shrink-0" style={{ color: '#808080' }} />
          )}

          {canDeployStaging && (
            <button
              onClick={() => handleAction('staging')}
              disabled={actionLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium transition-opacity"
              style={{
                background: '#CC7832',
                color: '#FFFFFF',
                borderRadius: '4px',
                opacity: actionLoading ? 0.6 : 1,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
              }}
            >
              🚀 Deploy to Staging
            </button>
          )}

          {canApprove && (
            <button
              onClick={() => handleAction('approve')}
              disabled={actionLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium transition-opacity"
              style={{
                background: '#6A8759',
                color: '#FFFFFF',
                borderRadius: '4px',
                opacity: actionLoading ? 0.6 : 1,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
              }}
            >
              ✅ Approve
            </button>
          )}

          {canDeployProd && (
            <button
              onClick={() => handleAction('production')}
              disabled={actionLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium transition-opacity"
              style={{
                background: '#3592C4',
                color: '#FFFFFF',
                borderRadius: '4px',
                opacity: actionLoading ? 0.6 : 1,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
              }}
            >
              🚀 Deploy to Production
            </button>
          )}
        </div>
      )}
    </div>
  )
}
