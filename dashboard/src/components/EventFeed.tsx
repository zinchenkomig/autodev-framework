import { type Event } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

const dotColor: Record<string, string> = {
  'task.created':   'text-[#6366F1]',
  'task.assigned':  'text-[#A78BFA]',
  'task.done':      'text-[#22C55E]',
  'pr.created':     'text-[#6366F1]',
  'pr.merged':      'text-[#22C55E]',
  'pr.ci.passed':   'text-[#22C55E]',
  'pr.ci.failed':   'text-[#EF4444]',
  'deploy.staging': 'text-[#F59E0B]',
  'deploy.production': 'text-[#22C55E]',
  'bug.found':      'text-[#EF4444]',
  'bug.resolved':   'text-[#22C55E]',
  'agent.failed':   'text-[#EF4444]',
  'agent.running':  'text-[#F59E0B]',
  'release.ready':  'text-[#6366F1]',
  'release.approved': 'text-[#22C55E]',
}

interface EventFeedProps {
  events: Event[]
}

export function EventFeed({ events }: EventFeedProps) {
  if (events.length === 0) {
    return (
      <div className="py-8 text-center text-[#3F3F46] text-sm">
        No events
      </div>
    )
  }

  return (
    <div className="divide-y divide-[#1F1F23]">
      {events.map((event) => {
        const color = dotColor[event.type] ?? 'text-[#3F3F46]'
        return (
          <div key={event.id} className="flex items-start gap-3 py-2.5">
            <span className={`text-xs shrink-0 mt-0.5 ${color}`}>●</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-[#71717A] truncate">
                {event.description ?? event.type}
              </p>
            </div>
            <span className="text-xs text-[#3F3F46] whitespace-nowrap shrink-0">
              {formatDistanceToNow(event.created_at)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
