'use client'

import { useEffect, useState } from 'react'
import { getReleases, type Release, type ReleaseStatus } from '@/lib/api'
import Link from 'next/link'
import { Loader2, GitBranch } from 'lucide-react'

const statusConfig: Record<ReleaseStatus, { color: string; bg: string; label: string }> = {
  draft:    { color: '#808080', bg: 'rgba(128,128,128,0.15)', label: 'draft'    },
  staging:  { color: '#CC7832', bg: 'rgba(204,120,50,0.15)',  label: 'staging'  },
  approved: { color: '#6A8759', bg: 'rgba(106,135,89,0.15)',  label: 'approved' },
  deployed: { color: '#3592C4', bg: 'rgba(53,146,196,0.15)',  label: 'deployed' },
}

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export default function ReleasesPage() {
  const [releases, setReleases] = useState<Release[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getReleases().then((r) => {
      setReleases(r)
      setLoading(false)
    })
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  const counts = {
    draft:    releases.filter(r => r.status === 'draft').length,
    staging:  releases.filter(r => r.status === 'staging').length,
    approved: releases.filter(r => r.status === 'approved').length,
    deployed: releases.filter(r => r.status === 'deployed').length,
  }

  return (
    <div className="space-y-8 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: '#FFFFFF' }}>Releases</h1>
        <p className="text-xs mt-0.5" style={{ color: '#808080' }}>
          {(Object.entries(counts) as [string, number][]).map(([k, v]) => v > 0 ? `${v} ${k}` : null).filter(Boolean).join(' · ')}
        </p>
      </div>

      {/* Summary badges */}
      <div className="flex flex-wrap gap-3">
        {(Object.entries(statusConfig) as [ReleaseStatus, typeof statusConfig[ReleaseStatus]][]).map(([status, cfg]) => (
          counts[status] > 0 && (
            <div
              key={status}
              className="flex items-center gap-2 px-3 py-2"
              style={{
                background: cfg.bg,
                border: `1px solid ${cfg.color}40`,
                borderRadius: '4px',
              }}
            >
              <span style={{ color: cfg.color, fontSize: '8px' }}>●</span>
              <span className="text-xs" style={{ color: cfg.color }}>{cfg.label}</span>
              <span className="text-sm font-bold font-mono" style={{ color: '#FFFFFF' }}>{counts[status]}</span>
            </div>
          )
        ))}
      </div>

      {/* Release list */}
      <div style={{ border: '1px solid #515151', borderRadius: '4px', overflow: 'hidden' }}>
        {releases.length === 0 ? (
          <p className="text-xs text-center py-8" style={{ color: '#808080' }}>No releases</p>
        ) : (
          releases.map((release, idx) => {
            const cfg = statusConfig[release.status]
            return (
              <Link key={release.id} href={`/releases/${release.id}`}>
                <div
                  className="flex items-center gap-4 px-4 py-3.5 transition-colors cursor-pointer"
                  style={{
                    background: '#3C3F41',
                    borderBottom: idx < releases.length - 1 ? '1px solid #515151' : 'none',
                  }}
                  onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.background = '#414345'}
                  onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.background = '#3C3F41'}
                >
                  <div className="flex items-center gap-2 shrink-0">
                    <GitBranch className="w-4 h-4" style={{ color: '#808080' }} />
                    <span className="font-mono text-sm font-bold" style={{ color: '#FFC66D' }}>{release.version}</span>
                  </div>
                  <span
                    className="text-xs font-medium px-2 py-0.5 rounded font-mono shrink-0"
                    style={{ color: cfg.color, background: cfg.bg }}
                  >
                    {cfg.label}
                  </span>
                  <span className="text-xs shrink-0" style={{ color: '#808080' }}>{formatDate(release.created_at)}</span>
                  <span className="text-xs font-mono ml-auto shrink-0 flex items-center gap-1" style={{ color: '#808080' }}>
                    <GitBranch className="w-3 h-3" />
                    {release.prs.length} PRs
                  </span>
                </div>
              </Link>
            )
          })
        )}
      </div>
    </div>
  )
}
