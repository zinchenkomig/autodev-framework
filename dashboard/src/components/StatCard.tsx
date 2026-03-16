interface StatCardProps {
  label: string
  value: string | number
  trend?: number
  description?: string
}

export function StatCard({ label, value, trend, description }: StatCardProps) {
  return (
    <div className="border border-[#1F1F23] p-5 hover:border-[#3F3F46] transition-colors">
      <p className="text-xs text-[#71717A] uppercase tracking-wider mb-3">{label}</p>
      <div className="flex items-end justify-between">
        <span className="text-2xl font-mono text-[#FAFAFA]">{value}</span>
        {trend !== undefined && (
          <span className={`text-xs font-mono ${
            trend > 0 ? 'text-[#22C55E]' : trend < 0 ? 'text-[#EF4444]' : 'text-[#3F3F46]'
          }`}>
            {trend > 0 ? `+${trend}` : trend}
          </span>
        )}
      </div>
      {description && (
        <p className="text-xs text-[#3F3F46] mt-1">{description}</p>
      )}
    </div>
  )
}
