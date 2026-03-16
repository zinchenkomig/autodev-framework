interface StatCardProps {
  label: string
  value: string | number
  trend?: number
  description?: string
  accentColor?: string
  icon?: React.ReactNode
}

export function StatCard({ label, value, trend, description, accentColor = '#3592C4', icon }: StatCardProps) {
  return (
    <div
      className="p-5 transition-all cursor-default group"
      style={{
        background: '#3C3F41',
        border: '1px solid #515151',
        borderRadius: '4px',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLDivElement).style.borderColor = '#808080'
        ;(e.currentTarget as HTMLDivElement).style.background = '#414345'
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.borderColor = '#515151'
        ;(e.currentTarget as HTMLDivElement).style.background = '#3C3F41'
      }}
    >
      <div className="flex items-start justify-between mb-3">
        <p className="text-xs uppercase tracking-wider" style={{ color: '#808080' }}>{label}</p>
        {icon && (
          <span style={{ color: accentColor, opacity: 0.85 }}>{icon}</span>
        )}
      </div>
      <div className="flex items-end justify-between">
        <span className="text-3xl font-bold" style={{ color: '#FFFFFF', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
        {trend !== undefined && (
          <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{
            color: trend > 0 ? '#6A8759' : trend < 0 ? '#CC4E4E' : '#808080',
            background: trend > 0 ? 'rgba(106,135,89,0.15)' : trend < 0 ? 'rgba(204,78,78,0.15)' : 'rgba(128,128,128,0.1)',
          }}>
            {trend > 0 ? `+${trend}` : trend}
          </span>
        )}
      </div>
      {description && (
        <p className="text-xs mt-1" style={{ color: '#808080' }}>{description}</p>
      )}
    </div>
  )
}
