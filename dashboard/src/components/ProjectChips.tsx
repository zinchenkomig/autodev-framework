'use client'

import { cx } from '@/lib/format'

/** Horizontally scrolling project filter; an optional count shows next to each name. */
export function ProjectChips({
  items,
  value,
  onChange,
}: {
  items: { id: string; name: string; count?: number }[]
  value: string
  onChange: (id: string) => void
}) {
  return (
    <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
      {items.map((p) => (
        <button
          key={p.id}
          onClick={() => onChange(p.id)}
          className={cx(
            'shrink-0 rounded-full border px-3 py-1.5 text-sm',
            value === p.id ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-surface text-muted',
          )}
        >
          {p.name}
          {p.count !== undefined && <span className="ml-1.5 opacity-70">{p.count}</span>}
        </button>
      ))}
    </div>
  )
}
