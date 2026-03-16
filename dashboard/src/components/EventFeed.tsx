import { type Event } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'
import {
  GitPullRequest, CheckCircle, XCircle, Bug, Rocket,
  Package, User, Zap, AlertCircle
} from 'lucide-react'

const eventConfig: Record<string, { icon: React.ElementType; color: string }> = {
  'task.created': { icon: Zap, color: 'text-blue-400' },
  'task.assigned': { icon: User, color: 'text-purple-400' },
  'pr.created': { icon: GitPullRequest, color: 'text-blue-400' },
  'pr.merged': { icon: CheckCircle, color: 'text-green-400' },
  'pr.ci.passed': { icon: CheckCircle, color: 'text-green-400' },
  'pr.ci.failed': { icon: XCircle, color: 'text-red-400' },
  'deploy.staging': { icon: Rocket, color: 'text-yellow-400' },
  'deploy.production': { icon: Rocket, color: 'text-green-400' },
  'review.passed': { icon: CheckCircle, color: 'text-green-400' },
  'review.failed': { icon: XCircle, color: 'text-red-400' },
  'bug.found': { icon: Bug, color: 'text-red-400' },
  'release.ready': { icon: Package, color: 'text-blue-400' },
  'release.approved': { icon: CheckCircle, color: 'text-green-400' },
  'agent.idle': { icon: User, color: 'text-gray-400' },
  'agent.failed': { icon: AlertCircle, color: 'text-red-400' },
}

interface EventFeedProps {
  events: Event[]
}

export function EventFeed({ events }: EventFeedProps) {
  if (events.length === 0) {
    return (
      <div className="py-8 text-center text-gray-500 text-sm">
        Нет событий
      </div>
    )
  }

  return (
    <div className="space-y-0">
      {events.map((event, index) => {
        const config = eventConfig[event.type] ?? { icon: Zap, color: 'text-gray-400' }
        const Icon = config.icon
        const isLast = index === events.length - 1

        return (
          <div key={event.id} className="flex gap-3 group">
            <div className="flex flex-col items-center">
              <div className={`p-1.5 rounded-lg bg-gray-800 border border-gray-700 ${config.color}`}>
                <Icon className="w-3.5 h-3.5" />
              </div>
              {!isLast && <div className="w-px flex-1 bg-gray-800 my-1" />}
            </div>
            <div className="pb-4 flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-xs font-mono text-gray-500">{event.type}</span>
                  <p className="text-sm text-gray-300 mt-0.5 truncate">
                    {event.description ?? JSON.stringify(event.payload)}
                  </p>
                </div>
                <span className="text-xs text-gray-600 whitespace-nowrap shrink-0">
                  {formatDistanceToNow(event.created_at)}
                </span>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
