'use client'

import { useEffect, useState } from 'react'
import { getRelease, type Release, type ReleaseStatus } from '@/lib/api'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { ExternalLink, ArrowLeft, GitPullRequest, Loader2 } from 'lucide-react'
import { use } from 'react'

const statusColor: Record<ReleaseStatus, string> = {
  draft:            'text-[#3F3F46]',
  staging:          'text-[#F59E0B]',
  testing:          'text-[#FFC66D]',
  pending_approval: 'text-[#6366F1]',
  approved:         'text-[#6366F1]',
  deployed:         'text-[#22C55E]',
  failed:           'text-[#FF6B6B]',
  cancelled:        'text-[#71717A]',
  reverted:         'text-[#FF6B6B]',
}

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function MarkdownBlock({ content }: { content: string }) {
  const lines = content.split('\n')
  return (
    <div className="space-y-1 text-sm text-[#71717A]">
      {lines.map((line, i) => {
        if (line.startsWith('### ')) {
          return <h4 key={i} className="text-[#FAFAFA] text-xs uppercase tracking-wider mt-4 mb-2">{line.slice(4)}</h4>
        }
        if (line.startsWith('## ')) {
          return <h3 key={i} className="text-[#FAFAFA] text-sm font-semibold mt-4 mb-2">{line.slice(3)}</h3>
        }
        if (line.startsWith('# ')) {
          return <h2 key={i} className="text-[#FAFAFA] font-semibold mt-4 mb-2">{line.slice(2)}</h2>
        }
        if (line.startsWith('- ') || line.startsWith('* ')) {
          return (
            <div key={i} className="flex gap-2 items-start">
              <span className="text-[#3F3F46] mt-0.5">·</span>
              <span dangerouslySetInnerHTML={{ __html: line.slice(2).replace(/\*\*(.*?)\*\*/g, '<span class="text-[#FAFAFA]">$1</span>') }} />
            </div>
          )
        }
        if (line.startsWith('- [ ] ') || line.startsWith('- [x] ')) {
          const checked = line.startsWith('- [x]')
          return (
            <div key={i} className="flex gap-2 items-start">
              <span className={`mt-0.5 shrink-0 text-xs ${checked ? 'text-[#22C55E]' : 'text-[#3F3F46]'}`}>
                {checked ? '✓' : '○'}
              </span>
              <span className={checked ? 'line-through text-[#3F3F46]' : ''}>
                {line.replace(/^- \[.\] /, '')}
              </span>
            </div>
          )
        }
        if (line === '') return <div key={i} className="h-1" />
        return (
          <p key={i} dangerouslySetInnerHTML={{ __html: line.replace(/\*\*(.*?)\*\*/g, '<span class="text-[#FAFAFA]">$1</span>') }} />
        )
      })}
    </div>
  )
}

export default function ReleaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [release, setRelease] = useState<Release | null | undefined>(undefined)

  useEffect(() => {
    getRelease(id).then((r) => setRelease(r))
  }, [id])

  if (release === undefined) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-4 h-4 text-[#3F3F46] animate-spin" />
      </div>
    )
  }

  if (release === null) {
    notFound()
    return null
  }

  const canDeployStaging = release.status === 'draft'
  const canApprove = release.status === 'staging'
  const canDeployProd = release.status === 'approved'

  return (
    <div className="space-y-8 max-w-3xl">
      {/* Back */}
      <Link href="/releases" className="inline-flex items-center gap-1.5 text-[#71717A] hover:text-[#FAFAFA] text-xs transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" />
        Releases
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xl text-[#FAFAFA]">{release.version}</span>
            <span className={`text-xs font-mono ${statusColor[release.status]}`}>● {release.status}</span>
          </div>
          <p className="text-xs text-[#3F3F46] mt-1">Created {formatDate(release.created_at)}</p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {canDeployStaging && (
            <button className="px-3 py-1.5 border border-[#1F1F23] text-[#71717A] hover:text-[#F59E0B] hover:border-[#F59E0B]/30 text-xs transition-colors">
              → Staging
            </button>
          )}
          {canApprove && (
            <button className="px-3 py-1.5 border border-[#1F1F23] text-[#71717A] hover:text-[#6366F1] hover:border-[#6366F1]/30 text-xs transition-colors">
              ✓ Approve
            </button>
          )}
          {canDeployProd && (
            <button className="px-3 py-1.5 border border-[#1F1F23] text-[#71717A] hover:text-[#22C55E] hover:border-[#22C55E]/30 text-xs transition-colors">
              → Production
            </button>
          )}
        </div>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-6 text-xs text-[#3F3F46] border-t border-[#1F1F23] pt-4">
        <span><span className="font-mono text-[#71717A]">{release.prs.length}</span> PRs</span>
        <span><span className="font-mono text-[#71717A]">{release.tasks.length}</span> tasks</span>
        {release.approved_by && <span>approved by <span className="text-[#71717A]">{release.approved_by}</span></span>}
        {release.staging_deployed_at && <span>staging {formatDate(release.staging_deployed_at)}</span>}
        {release.production_deployed_at && <span className="text-[#22C55E]">prod {formatDate(release.production_deployed_at)}</span>}
      </div>

      {/* Release notes */}
      <div>
        <p className="text-xs text-[#71717A] uppercase tracking-wider mb-4">Release Notes</p>
        <MarkdownBlock content={release.release_notes} />
      </div>

      {/* Testing plan */}
      <div className="border-t border-[#1F1F23] pt-6">
        <p className="text-xs text-[#71717A] uppercase tracking-wider mb-4">Testing Plan</p>
        <MarkdownBlock content={release.testing_plan} />
      </div>

      {/* Reports */}
      {(release.ba_report || release.tester_report) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 border-t border-[#1F1F23] pt-6">
          {release.ba_report && (
            <div>
              <p className="text-xs text-[#71717A] uppercase tracking-wider mb-4">BA Report</p>
              <MarkdownBlock content={release.ba_report} />
            </div>
          )}
          {release.tester_report && (
            <div>
              <p className="text-xs text-[#71717A] uppercase tracking-wider mb-4">QA Report</p>
              <MarkdownBlock content={release.tester_report} />
            </div>
          )}
        </div>
      )}

      {/* PRs */}
      <div className="border-t border-[#1F1F23] pt-6">
        <p className="text-xs text-[#71717A] uppercase tracking-wider mb-4">Pull Requests</p>
        {release.prs.length === 0 ? (
          <p className="text-xs text-[#3F3F46]">No PRs</p>
        ) : (
          <div className="divide-y divide-[#1F1F23]">
            {release.prs.map(pr => (
              <a
                key={pr.number}
                href={pr.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 py-2.5 hover:bg-white/[0.02] transition-colors group"
              >
                <span className={`text-xs ${pr.merged_at ? 'text-[#A78BFA]' : 'text-[#22C55E]'}`}>
                  <GitPullRequest className="w-3.5 h-3.5" />
                </span>
                <span className="text-xs text-[#71717A] flex-1 truncate group-hover:text-[#FAFAFA] transition-colors">
                  #{pr.number} {pr.title}
                </span>
                <span className="text-xs text-[#3F3F46]">{pr.author}</span>
                <ExternalLink className="w-3 h-3 text-[#3F3F46] group-hover:text-[#71717A] shrink-0 transition-colors" />
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
