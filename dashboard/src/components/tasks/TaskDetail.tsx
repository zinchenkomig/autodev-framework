'use client'

import { type Task } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import { X, GitPullRequest } from 'lucide-react'
import { PriorityBadge, StatusBadge } from '@/components/Badge'

interface TaskDetailProps {
  task: Task | null
  onClose: () => void
}

export function TaskDetail({ task, onClose }: TaskDetailProps) {
  if (!task) return null

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40" onClick={onClose} />

      <div className="fixed right-0 top-0 h-full w-full md:max-w-sm bg-[#09090B] border-l border-[#1F1F23] z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[#1F1F23]">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <StatusBadge status={task.status} />
              <PriorityBadge priority={task.priority} />
            </div>
            <p className="text-sm text-[#FAFAFA] leading-snug">{task.title}</p>
          </div>
          <button
            onClick={onClose}
            className="text-[#3F3F46] hover:text-[#71717A] transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {task.description && (
            <div>
              <p className="text-xs text-[#71717A] uppercase tracking-wider mb-2">Description</p>
              <p className="text-xs text-[#71717A] leading-relaxed">{task.description}</p>
            </div>
          )}

          <div>
            <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">Details</p>
            <div className="space-y-2">
              {[
                ['Assigned', task.assigned_to ?? '—'],
                ['Repository', task.repo],
                ['Source', task.source],
                ['Created by', task.created_by],
                ['Created', formatDistanceToNow(task.created_at)],
                ['Updated', formatDistanceToNow(task.updated_at)],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-xs text-[#3F3F46]">{label}</span>
                  <span className="text-xs text-[#71717A] font-mono">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {(task.issue_number || task.pr_number) && (
            <div>
              <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">Links</p>
              <div className="space-y-1.5">
                {task.pr_number && (
                  <a
                    href={`https://github.com/autodev-framework/${task.repo}/pull/${task.pr_number}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-xs text-[#6366F1] hover:text-[#818CF8] transition-colors"
                  >
                    <GitPullRequest className="w-3.5 h-3.5" />
                    PR #{task.pr_number}
                  </a>
                )}
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">History</p>
            <div className="space-y-2.5">
              <div className="flex items-start gap-2">
                <span className="text-xs text-[#3F3F46] mt-0.5">●</span>
                <div>
                  <p className="text-xs text-[#71717A]">
                    Status → <span className="text-[#FAFAFA]">{task.status}</span>
                    <span className="text-[#3F3F46] ml-1">by {task.assigned_to ?? 'system'}</span>
                  </p>
                  <p className="text-xs text-[#3F3F46]">{formatDistanceToNow(task.updated_at)}</p>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-xs text-[#3F3F46] mt-0.5">●</span>
                <div>
                  <p className="text-xs text-[#71717A]">
                    Created by <span className="text-[#FAFAFA]">{task.created_by}</span>
                  </p>
                  <p className="text-xs text-[#3F3F46]">{formatDistanceToNow(task.created_at)}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
