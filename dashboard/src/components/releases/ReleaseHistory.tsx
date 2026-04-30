'use client'

import Link from 'next/link'
import { Package, ChevronRight } from 'lucide-react'
import type { Release, ReleaseStatus } from '@/lib/api'

interface Props {
  releases: Release[]
}

const statusConfig: Record<ReleaseStatus, { color: string; bg: string; label: string }> = {
  draft:            { color: '#808080', bg: 'rgba(128,128,128,0.15)', label: 'draft' },
  staging:          { color: '#CC7832', bg: 'rgba(204,120,50,0.15)',  label: 'staging' },
  testing:          { color: '#FFC66D', bg: 'rgba(255,198,109,0.15)', label: 'testing' },
  pending_approval: { color: '#6A8759', bg: 'rgba(106,135,89,0.15)',  label: 'pending' },
  approved:         { color: '#6A8759', bg: 'rgba(106,135,89,0.15)',  label: 'approved' },
  deployed:         { color: '#3592C4', bg: 'rgba(53,146,196,0.15)',  label: 'deployed' },
  failed:           { color: '#FF6B6B', bg: 'rgba(255,107,107,0.15)', label: 'failed' },
  cancelled:        { color: '#808080', bg: 'rgba(128,128,128,0.15)', label: 'cancelled' },
  reverted:         { color: '#FF6B6B', bg: 'rgba(255,107,107,0.15)', label: 'reverted' },
}

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export default function ReleaseHistory({ releases }: Props) {
  const sorted = [...releases].sort((a, b) => {
    const ad = a.production_deployed_at ?? a.staging_deployed_at ?? a.created_at
    const bd = b.production_deployed_at ?? b.staging_deployed_at ?? b.created_at
    return new Date(bd).getTime() - new Date(ad).getTime()
  })

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs uppercase tracking-wider" style={{ color: '#808080' }}>
          История релизов
        </h2>
        <span className="text-xs" style={{ color: '#515151' }}>
          {sorted.length} {sorted.length === 1 ? 'релиз' : 'релизов'}
        </span>
      </div>

      {sorted.length === 0 ? (
        <div
          className="py-10 text-center"
          style={{ background: '#3C3F41', border: '1px solid #515151', borderRadius: '4px' }}
        >
          <Package className="w-6 h-6 mx-auto mb-2" style={{ color: '#515151' }} />
          <p className="text-xs" style={{ color: '#808080' }}>Релизов ещё не было</p>
        </div>
      ) : (
        <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
          {sorted.map((r, idx) => {
            const cfg = statusConfig[r.status]
            const deployedAt = r.production_deployed_at
            const stagingAt = r.staging_deployed_at
            return (
              <Link
                key={r.id}
                href={`/releases/${r.id}`}
                className="flex items-center gap-3 px-4 py-3 transition-colors group"
                style={{
                  background: '#3C3F41',
                  borderBottom: idx < sorted.length - 1 ? '1px solid #515151' : 'none',
                }}
                onMouseEnter={(e) => {
                  ;(e.currentTarget as HTMLAnchorElement).style.background = '#414345'
                }}
                onMouseLeave={(e) => {
                  ;(e.currentTarget as HTMLAnchorElement).style.background = '#3C3F41'
                }}
              >
                <span
                  className="font-mono text-sm shrink-0"
                  style={{ color: '#FFC66D', minWidth: '140px' }}
                >
                  {r.version}
                </span>

                <span
                  className="text-xs px-1.5 py-0.5 font-mono shrink-0"
                  style={{
                    background: cfg.bg,
                    border: `1px solid ${cfg.color}44`,
                    borderRadius: '3px',
                    color: cfg.color,
                  }}
                >
                  {cfg.label}
                </span>

                <div className="flex items-center gap-4 flex-1 text-xs" style={{ color: '#808080' }}>
                  <span>
                    <span className="font-mono" style={{ color: '#A9B7C6' }}>{r.tasks.length}</span>{' '}
                    {r.tasks.length === 1 ? 'task' : 'tasks'}
                  </span>
                  <span>
                    <span className="font-mono" style={{ color: '#A9B7C6' }}>{r.prs.length}</span>{' '}
                    PRs
                  </span>
                  {deployedAt ? (
                    <span style={{ color: '#6A8759' }}>prod {formatDate(deployedAt)}</span>
                  ) : stagingAt ? (
                    <span style={{ color: '#CC7832' }}>staging {formatDate(stagingAt)}</span>
                  ) : (
                    <span>created {formatDate(r.created_at)}</span>
                  )}
                </div>

                <ChevronRight
                  className="w-4 h-4 shrink-0 transition-colors"
                  style={{ color: '#515151' }}
                />
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
