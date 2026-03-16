'use client'

import { useEffect, useState, useRef } from 'react'
import { getAgents, type Agent } from '@/lib/api'
import { Loader2, RefreshCw } from 'lucide-react'

// ---------------------------------------------------------------------------
// Graph definition (hardcoded structure, statuses from API)
// ---------------------------------------------------------------------------

interface GraphNode {
  id: string
  label: string
  icon: string
}

interface GraphEdge {
  from: string
  to: string
  label: string
}

const AGENT_GRAPH = {
  nodes: [
    { id: 'pm', label: 'PM', icon: 'briefcase' },
    { id: 'developer', label: 'Developer', icon: 'code' },
    { id: 'tester', label: 'Tester', icon: 'flask' },
    { id: 'ba', label: 'BA', icon: 'chart' },
    { id: 'release_manager', label: 'Release Manager', icon: 'package' },
  ] as GraphNode[],
  edges: [
    { from: 'pm', to: 'developer', label: 'task.created' },
    { from: 'developer', to: 'tester', label: 'pr.created' },
    { from: 'tester', to: 'developer', label: 'bug.found' },
    { from: 'release_manager', to: 'tester', label: 'deploy.staging' },
    { from: 'release_manager', to: 'ba', label: 'deploy.staging' },
    { from: 'ba', to: 'developer', label: 'bug.found' },
    { from: 'developer', to: 'release_manager', label: 'pr.merged (8+)' },
  ] as GraphEdge[],
}

// ---------------------------------------------------------------------------
// Node positions (desktop layout)
// ---------------------------------------------------------------------------

interface NodePos {
  x: number
  y: number
  w: number
  h: number
}

// SVG viewBox: 900 x 520
const DESKTOP_POSITIONS: Record<string, NodePos> = {
  pm:              { x: 350, y: 30,  w: 140, h: 54 },
  developer:       { x: 330, y: 200, w: 160, h: 54 },
  tester:          { x: 620, y: 200, w: 140, h: 54 },
  ba:              { x: 620, y: 370, w: 140, h: 54 },
  release_manager: { x: 40,  y: 200, w: 160, h: 54 },
}

// Mobile layout (viewBox 360 x 600, nodes stacked vertically)
const MOBILE_POSITIONS: Record<string, NodePos> = {
  pm:              { x: 110, y: 20,  w: 140, h: 50 },
  developer:       { x: 110, y: 140, w: 140, h: 50 },
  tester:          { x: 110, y: 260, w: 140, h: 50 },
  ba:              { x: 110, y: 380, w: 140, h: 50 },
  release_manager: { x: 110, y: 500, w: 140, h: 50 },
}

// ---------------------------------------------------------------------------
// Status → color mapping
// ---------------------------------------------------------------------------

function nodeColor(status: string | undefined) {
  if (status === 'running' || status === 'working') return { fill: '#1d4ed8', stroke: '#3b82f6', text: '#bfdbfe' }
  if (status === 'failed') return { fill: '#7f1d1d', stroke: '#ef4444', text: '#fecaca' }
  return { fill: '#14532d', stroke: '#22c55e', text: '#bbf7d0' } // idle / unknown
}

// ---------------------------------------------------------------------------
// SVG Icon paths (inline, no external deps)
// ---------------------------------------------------------------------------

