'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useState } from 'react'
import {
  LayoutDashboard, ClipboardList, Bot, Package,
  ScrollText, Settings, ChevronLeft, ChevronRight, Cpu, X
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { href: '/tasks', icon: ClipboardList, label: 'Tasks' },
  { href: '/agents', icon: Bot, label: 'Agents' },
  { href: '/releases', icon: Package, label: 'Releases' },
  { href: '/events', icon: ScrollText, label: 'Events' },
  { href: '/settings', icon: Settings, label: 'Settings' },
]

interface SidebarProps {
  onClose?: () => void
}

export function Sidebar({ onClose }: SidebarProps) {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside className={cn(
      'flex flex-col bg-gray-950 border-r border-gray-800 transition-all duration-300 h-full',
      collapsed ? 'w-16' : 'w-56'
    )}>
      {/* Logo */}
      <div className={cn(
        'flex items-center h-16 border-b border-gray-800 px-4',
        collapsed ? 'justify-center' : 'gap-3'
      )}>
        <div className="p-1.5 bg-blue-500/20 rounded-lg shrink-0">
          <Cpu className="w-5 h-5 text-blue-400" />
        </div>
        {!collapsed && (
          <span className="text-white font-bold text-lg tracking-tight flex-1">AutoDev</span>
        )}
        {/* Close button on mobile */}
        {!collapsed && onClose && (
          <button
            onClick={onClose}
            className="md:hidden p-1 text-gray-500 hover:text-gray-300 transition-colors"
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {navItems.map(({ href, icon: Icon, label }) => {
          const isActive = href === '/' ? pathname === '/' : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              onClick={onClose}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                isActive
                  ? 'bg-blue-500/15 text-blue-400 border border-blue-500/20'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800',
                collapsed && 'justify-center px-2'
              )}
              title={collapsed ? label : undefined}
            >
              <Icon className="w-5 h-5 shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          )
        })}
      </nav>

      {/* Collapse toggle – desktop only */}
      <div className="p-3 border-t border-gray-800 hidden md:block">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center w-full py-2 px-3 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors text-sm"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : (
            <>
              <ChevronLeft className="w-4 h-4 mr-2" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
