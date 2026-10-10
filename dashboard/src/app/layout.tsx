import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Shell } from '@/components/Shell'

const inter = Inter({ variable: '--font-inter', subsets: ['latin', 'cyrillic'] })
const mono = JetBrains_Mono({ variable: '--font-mono', subsets: ['latin', 'cyrillic'] })

export const metadata: Metadata = {
  title: 'AutoDev',
  description: 'Задачи → Claude Code → stage',
  appleWebApp: { capable: true, title: 'AutoDev', statusBarStyle: 'default' },
  icons: { icon: '/icon-192.png', apple: '/apple-touch-icon.png' },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f6f7f9' },
    { media: '(prefers-color-scheme: dark)', color: '#0b1020' },
  ],
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body className={`${inter.variable} ${mono.variable} font-sans antialiased`}>
        <Shell>{children}</Shell>
      </body>
    </html>
  )
}
