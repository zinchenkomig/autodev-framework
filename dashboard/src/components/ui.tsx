'use client'

import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { cx } from '@/lib/format'

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
}

export function Button({ variant = 'secondary', size = 'md', className, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-sm' : 'h-11 px-4 text-[15px]',
        variant === 'primary' && 'bg-accent text-accent-fg hover:opacity-90',
        variant === 'secondary' && 'border border-line bg-surface hover:bg-surface-2',
        variant === 'ghost' && 'hover:bg-surface-2',
        variant === 'danger' && 'border border-bad/40 bg-surface text-bad hover:bg-bad/10',
        className,
      )}
    />
  )
}

const TONES: Record<string, string> = {
  neutral: 'bg-surface-2 text-muted',
  info: 'bg-info/15 text-info',
  warn: 'bg-warn/15 text-warn',
  ok: 'bg-ok/15 text-ok',
  done: 'bg-accent/15 text-accent',
  bad: 'bg-bad/15 text-bad',
}

export function Badge({ tone = 'neutral', children, className }: { tone?: string; children: React.ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', TONES[tone], className)}>
      {children}
    </span>
  )
}

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx('rounded-2xl border border-line bg-surface', className)}>{children}</div>
}

/** Bottom sheet on phones, centered dialog on wider screens. */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl border border-line bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-2xl sm:max-w-lg sm:rounded-3xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-full p-2 hover:bg-surface-2" aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

/** Full-screen image viewer over the page: arrows / swipe to flip, Escape or a tap on the backdrop to close. */
export function Lightbox({
  images,
  index,
  onIndex,
  onClose,
}: {
  images: { src: string; caption?: string }[]
  index: number | null
  onIndex: (i: number) => void
  onClose: () => void
}) {
  const open = index !== null
  const touchX = useRef<number | null>(null)
  const go = (d: number) => index !== null && images.length > 1 && onIndex((index + d + images.length) % images.length)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'ArrowRight') go(1)
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  })

  if (index === null || !images[index]) return null
  const img = images[index]
  const many = images.length > 1
  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-black/90 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]"
      role="dialog"
      aria-modal="true"
      aria-label={img.caption || 'Изображение'}
      onClick={onClose}
      onTouchStart={(e) => (touchX.current = e.touches[0].clientX)}
      onTouchEnd={(e) => {
        if (touchX.current === null) return
        const dx = e.changedTouches[0].clientX - touchX.current
        touchX.current = null
        if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1)
      }}
    >
      <div className="flex items-center gap-2 p-2 text-sm text-white/80">
        <span className="min-w-0 flex-1 truncate px-2">{img.caption}</span>
        {many && (
          <span className="shrink-0 tabular-nums">
            {index + 1} / {images.length}
          </span>
        )}
        <button onClick={onClose} className="shrink-0 rounded-full p-2 hover:bg-white/10" aria-label="Закрыть">
          <X size={20} />
        </button>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-2">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={img.src}
          alt={img.caption ?? ''}
          className="max-h-full max-w-full rounded-lg object-contain"
          onClick={(e) => e.stopPropagation()}
        />
        {many && (
          <>
            <button
              onClick={(e) => (e.stopPropagation(), go(-1))}
              className="absolute left-2 hidden rounded-full bg-black/50 p-2 text-white hover:bg-black/70 sm:block"
              aria-label="Предыдущее"
            >
              <ChevronLeft size={24} />
            </button>
            <button
              onClick={(e) => (e.stopPropagation(), go(1))}
              className="absolute right-2 hidden rounded-full bg-black/50 p-2 text-white hover:bg-black/70 sm:block"
              aria-label="Следующее"
            >
              <ChevronRight size={24} />
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-xl border border-line bg-bg px-3 py-2.5 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20'

export function ErrorNote({ error }: { error: Error | string | null | undefined }) {
  if (!error) return null
  return (
    <div className="rounded-xl border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">
      {typeof error === 'string' ? error : error.message}
    </div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">{children}</div>
}

/** Long text folded to a few lines with «Показать полностью»; short text as is. */
export function Collapsible({ children, height = 'max-h-48' }: { children: React.ReactNode; height?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [overflows, setOverflows] = useState(false)
  useLayoutEffect(() => {
    const el = ref.current
    if (el && !open) setOverflows(el.scrollHeight > el.clientHeight + 8)
  }, [children, open])
  return (
    <div>
      <div ref={ref} className={cx('relative', !open && cx(height, 'overflow-hidden'))}>
        {children}
        {!open && overflows && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-surface to-transparent" />
        )}
      </div>
      {(overflows || open) && (
        <button onClick={() => setOpen(!open)} className="mt-1 text-sm font-medium text-accent hover:opacity-80">
          {open ? 'Свернуть' : 'Показать полностью'}
        </button>
      )}
    </div>
  )
}
