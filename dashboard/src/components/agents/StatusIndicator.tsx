import { type AgentMonitorStatus } from '@/lib/api'

interface StatusIndicatorProps {
  status: AgentMonitorStatus
  size?: 'sm' | 'md' | 'lg'
}

export function StatusIndicator({ status }: StatusIndicatorProps) {
  if (status === 'working') return <span className="text-xs text-[#22C55E]">●</span>
  if (status === 'failed')  return <span className="text-xs text-[#EF4444]">●</span>
  return <span className="text-xs text-[#3F3F46]">●</span>
}
