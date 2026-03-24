'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, ClipboardList, Bot, Package,
  ScrollText, Settings, Share2, MessageSquare, X, BarChart2, AlertTriangle
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { href: '/pm', icon: MessageSquare, label: 'PM Chat' },
  { href: '/tasks', icon: ClipboardList, label: 'Tasks' },
  { href: '/agents', icon: Bot, label: 'Agents' },
  { href: '/alerts', icon: AlertTriangle, label: 'Alerts' },
  { href: '/agents/graph', icon: Share2, label: 'Agent Graph', sub: true },
  { href: '/releases', icon: Package, label: 'Releases' },
  { href: '/events', icon: ScrollText, label: 'Events' },
  { href: '/metrics', icon: BarChart2, label: 'Metrics' },
  { href: '/settings', icon: Settings, label: 'Settings' },
]

interface SidebarProps {
  onClose?: () => void
}

export function Sidebar({ onClose }: SidebarProps) {
  const pathname = usePathname()

  return (
    <aside className="flex flex-col h-full w-[220px]" style={{ background: '#313335', borderRight: '1px solid #515151' }}>
      {/* Logo */}
      <div className="flex items-center justify-between h-12 px-4" style={{ borderBottom: '1px solid #515151' }}>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold" style={{ color: '#3592C4' }}>⬡</span>
          <span className="font-semibold text-sm tracking-tight" style={{ color: '#FFFFFF' }}>AutoDev</span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="md:hidden p-1 transition-colors"
            style={{ color: '#808080' }}
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map(({ href, icon: Icon, label, sub }, i) => {
          const isActive = href === '/' ? pathname === '/' : pathname === href

          // Section divider before Settings
          const showDivider = i > 0 && href === '/settings'

          return (
            <div key={href}>
              {showDivider && (
                <div className="my-2" style={{ borderTop: '1px solid #515151' }} />
              )}
              <Link
                href={href}
                onClick={onClose}
                className={cn(
                  'relative flex items-center gap-2.5 px-3 py-2 text-sm transition-colors rounded-sm',
                  sub && 'ml-4 text-xs'
                )}
                style={{
                  backgroundColor: isActive ? '#214283' : 'transparent',
                  color: isActive ? '#FFFFFF' : '#BABABA',
                  borderLeft: isActive ? '2px solid #3592C4' : '2px solid transparent',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    (e.currentTarget as HTMLAnchorElement).style.backgroundColor = '#353739'
                    ;(e.currentTarget as HTMLAnchorElement).style.color = '#FFFFFF'
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    (e.currentTarget as HTMLAnchorElement).style.backgroundColor = 'transparent'
                    ;(e.currentTarget as HTMLAnchorElement).style.color = '#BABABA'
                  }
                }}
                title={label}
              >
                <Icon size={18} className="shrink-0" />
                <span>{label}</span>
              </Link>
            </div>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3" style={{ borderTop: '1px solid #515151' }}>
        <p className="text-xs" style={{ color: '#808080' }}>AutoDev Framework</p>
        <p className="text-xs" style={{ color: '#515151' }}>v0.1.0</p>
      </div>
    </aside>
  )
}
