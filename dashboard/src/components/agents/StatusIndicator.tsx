import { type AgentMonitorStatus } from '@/lib/api'

interface StatusIndicatorProps {
  status: AgentMonitorStatus
  size?: 'sm' | 'md' | 'lg'
}

export function StatusIndicator({ status, size = 'md' }: StatusIndicatorProps) {
  const sizes = {
    sm: 'w-2 h-2',
    md: 'w-3 h-3',
    lg: 'w-4 h-4',
  }

  const sizeClass = sizes[size]

  if (status === 'working') {
    return (
      <span className="relative flex items-center justify-center">
        <span className={`absolute ${sizeClass} rounded-full bg-green-400 animate-ping opacity-75`} />
        <span className={`relative ${sizeClass} rounded-full bg-green-400`} />
      </span>
    )
  }

  if (status === 'failed') {
    return (
      <span className={`${sizeClass} rounded-full bg-red-500 block`} />
    )
  }

  // idle
  return (
    <span className={`${sizeClass} rounded-full bg-gray-500 block`} />
  )
}
