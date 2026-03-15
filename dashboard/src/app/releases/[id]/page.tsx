import { getRelease, type ReleaseStatus } from '@/lib/api'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import {
  Tag, GitPullRequest, CheckCircle, Clock, Rocket,
  ArrowLeft, ExternalLink, FileText, TestTube, User,
  ChevronRight, Circle
} from 'lucide-react'

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
  return new Date(dateString).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function MarkdownBlock({ content }: { content: string }) {
  // Minimal markdown renderer: handles ### h3, ## h2, # h1, **, -, ✅, ⚠️
  const lines = content.split('\n')
  return (
    <div className="space-y-1 text-sm text-gray-300">
      {lines.map((line, i) => {
        if (line.startsWith('### ')) {
          return <h4 key={i} className="text-white font-semibold mt-3 mb-1">{line.slice(4)}</h4>
        }
        if (line.startsWith('## ')) {
          return <h3 key={i} className="text-white font-bold text-base mt-4 mb-1">{line.slice(3)}</h3>
        }
        if (line.startsWith('# ')) {
          return <h2 key={i} className="text-white font-bold text-lg mt-4 mb-2">{line.slice(2)}</h2>
        }
        if (line.startsWith('- ') || line.startsWith('* ')) {
          return (
            <div key={i} className="flex gap-2 items-start">
              <span className="text-gray-600 mt-0.5">•</span>
              <span dangerouslySetInnerHTML={{ __html: line.slice(2).replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>') }} />
            </div>
          )
        }
        if (line.startsWith('- [ ] ') || line.startsWith('- [x] ')) {
          const checked = line.startsWith('- [x]')
          return (
            <div key={i} className="flex gap-2 items-start">
              <span className={`mt-0.5 shrink-0 ${checked ? 'text-green-400' : 'text-gray-600'}`}>
                {checked ? '✅' : '☐'}
              </span>
              <span className={checked ? 'line-through text-gray-500' : ''}>
                {line.replace(/^- \[.\] /, '')}
              </span>
            </div>
          )
        }
        if (line === '') return <div key={i} className="h-1" />
        return (
          <p key={i} dangerouslySetInnerHTML={{ __html: line.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>') }} />
        )
      })}
    </div>
  )
}

type TimelineStep = {
  key: string
  label: string
  icon: React.ElementType
  date: string | null
  active: boolean
  done: boolean
}

export default async function ReleaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const release = await getRelease(id)
  if (!release) notFound()

  const timelineSteps: TimelineStep[] = [
    {
      key: 'created',
      label: 'Created',
      icon: Tag,
      date: release.created_at,
      done: true,
      active: release.status === 'draft',
    },
    {
      key: 'staging',
      label: 'Deployed to Staging',
      icon: Rocket,
      date: release.staging_deployed_at,
      done: !!release.staging_deployed_at,
      active: release.status === 'staging',
    },
    {
      key: 'tested',
      label: 'QA Tested',
      icon: TestTube,
      date: release.tester_report ? release.staging_deployed_at : null,
      done: !!release.tester_report,
      active: release.status === 'staging' && !!release.tester_report,
    },
    {
      key: 'approved',
      label: 'Approved',
      icon: CheckCircle,
      date: release.approved_by ? release.staging_deployed_at : null,
      done: !!release.approved_by,
      active: release.status === 'approved',
    },
    {
      key: 'deployed',
      label: 'Deployed to Production',
      icon: Rocket,
      date: release.production_deployed_at,
      done: !!release.production_deployed_at,
      active: release.status === 'deployed',
    },
  ]

  const canDeployStaging = release.status === 'draft'
  const canApprove = release.status === 'staging'
  const canDeployProd = release.status === 'approved'

  return (
    <div className="space-y-6">
      {/* Back nav */}
      <Link href="/releases" className="inline-flex items-center gap-1.5 text-gray-400 hover:text-white text-sm transition-colors">
        <ArrowLeft className="w-4 h-4" />
        Back to Releases
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-xl bg-gray-800 border border-gray-700">
            <Tag className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-2xl font-bold text-white font-mono">{release.version}</h2>
              <ReleaseBadge status={release.status} />
            </div>
            <p className="text-gray-400 text-sm mt-1">Created {formatDate(release.created_at)}</p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          {canDeployStaging && (
            <button className="flex items-center gap-2 px-4 py-2 bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg text-sm hover:bg-yellow-500/20 transition-colors">
              <Rocket className="w-4 h-4" />
              Deploy to Staging
            </button>
          )}
          {canApprove && (
            <button className="flex items-center gap-2 px-4 py-2 bg-blue-500/10 border border-blue-500/30 text-blue-400 rounded-lg text-sm hover:bg-blue-500/20 transition-colors">
              <CheckCircle className="w-4 h-4" />
              Approve
            </button>
          )}
          {canDeployProd && (
            <button className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg text-sm hover:bg-green-500/20 transition-colors">
              <Rocket className="w-4 h-4" />
              Deploy to Production
            </button>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-white font-semibold mb-5">Timeline</h3>
        <div className="flex items-start gap-0 overflow-x-auto pb-2">
          {timelineSteps.map((step, index) => {
            const Icon = step.icon
            const isLast = index === timelineSteps.length - 1
            return (
              <div key={step.key} className="flex items-center flex-shrink-0">
                <div className="flex flex-col items-center">
                  <div className={`p-2 rounded-full border ${
                    step.done
                      ? 'bg-green-500/20 border-green-500/40 text-green-400'
                      : step.active
                      ? 'bg-yellow-500/20 border-yellow-500/40 text-yellow-400'
                      : 'bg-gray-800 border-gray-700 text-gray-600'
                  }`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="mt-2 text-center">
                    <p className={`text-xs font-medium whitespace-nowrap ${
                      step.done ? 'text-white' : step.active ? 'text-yellow-400' : 'text-gray-600'
                    }`}>
                      {step.label}
                    </p>
                    {step.date && (
                      <p className="text-xs text-gray-500 mt-0.5 whitespace-nowrap">
                        {new Date(step.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      </p>
                    )}
                  </div>
                </div>
                {!isLast && (
                  <div className={`w-16 h-px mx-1 mb-6 ${
                    step.done ? 'bg-green-500/40' : 'bg-gray-700'
                  }`} />
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left column: notes + testing plan */}
        <div className="xl:col-span-2 space-y-6">
          {/* Release notes */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
              <FileText className="w-4 h-4 text-gray-400" />
              <h3 className="text-white font-semibold">Release Notes</h3>
            </div>
            <div className="p-5">
              <MarkdownBlock content={release.release_notes} />
            </div>
          </div>

          {/* Testing plan */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
              <TestTube className="w-4 h-4 text-gray-400" />
              <h3 className="text-white font-semibold">Testing Plan</h3>
            </div>
            <div className="p-5">
              <MarkdownBlock content={release.testing_plan} />
            </div>
          </div>

          {/* Reports row */}
          {(release.ba_report || release.tester_report) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {release.ba_report && (
                <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                  <div className="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
                    <User className="w-4 h-4 text-purple-400" />
                    <h3 className="text-white font-semibold">BA Report</h3>
                  </div>
                  <div className="p-5">
                    <MarkdownBlock content={release.ba_report} />
                  </div>
                </div>
              )}
              {release.tester_report && (
                <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                  <div className="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
                    <TestTube className="w-4 h-4 text-green-400" />
                    <h3 className="text-white font-semibold">QA Report</h3>
                  </div>
                  <div className="p-5">
                    <MarkdownBlock content={release.tester_report} />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right column: PRs */}
        <div className="space-y-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
              <GitPullRequest className="w-4 h-4 text-gray-400" />
              <h3 className="text-white font-semibold">Pull Requests</h3>
              <span className="ml-auto text-xs text-gray-500">{release.prs.length}</span>
            </div>
            <div className="divide-y divide-gray-800">
              {release.prs.length === 0 ? (
                <p className="p-5 text-gray-500 text-sm">No PRs yet.</p>
              ) : (
                release.prs.map(pr => (
                  <a
                    key={pr.number}
                    href={pr.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-3 p-4 hover:bg-gray-800/50 transition-colors group"
                  >
                    <GitPullRequest className={`w-4 h-4 mt-0.5 shrink-0 ${pr.merged_at ? 'text-purple-400' : 'text-green-400'}`} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-gray-200 group-hover:text-white transition-colors truncate">
                        {pr.title}
                      </p>
                      <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                        <span>#{pr.number}</span>
                        <span>·</span>
                        <span>{pr.author}</span>
                        {pr.merged_at && (
                          <>
                            <span>·</span>
                            <span className="text-purple-400">merged</span>
                          </>
                        )}
                      </div>
                    </div>
                    <ExternalLink className="w-3.5 h-3.5 text-gray-600 group-hover:text-gray-400 shrink-0 mt-0.5 transition-colors" />
                  </a>
                ))
              )}
            </div>
          </div>

          {/* Meta info */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
            <h3 className="text-white font-semibold text-sm">Details</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Status</span>
                <ReleaseBadge status={release.status} />
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">PRs</span>
                <span className="text-gray-300">{release.prs.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Tasks</span>
                <span className="text-gray-300">{release.tasks.length}</span>
              </div>
              {release.approved_by && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Approved by</span>
                  <span className="text-gray-300">{release.approved_by}</span>
                </div>
              )}
              {release.staging_deployed_at && (
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500 shrink-0">Staging</span>
                  <span className="text-yellow-400 text-xs text-right">{formatDate(release.staging_deployed_at)}</span>
                </div>
              )}
              {release.production_deployed_at && (
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500 shrink-0">Production</span>
                  <span className="text-green-400 text-xs text-right">{formatDate(release.production_deployed_at)}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
