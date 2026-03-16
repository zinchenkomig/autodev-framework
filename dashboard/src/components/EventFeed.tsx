import { type Event } from '@/lib/api'
import { formatDistanceToNow } from '@/lib/utils'

const dotColor: Record<string, string> = {
  'task.created':      '#3592C4',
  'task.assigned':     '#9876AA',
  'task.done':         '#6A8759',
  'pr.created':        '#3592C4',
  'pr.merged':         '#6A8759',
  'pr.ci.passed':      '#6A8759',
  'pr.ci.failed':      '#CC4E4E',
  'deploy.staging':    '#CC7832',
  'deploy.production': '#6A8759',
  'bug.found':         '#CC4E4E',
  'bug.resolved':      '#6A8759',
  'agent.failed':      '#CC4E4E',
  'agent.running':     '#CC7832',
  'release.ready':     '#3592C4',
  'release.approved':  '#6A8759',
}

interface EventFeedProps {
  events: Event[]
}

export function EventFeed({ events }: EventFeedProps) {
  if (events.length === 0) {
    return (
      <div className="py-8 text-center text-sm" style={{ color: '#808080' }}>
        No events
      </div>
    )
  }

  return (
    <div>
      {events.map((event, i) => {
        const color = dotColor[event.type] ?? '#808080'
        return (
          <div
            key={event.id}
            className="flex items-start gap-3 py-2"
            style={{ borderBottom: i < events.length - 1 ? '1px solid #414345' : 'none' }}
          >
            <span
              style={{
                display: 'inline-block',
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                background: color,
                flexShrink: 0,
                marginTop: '4px',
              }}
            />
            <div className="flex-1 min-w-0">
              <p className="text-xs truncate" style={{ color: '#BABABA' }}>
                {event.description ?? event.type}
              </p>
            </div>
            <span className="text-xs whitespace-nowrap shrink-0" style={{ color: '#808080' }}>
              {formatDistanceToNow(event.created_at)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