function SvgIcon({ icon, x, y, size = 16 }: { icon: string; x: number; y: number; size?: number }) {
  const h = size / 2
  switch (icon) {
    case 'briefcase':
      return (
        <g transform={`translate(${x - h}, ${y - h})`}>
          <rect x="1" y="4" width={size - 2} height={size - 5} rx="2" stroke="currentColor" strokeWidth="1.5" fill="none"/>
          <path d={`M${size/2-3} 4 V2 a1 1 0 0 1 1-1 h4 a1 1 0 0 1 1 1 v2`} stroke="currentColor" strokeWidth="1.5" fill="none"/>
          <line x1="1" y1="9" x2={size-1} y2="9" stroke="currentColor" strokeWidth="1.5"/>
        </g>
      )
    case 'code':
      return (
        <g transform={`translate(${x - h}, ${y - h})`}>
          <polyline points={`${size*0.3},${size*0.25} ${size*0.05},${size/2} ${size*0.3},${size*0.75}`} stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
          <polyline points={`${size*0.7},${size*0.25} ${size*0.95},${size/2} ${size*0.7},${size*0.75}`} stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
        </g>
      )
    case 'flask':
      return (
        <g transform={`translate(${x - h}, ${y - h})`}>
          <path d={`M${size*0.35} 2 v${size*0.35} L${size*0.05} ${size-2} a1 1 0 0 0 0.9 1 h${size*0.9+1} a1 1 0 0 0 0.9-1 L${size*0.65} ${size*0.35} V2`} stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
          <line x1={size*0.3} y1="2" x2={size*0.7} y2="2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </g>
      )
    case 'chart':
      return (
        <g transform={`translate(${x - h}, ${y - h})`}>
          <line x1="2" y1={size-2} x2={size-2} y2={size-2} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          <rect x="3" y={size*0.55} width={size*0.2} height={size*0.35} rx="1" fill="currentColor"/>
          <rect x={size*0.4} y={size*0.3} width={size*0.2} height={size*0.6} rx="1" fill="currentColor"/>
          <rect x={size*0.73} y={size*0.1} width={size*0.2} height={size*0.8} rx="1" fill="currentColor"/>
        </g>
      )
    case 'package':
      return (
        <g transform={`translate(${x - h}, ${y - h})`}>
          <path d={`M${size/2} 1 L${size-1} ${size*0.3} V${size*0.7} L${size/2} ${size-1} L1 ${size*0.7} V${size*0.3} Z`} stroke="currentColor" strokeWidth="1.5" fill="none"/>
          <line x1={size/2} y1="1" x2={size/2} y2={size-1} stroke="currentColor" strokeWidth="1" strokeDasharray="2,2"/>
          <line x1="1" y1={size*0.3} x2={size-1} y2={size*0.3} stroke="currentColor" strokeWidth="1" strokeDasharray="2,2"/>
        </g>
      )
    default:
      return <circle cx={x} cy={y} r={h * 0.6} stroke="currentColor" strokeWidth="1.5" fill="none"/>
  }
}

// ---------------------------------------------------------------------------
// Arrow head & edge rendering
// ---------------------------------------------------------------------------

function arrowId(from: string, to: string) {
  return `arrow-${from}-${to}`
}

