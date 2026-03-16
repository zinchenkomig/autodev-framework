'use client'

import { useEffect, useState } from 'react'
import { getReleases, type Release, type ReleaseStatus } from '@/lib/api'
import Link from 'next/link'
import { Tag, GitPullRequest, Calendar, ChevronRight, Loader2 } from 'lucide-react'

const statusConfig: Record<ReleaseStatus, { label: string; className: string; dot: string }> = {
  draft: { label: 'Draft', className: 'bg-gray-500/20 text-gray-400 border border-gray-500/30', dot: 'bg-gray-400' },
  staging: { label: 'Staging', className: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30', dot: 'bg-yellow-400 animate-pulse' },
  approved: { label: 'Approved', className: 'bg-blue-500/20 text-blue-400 border border-blue-500/30', dot: 'bg-blue-400' },
  deployed: { label: 'Deployed', className: 'bg-green-500/20 text-green-400 border border-green-500/30', dot: 'bg-green-400' },
}

function ReleaseBadge({ status }: { status: ReleaseStatus }) {
  const config = statusConfig[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  )
}

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function ReleaseCard({ release }: { release: Release }) {
  return (
    <Link href={`/releases/${release.id}`}>
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 hover:bg-gray-900/80 transition-all cursor-pointer group">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <div className="p-2 rounded-lg bg-gray-800 border border-gray-700 shrink-0 mt-0.5">
              <Tag className="w-4 h-4 text-blue-400" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-white font-semibold font-mono">{release.version}</h3>
                <ReleaseBadge status={release.status} />
              </div>
              <p className="text-gray-400 text-sm mt-1 line-clamp-2">
                {release.release_notes.split('\n').find(l => l.startsWith('###'))?.replace('### ', '') ?? 'No description'}
              </p>
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 transition-colors shrink-0 mt-1" />
        </div>

        {/* Meta row – wraps on very small screens */}
        <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            <GitPullRequest className="w-3.5 h-3.5" />
            {release.prs.length} PR{release.prs.length !== 1 ? 's' : ''}
          </span>
          <span className="flex items-center gap-1.5">
            <Calendar className="w-3.5 h-3.5" />
            Created {formatDate(release.created_at)}
          </span>
          {release.staging_deployed_at && (
            <span className="text-yellow-500/70">
              Staging: {formatDate(release.staging_deployed_at)}
            </span>
          )}
          {release.production_deployed_at && (
            <span className="text-green-500/70">
              Prod: {formatDate(release.production_deployed_at)}
            </span>
          )}
        </div>
      </div>
    </Link>
  )
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
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    )
  }

  const counts = {
    draft: releases.filter(r => r.status === 'draft').length,
    staging: releases.filter(r => r.status === 'staging').length,
    approved: releases.filter(r => r.status === 'approved').length,
    deployed: releases.filter(r => r.status === 'deployed').length,
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-white">Releases</h2>
        <p className="text-gray-400 text-sm mt-1">Manage and track software releases</p>
      </div>

      {/* Status summary – 2 cols on mobile, 4 on sm */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {(Object.entries(counts) as [ReleaseStatus, number][]).map(([status, count]) => (
          <div key={status} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-gray-400 text-sm capitalize">{status}</span>
              <ReleaseBadge status={status} />
            </div>
            <p className="text-2xl font-bold text-white mt-2">{count}</p>
          </div>
        ))}
      </div>

      {/* Release list – 1 col (cards stack vertically already) */}
      <div className="space-y-3">
        {releases.length === 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
            <Tag className="w-8 h-8 text-gray-600 mx-auto mb-3" />
            <p className="text-gray-500">No releases yet.</p>
          </div>
        ) : (
          releases.map(release => (
            <ReleaseCard key={release.id} release={release} />
          ))
        )}
      </div>
    </div>
  )
}
