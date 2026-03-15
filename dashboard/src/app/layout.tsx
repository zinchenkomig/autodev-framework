import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'
import { Sidebar } from '@/components/Sidebar'
import { Bell, Circle } from 'lucide-react'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})

export const metadata: Metadata = {
  title: 'AutoDev Framework',
  description: 'AI-powered development automation dashboard',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-950 text-white`}>
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
            {/* Header */}
            <header className="h-16 bg-gray-950 border-b border-gray-800 flex items-center justify-between px-6 shrink-0">
              <div className="flex items-center gap-2">
                <h1 className="text-white font-semibold text-lg">AutoDev</h1>
                <span className="text-gray-600">/</span>
                <span className="text-gray-400 text-sm">Framework</span>
              </div>
              <div className="flex items-center gap-4">
                {/* Status indicator */}
                <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-3 py-1">
                  <Circle className="w-2 h-2 fill-green-400 text-green-400 animate-pulse" />
                  <span className="text-green-400 text-xs font-medium">Online</span>
                </div>
                <button className="p-2 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded-lg transition-colors relative">
                  <Bell className="w-5 h-5" />
                  <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full"></span>
                </button>
              </div>
            </header>
            {/* Main content */}
            <main className="flex-1 overflow-y-auto p-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  )
}