function getEdgePoints(from: NodePos, to: NodePos) {
  const fx = from.x + from.w / 2
  const fy = from.y + from.h / 2
  const tx = to.x + to.w / 2
  const ty = to.y + to.h / 2

  // Find exit/entry points on box borders
  const dx = tx - fx
  const dy = ty - fy
  const angle = Math.atan2(dy, dx)

  // Exit point from source
  const ex = fx + Math.cos(angle) * (from.w / 2 + 2)
  const ey = fy + Math.sin(angle) * (from.h / 2 + 2)

  // Entry point to target (back off 10px for arrowhead)
  const tx2 = tx - Math.cos(angle) * (to.w / 2 + 12)
  const ty2 = ty - Math.sin(angle) * (to.h / 2 + 12)

  // Label midpoint
  const mx = (ex + tx2) / 2
  const my = (ey + ty2) / 2

  return { ex, ey, tx: tx2, ty: ty2, mx, my }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AgentGraphPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [recentEdges, setRecentEdges] = useState<Set<string>>(new Set())
  const [isMobile, setIsMobile] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 640)
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  const loadAgents = () => {
    setLoading(true)
    getAgents().then(a => {
      setAgents(a)
      setLoading(false)
    })
  }

  useEffect(() => { loadAgents() }, [])

  // Simulate "recent edge" animation — in real usage this would come from events API
  useEffect(() => {
    if (agents.length === 0) return
    const workingAgent = agents.find(a => a.status === 'running')
    if (!workingAgent) return
    const edges = AGENT_GRAPH.edges
      .filter(e => e.from === workingAgent.id || e.to === workingAgent.id)
      .map(e => `${e.from}-${e.to}`)
    setRecentEdges(new Set(edges))
  }, [agents])

  const statusMap: Record<string, string> = {}
  agents.forEach(a => { statusMap[a.id] = a.status })

  const positions = isMobile ? MOBILE_POSITIONS : DESKTOP_POSITIONS
  const viewBox = isMobile ? '0 0 360 600' : '0 0 900 520'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-white">Agent Interaction Graph</h2>
          <p className="text-gray-400 text-sm mt-1">
            Схема взаимодействия агентов и событий между ними
          </p>
        </div>
        <button
          onClick={loadAgents}
          className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm text-gray-300 transition-colors self-start sm:self-auto"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Обновить
        </button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-gray-400">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-green-900 border border-green-500 inline-block" />
          Idle
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-blue-900 border border-blue-500 inline-block" />
          Working
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-red-900 border border-red-500 inline-block" />
          Failed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-8 h-0.5 bg-gray-500 inline-block" />
          Event trigger
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-8 h-0.5 bg-blue-400 inline-block animate-pulse" />
          Active event
        </span>
      </div>

      {/* Graph */}
      <div
        ref={containerRef}
        className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden"
      >
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
          </div>
        ) : (
          <svg
            viewBox={viewBox}
            className="w-full h-auto"
            style={{ minHeight: isMobile ? 400 : 380 }}
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              {/* Arrow markers per edge color */}
              <marker id="arrow-default" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="#6b7280" />
              </marker>
              <marker id="arrow-active" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="#60a5fa" />
              </marker>
              {/* Glow filter for active nodes */}
              <filter id="glow">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge>
                  <feMergeNode in="coloredBlur"/>
                  <feMergeNode in="SourceGraphic"/>
                </feMerge>
              </filter>
            </defs>

            {/* Edges */}
            {AGENT_GRAPH.edges.map((edge) => {
              const fromPos = positions[edge.from]
              const toPos = positions[edge.to]
              if (!fromPos || !toPos) return null
              const key = `${edge.from}-${edge.to}`
              const isActive = recentEdges.has(key)
              const { ex, ey, tx, ty, mx, my } = getEdgePoints(fromPos, toPos)

              return (
                <g key={key}>
                  <line
                    x1={ex} y1={ey} x2={tx} y2={ty}
                    stroke={isActive ? '#60a5fa' : '#4b5563'}
                    strokeWidth={isActive ? 2 : 1.5}
                    markerEnd={isActive ? 'url(#arrow-active)' : 'url(#arrow-default)'}
                    strokeDasharray={isActive ? '6 3' : undefined}
                    className={isActive ? 'animate-pulse' : undefined}
                  />
                  {/* Label background */}
                  <rect
                    x={mx - edge.label.length * 3.2}
                    y={my - 9}
                    width={edge.label.length * 6.4}
                    height={16}
                    rx="3"
                    fill="#111827"
                    opacity="0.85"
                  />
                  <text
                    x={mx}
                    y={my + 4}
                    textAnchor="middle"
                    fontSize={isMobile ? 8 : 10}
                    fill={isActive ? '#93c5fd' : '#9ca3af'}
                    fontFamily="ui-monospace, monospace"
                  >
                    {edge.label}
                  </text>
                </g>
              )
            })}

            {/* Nodes */}
            {AGENT_GRAPH.nodes.map((node) => {
              const pos = positions[node.id]
              if (!pos) return null
              const status = statusMap[node.id]
              const colors = nodeColor(status)
              const isWorking = status === 'running' || status === 'working'
              const cx = pos.x + pos.w / 2
              const cy = pos.y + pos.h / 2

              return (
                <g key={node.id} filter={isWorking ? 'url(#glow)' : undefined}>
                  {/* Pulsing ring for working agents */}
                  {isWorking && (
                    <rect
                      x={pos.x - 4}
                      y={pos.y - 4}
                      width={pos.w + 8}
                      height={pos.h + 8}
                      rx="12"
                      fill="none"
                      stroke={colors.stroke}
                      strokeWidth="2"
                      opacity="0.4"
                      className="animate-ping"
                    />
                  )}
                  {/* Node body */}
                  <rect
                    x={pos.x}
                    y={pos.y}
                    width={pos.w}
                    height={pos.h}
                    rx="8"
                    fill={colors.fill}
                    stroke={colors.stroke}
                    strokeWidth="1.5"
                  />
                  {/* Icon */}
                  <g color={colors.text}>
                    <SvgIcon icon={node.icon} x={pos.x + 22} y={cy} size={16} />
                  </g>
                  {/* Label */}
                  <text
                    x={cx + 8}
                    y={cy - 5}
                    textAnchor="middle"
                    fontSize={isMobile ? 11 : 13}
                    fontWeight="600"
                    fill={colors.text}
                    fontFamily="ui-sans-serif, system-ui, sans-serif"
                  >
                    {node.label}
                  </text>
                  {/* Status */}
                  <text
                    x={cx + 8}
                    y={cy + 9}
                    textAnchor="middle"
                    fontSize={isMobile ? 8 : 9}
                    fill={colors.text}
                    opacity="0.7"
                    fontFamily="ui-monospace, monospace"
                  >
                    {status ?? 'no data'}
                  </text>
                </g>
              )
            })}
          </svg>
        )}
      </div>

      {/* Agent list below graph */}
      {!loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
          {AGENT_GRAPH.nodes.map(node => {
            const status = statusMap[node.id]
            const colors = nodeColor(status)
            return (
              <div
                key={node.id}
                className="bg-gray-900 border border-gray-800 rounded-xl p-3 flex items-center gap-3"
              >
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: colors.stroke }}
                />
                <div className="min-w-0">
                  <p className="text-white text-sm font-medium truncate">{node.label}</p>
                  <p className="text-gray-500 text-xs">{status ?? 'no data'}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
