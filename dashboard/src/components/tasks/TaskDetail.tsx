'use client'

import { type Task } from '@/lib/api'
import { PriorityBadge, StatusBadge } from '@/components/Badge'
import { formatDistanceToNow } from '@/lib/utils'
import { X, GitPullRequest, Hash, User2, Calendar, Database, Tag } from 'lucide-react'

interface TaskDetailProps {
  task: Task | null
  onClose: () => void
}

export function TaskDetail({ task, onClose }: TaskDetailProps) {
  if (!task) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-full max-w-md bg-gray-900 border-l border-gray-800 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-start gap-3 p-5 border-b border-gray-800">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <StatusBadge status={task.status} />
              <PriorityBadge priority={task.priority} />
            </div>
            <h2 className="text-white font-semibold text-base leading-snug mt-2">
              {task.title}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 transition-colors shrink-0 mt-0.5"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Description */}
          {task.description && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Description
              </h3>
              <p className="text-gray-300 text-sm leading-relaxed">
                {task.description}
              </p>
            </div>
          )}

          {/* Details */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
              Details
            </h3>
            <div className="space-y-2.5">
              <DetailRow icon={User2} label="Assigned to">
                <span className="text-gray-300 text-sm">{task.assigned_to ?? 'Unassigned'}</span>
              </DetailRow>
              <DetailRow icon={Database} label="Repository">
                <span className="text-gray-300 text-sm font-mono">{task.repo}</span>
              </DetailRow>
              <DetailRow icon={Tag} label="Source">
                <span className="text-gray-300 text-sm">{task.source.replace(/_/g, ' ')}</span>
              </DetailRow>
              <DetailRow icon={User2} label="Created by">
                <span className="text-gray-300 text-sm">{task.created_by}</span>
              </DetailRow>
              <DetailRow icon={Calendar} label="Created">
                <span className="text-gray-300 text-sm">{formatDistanceToNow(task.created_at)}</span>
              </DetailRow>
              <DetailRow icon={Calendar} label="Updated">
                <span className="text-gray-300 text-sm">{formatDistanceToNow(task.updated_at)}</span>
              </DetailRow>
            </div>
          </div>

          {/* Links */}
          {(task.issue_number || task.pr_number) && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Links
              </h3>
              <div className="space-y-2">
                {task.issue_number && (
                  <a
                    href={`https://github.com/autodev-framework/${task.repo}/issues/${task.issue_number}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-blue-400 hover:text-blue-300 text-sm transition-colors"
                  >
                    <Hash className="size-4" />
                    Issue #{task.issue_number}
                  </a>
                )}
                {task.pr_number && (
                  <a
                    href={`https://github.com/autodev-framework/${task.repo}/pull/${task.pr_number}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-blue-400 hover:text-blue-300 text-sm transition-colors"
                  >
                    <GitPullRequest className="size-4" />
                    Pull Request #{task.pr_number}
                  </a>
                )}
              </div>
            </div>
          )}

          {/* History (mock) */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
              History
            </h3>
            <div className="space-y-3">
              <HistoryItem
                action="Status changed to"
                value={task.status.replace(/_/g, ' ')}
                time={task.updated_at}
                actor={task.assigned_to ?? 'system'}
              />
              <HistoryItem
                action="Task created by"
                value={task.created_by}
                time={task.created_at}
                actor="system"
              />
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

function DetailRow({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 w-28 shrink-0">
        <Icon className="size-3.5 text-gray-500" />
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      {children}
    </div>
  )
}

function HistoryItem({
  action,
  value,
  time,
  actor,
}: {
  action: string
  value: string
  time: string
  actor: string
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-1.5 h-1.5 rounded-full bg-gray-600 mt-1.5 shrink-0" />
      <div>
        <p className="text-xs text-gray-400">
          {action} <span className="text-gray-200 font-medium">{value}</span>{' '}
          <span className="text-gray-600">by {actor}</span>
        </p>
        <p className="text-xs text-gray-600 mt-0.5">{formatDistanceToNow(time)}</p>
      </div>
    </div>
  )
}
