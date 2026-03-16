'use client'

import { useEffect, useState } from 'react'
import { getReleases, type Release, type ReleaseStatus } from '@/lib/api'
import Link from 'next/link'
import { Loader2 } from 'lucide-react'

const statusColor: Record<ReleaseStatus, string> = {
  draft:    'text-[#3F3F46]',
  staging:  'text-[#F59E0B]',
  approved: 'text-[#6366F1]',
  deployed: 'text-[#22C55E]',
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
        <Loader2 className="w-4 h-4 text-[#3F3F46] animate-spin" />
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
    <div className="space-y-8 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-sm font-semibold text-[#FAFAFA]">Releases</h1>
        <p className="text-xs text-[#71717A] mt-0.5">
          {(Object.entries(counts) as [string, number][]).map(([k, v]) => v > 0 ? `${v} ${k}` : null).filter(Boolean).join(' · ')}
        </p>
      </div>

      {/* Release list */}
      <div className="divide-y divide-[#1F1F23]">
        {releases.length === 0 ? (
          <p className="text-xs text-[#3F3F46] py-8">No releases</p>
        ) : (
          releases.map(release => (
            <Link key={release.id} href={`/releases/${release.id}`}>
              <div className="flex items-center gap-4 py-3 hover:bg-white/[0.02] transition-colors px-1 cursor-pointer">
                <span className="font-mono text-sm text-[#FAFAFA] shrink-0 w-24">{release.version}</span>
                <span className={`text-xs font-mono ${statusColor[release.status]} w-16 shrink-0`}>
                  {release.status}
                </span>
                <span className="text-xs text-[#3F3F46] shrink-0">{formatDate(release.created_at)}</span>
                <span className="text-xs text-[#3F3F46] font-mono ml-auto shrink-0">{release.prs.length} PRs</span>
              </div>
            </Link>
          ))
        )}
      </div>
    </div>
  )
}
