'use client'

import { useState } from 'react'
import { Sidebar } from './Sidebar'
import { Menu } from 'lucide-react'

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden bg-[#09090B]">
      {/* Mobile overlay */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
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
        {/* Header – minimal, mobile only shows hamburger */}
        <header className="h-12 border-b border-[#1F1F23] flex items-center px-4 shrink-0 md:hidden">
          <button
            className="p-1.5 text-[#71717A] hover:text-[#FAFAFA] transition-colors"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="w-4 h-4" />
          </button>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-6 md:p-8">
          {children}
        </main>
      </div>
    </div>
  )
}
