'use client'

import { useState } from 'react'
import { Sidebar } from './Sidebar'
import { Bell, Circle, Menu } from 'lucide-react'

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Mobile overlay */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Sidebar – always visible on md+, togglable on mobile */}
      <div
        className={[
          'fixed inset-y-0 left-0 z-30 transition-transform duration-300',
          'md:static md:flex md:translate-x-0',
          mobileSidebarOpen ? 'flex translate-x-0' : '-translate-x-full hidden md:flex',
        ].join(' ')}
      >
        <Sidebar onClose={() => setMobileSidebarOpen(false)} />
      </div>

      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Header */}
        <header className="h-16 bg-gray-950 border-b border-gray-800 flex items-center justify-between px-4 md:px-6 shrink-0">
          <div className="flex items-center gap-3">
            {/* Hamburger – mobile only */}
            <button
              className="md:hidden p-2 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded-lg transition-colors"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open menu"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              <h1 className="text-white font-semibold text-lg">AutoDev</h1>
              <span className="text-gray-600">/</span>
              <span className="text-gray-400 text-sm hidden sm:inline">Framework</span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-3 py-1">
              <Circle className="w-2 h-2 fill-green-400 text-green-400 animate-pulse" />
              <span className="text-green-400 text-xs font-medium">Online</span>
            </div>
            <button className="p-2 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded-lg transition-colors relative">
              <Bell className="w-5 h-5" />
              <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
            </button>
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
