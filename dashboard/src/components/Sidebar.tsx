'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, ClipboardList, Bot, Package,
  ScrollText, Settings, Share2, MessageSquare, X
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { href: '/pm', icon: MessageSquare, label: 'PM Chat' },
  { href: '/tasks', icon: ClipboardList, label: 'Tasks' },
  { href: '/agents', icon: Bot, label: 'Agents' },
  { href: '/agents/graph', icon: Share2, label: 'Agent Graph', sub: true },
  { href: '/releases', icon: Package, label: 'Releases' },
  { href: '/events', icon: ScrollText, label: 'Events' },
  { href: '/settings', icon: Settings, label: 'Settings' },
]

interface SidebarProps {
  onClose?: () => void
}

export function Sidebar({ onClose }: SidebarProps) {
  const pathname = usePathname()

  return (
    <aside className="flex flex-col bg-[#09090B] border-r border-[#1F1F23] h-full w-[220px]">
      {/* Logo */}
      <div className="flex items-center justify-between h-12 border-b border-[#1F1F23] px-4">
        <span className="text-[#FAFAFA] font-semibold text-sm tracking-tight">AutoDev</span>
        {onClose && (
          <button
            onClick={onClose}
            className="md:hidden p-1 text-[#3F3F46] hover:text-[#71717A] transition-colors"
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 space-y-0.5">
        {navItems.map(({ href, icon: Icon, label, sub }, i) => {
          const isActive = href === '/' ? pathname === '/' : pathname === href

          // Section divider before Settings
          const showDivider = i > 0 && href === '/settings'

          return (
            <div key={href}>
              {showDivider && (
                <div className="my-2 border-t border-[#1F1F23]" />
              )}
              <Link
                href={href}
                onClick={onClose}
                className={cn(
                  'relative flex items-center gap-2.5 px-3 py-1.5 text-sm transition-colors rounded-sm',
                  isActive
                    ? 'bg-white/5 text-[#FAFAFA]'
                    : 'text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.03]',
                  sub && 'ml-4 text-xs'
                )}
                title={label}
              >
                {/* Active indicator */}
                {isActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-[#6366F1] rounded-full" />
                )}
                <Icon className="w-4 h-4 shrink-0" />
                <span>{label}</span>
              </Link>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
