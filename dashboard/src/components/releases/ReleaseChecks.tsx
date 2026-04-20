'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  getReleaseChecks, type CheckRun, type ReleasePRChecks,
} from '@/lib/api'
import {
  CheckCircle, XCircle, Loader2, Clock, MinusCircle,
  GitPullRequest, ExternalLink, RefreshCw,
} from 'lucide-react'

interface Props {
  releaseId: string
}

function checkStyle(c: CheckRun): { color: string; bg: string; icon: typeof CheckCircle } {
  if (c.status !== 'completed') {
    return { color: '#FFC66D', bg: 'rgba(255,198,109,0.12)', icon: Clock }
  }
  switch (c.conclusion) {
    case 'success':
      return { color: '#6A8759', bg: 'rgba(106,135,89,0.12)', icon: CheckCircle }
    case 'failure':
    case 'timed_out':
    case 'action_required':
      return { color: '#FF6B6B', bg: 'rgba(255,107,107,0.12)', icon: XCircle }
    case 'cancelled':
    case 'skipped':
    case 'stale':
    case 'neutral':
    default:
      return { color: '#808080', bg: 'rgba(128,128,128,0.12)', icon: MinusCircle }
  }
}

export default function ReleaseChecks({ releaseId }: Props) {
  const [data, setData] = useState<ReleasePRChecks[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getReleaseChecks(releaseId)
      setData(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load checks')
    } finally {
      setLoading(false)
    }
  }, [releaseId])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs uppercase tracking-wider font-medium" style={{ color: '#808080' }}>
          CI Checks
        </h2>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs"
          style={{ color: loading ? '#515151' : '#808080', cursor: loading ? 'default' : 'pointer' }}
        >
          {loading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          Обновить
        </button>
      </div>

      {error && (
        <p className="text-xs" style={{ color: '#FF6B6B' }}>{error}</p>
      )}

      {!error && data && data.length === 0 && !loading && (
        <p className="text-xs" style={{ color: '#515151' }}>Нет PR с проверками</p>
      )}

      {data && data.length > 0 && (
        <div
          className="divide-y"
          style={{ border: '1px solid #515151', borderRadius: '4px', background: '#3C3F41' }}
        >
          {data.map((row, i) => (
            <div key={`${row.source}-${row.repo}-${row.pr_number}-${i}`} className="p-3" style={{ borderColor: '#515151' }}>
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <span
                  className="text-[10px] uppercase tracking-wider font-mono px-1.5 py-0.5"
                  style={{
                    color: row.source === 'release_pr' ? '#A78BFA' : '#3592C4',
                    background: row.source === 'release_pr' ? 'rgba(167,139,250,0.12)' : 'rgba(53,146,196,0.12)',
                    borderRadius: '3px',
                  }}
                >
                  {row.source === 'release_pr' ? 'release' : 'task'}
                </span>
                <span className="text-xs font-mono" style={{ color: '#A9B7C6' }}>
                  {row.repo}
                </span>
                <a
                  href={row.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs"
                  style={{ color: '#3592C4' }}
                >
                  <GitPullRequest className="w-3 h-3" />
                  #{row.pr_number}
                  <ExternalLink className="w-3 h-3" />
                </a>
                {row.task_id && (
                  <Link
                    href={`/tasks/${row.task_id}`}
                    className="text-xs truncate hover:underline"
                    style={{ color: '#808080', maxWidth: '260px' }}
                  >
                    {row.task_title}
                  </Link>
                )}
              </div>

              {row.checks.length === 0 ? (
                <p className="text-xs" style={{ color: '#515151' }}>Нет проверок</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {row.checks.map((c, j) => {
                    const s = checkStyle(c)
                    const Icon = s.icon
                    const label = c.name || 'check'
                    const body = (
                      <span
                        className="inline-flex items-center gap-1 text-xs font-mono px-1.5 py-0.5"
                        style={{
                          color: s.color,
                          background: s.bg,
                          border: `1px solid ${s.color}33`,
                          borderRadius: '3px',
                        }}
                      >
                        <Icon className="w-3 h-3" />
                        {label}
                      </span>
                    )
                    return c.url ? (
                      <a
                        key={j}
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`${c.name} — ${c.conclusion ?? c.status}`}
                      >
                        {body}
                      </a>
                    ) : (
                      <span key={j} title={`${c.name} — ${c.conclusion ?? c.status}`}>
                        {body}
                      </span>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
