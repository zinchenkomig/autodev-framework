'use client'

import { FolderGit2, Inbox, LayoutGrid, Settings } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { api } from '@/lib/api'
import { cx, time } from '@/lib/format'
import { usePoll } from '@/lib/hooks'
import { fetchInbox } from '@/lib/inbox'

const NAV = [
  { href: '/', label: 'Задачи', icon: LayoutGrid },
  { href: '/inbox', label: 'Ждут меня', icon: Inbox },
  { href: '/projects', label: 'Проекты', icon: FolderGit2 },
  { href: '/settings', label: 'Настройки', icon: Settings },
]

function isActive(pathname: string, href: string) {
  return href === '/' ? pathname === '/' || pathname.startsWith('/tasks') : pathname.startsWith(href)
}

export function WorkerStatus() {
  const { data, error } = usePoll(api.status, 10000)
  if (error) return <Dot tone="bad" label="API недоступен" />
  if (!data) return null
  if (!data.worker_online) return <Dot tone="bad" label="Воркер не на связи" />
  if (data.paused_until) return <Dot tone="warn" label={`Лимит Claude до ${time(data.paused_until).slice(0, 5)}`} />
  if (!data.developers_enabled) return <Dot tone="warn" label="Пауза" />
  const busy = data.slots.filter((s) => s.status === 'working').length
  return <Dot tone="ok" label={busy ? `Работает: ${busy}/${data.slots.length}` : 'Свободен'} />
}

function Dot({ tone, label }: { tone: 'ok' | 'warn' | 'bad'; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <span
        className={cx(
          'h-2 w-2 rounded-full',
          tone === 'ok' && 'bg-ok',
          tone === 'warn' && 'bg-warn',
          tone === 'bad' && 'bg-bad',
        )}
      />
      {label}
    </span>
  )
}

/** How many things wait for the owner, on the "Ждут меня" nav item. */
function Count({ n, className }: { n: number; className?: string }) {
  if (!n) return null
  return (
    <span className={cx('rounded-full bg-bad px-1.5 text-[11px] font-semibold leading-4 text-white', className)}>{n}</span>
  )
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const inbox = usePoll(fetchInbox, 15000).data?.total ?? 0
  const count = (href: string) => (href === '/inbox' ? inbox : 0)
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 pt-[env(safe-area-inset-top)] backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/icon-192.png" alt="" className="h-7 w-7 rounded-lg" />
            AutoDev
          </Link>
          <nav className="hidden gap-1 sm:flex">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={cx(
                  'rounded-lg px-3 py-1.5 text-sm',
                  isActive(pathname, href) ? 'bg-surface-2 font-medium' : 'text-muted hover:text-fg',
                )}
              >
                {label}
                <Count n={count(href)} className="ml-1.5" />
              </Link>
            ))}
          </nav>
          <div className="ml-auto">
            <WorkerStatus />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 pb-28 pt-4 sm:pb-10">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
        <div className="grid grid-cols-4">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cx(
                'flex flex-col items-center gap-0.5 py-2 text-[11px]',
                isActive(pathname, href) ? 'text-accent' : 'text-muted',
              )}
            >
              <span className="relative">
                <Icon size={22} />
                <Count n={count(href)} className="absolute -right-2.5 -top-1.5" />
              </span>
              {label}
            </Link>
          ))}
        </div>
      </nav>
    </div>
  )
}
