'use client'

import { useEffect, useState } from 'react'
import { getAgents, type Agent } from '@/lib/api'
import { Loader2, RefreshCw } from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

type NodeType = 'agent' | 'process' | 'environment' | 'external'

interface GraphNode {
  id: string
  label: string
  sublabel?: string
  icon?: string
  type: NodeType
  x: number
  y: number
  w: number
  h: number
}

interface GraphEdge {
  id: string
  from: string
  to: string
  path: string
  labelX: number
  labelY: number
  label: string
  dashed?: boolean
  feedback?: boolean
}

// ─── Node definitions (viewBox 0 0 900 1000) ─────────────────────────────────

const NODES: GraphNode[] = [
  // External: Chat / Kanban (PM task source)
  { id: 'chat_kanban', label: 'Chat / Kanban', sublabel: 'пользователь задаёт задачи', icon: 'chat', type: 'external', x: 300, y: 10, w: 300, h: 60 },
  // Agents
  { id: 'pm',              label: 'PM',             icon: 'briefcase', type: 'agent', x: 375, y: 104, w: 150, h: 54 },
  { id: 'developer',       label: 'Developer',       icon: 'code',      type: 'agent', x: 375, y: 210, w: 150, h: 54 },
  { id: 'release_manager', label: 'Release Manager', icon: 'package',   type: 'agent', x: 340, y: 440, w: 220, h: 54 },
  { id: 'tester',          label: 'Tester',          icon: 'flask',     type: 'agent', x: 150, y: 675, w: 155, h: 54 },
  { id: 'ba',              label: 'BA',              icon: 'chart',     type: 'agent', x: 595, y: 675, w: 155, h: 54 },
  // Processes
  { id: 'ci',     label: 'CI',     sublabel: 'tests', icon: 'gear', type: 'process', x: 215, y: 325, w: 155, h: 54 },
  { id: 'review', label: 'Review', sublabel: 'auto',  icon: 'eye',  type: 'process', x: 530, y: 325, w: 155, h: 54 },
  // Environments
  { id: 'staging',    label: 'STAGING',    type: 'environment', x: 300, y: 550, w: 300, h: 64 },
  { id: 'production', label: 'PRODUCTION', type: 'environment', x: 260, y: 910, w: 380, h: 64 },
  // External: Human
  { id: 'mikhail', label: 'Mikhail', sublabel: 'human', type: 'external', x: 330, y: 795, w: 240, h: 60 },
]

// ─── Edge definitions (pre-calculated SVG paths) ─────────────────────────────
// Positions:
//   github_issues : cx=450 cy=42  bottom=64
//   pm            : cx=450 cy=131 top=104  bottom=158
//   developer     : cx=450 cy=237 top=210  bottom=264  left=375  right=525
//   ci            : cx=292 cy=352 top=325  bottom=379  left=215  right=370
//   review        : cx=607 cy=352 top=325  bottom=379  left=530  right=685
//   release_manager: cx=450 cy=467 top=440  bottom=494
//   staging       : cx=450 cy=582 top=550  bottom=614  left=300  right=600
//   tester        : cx=227 cy=702 top=675  bottom=729  left=150  right=305
//   ba            : cx=672 cy=702 top=675  bottom=729  left=595  right=750
//   mikhail       : cx=450 cy=825 top=795  bottom=855  left=330  right=570
//   production    : cx=450 cy=942 top=910  bottom=974

const EDGES: GraphEdge[] = [
  {
    id: 'chat-pm', from: 'chat_kanban', to: 'pm',
    path: 'M 450,70 L 450,104',
    labelX: 462, labelY: 90, label: 'tasks',
  },
  {
    id: 'pm-dev', from: 'pm', to: 'developer',
    path: 'M 450,158 L 450,210',
    labelX: 462, labelY: 188, label: 'task.created',
  },
  {
    id: 'dev-ci', from: 'developer', to: 'ci',
    path: 'M 420,264 C 420,298 292,298 292,325',
    labelX: 372, labelY: 294, label: 'pr.created',
  },
  {
    id: 'ci-review', from: 'ci', to: 'review',
    path: 'M 370,352 L 530,352',
    labelX: 450, labelY: 344, label: 'ci.started',
  },
  {
    id: 'ci-rm', from: 'ci', to: 'release_manager',
    path: 'M 292,379 C 292,415 450,415 450,440',
    labelX: 388, labelY: 413, label: 'ci.passed',
  },
  {
    id: 'rm-staging', from: 'release_manager', to: 'staging',
    path: 'M 450,494 L 450,550',
    labelX: 464, labelY: 526, label: 'deploy.staging',
  },
  {
    id: 'staging-tester', from: 'staging', to: 'tester',
    path: 'M 375,614 C 375,648 227,648 227,675',
    labelX: 292, labelY: 644, label: 'ready',
  },
  {
    id: 'staging-ba', from: 'staging', to: 'ba',
    path: 'M 525,614 C 525,648 672,648 672,675',
    labelX: 610, labelY: 644, label: 'ready',
  },
  {
    id: 'tester-mikh', from: 'tester', to: 'mikhail',
    path: 'M 227,729 C 227,768 390,768 390,795',
    labelX: 298, labelY: 763, label: 'qa.report',
  },
  {
    id: 'ba-mikh', from: 'ba', to: 'mikhail',
    path: 'M 672,729 C 672,768 510,768 510,795',
    labelX: 602, labelY: 763, label: 'ux.report',
  },
  {
    id: 'mikh-prod', from: 'mikhail', to: 'production',
    path: 'M 450,855 L 450,910',
    labelX: 464, labelY: 886, label: 'release.approved',
  },
  // Feedback edges (dashed, orange)
  {
    id: 'tester-dev-fb', from: 'tester', to: 'developer',
    path: 'M 150,702 C 55,702 55,237 375,237',
    labelX: 68, labelY: 470, label: 'bug.found',
    dashed: true, feedback: true,
  },
  {
    id: 'ba-dev-fb', from: 'ba', to: 'developer',
    path: 'M 750,702 C 845,702 845,237 525,237',
    labelX: 833, labelY: 470, label: 'bug.found',
    dashed: true, feedback: true,
  },
]

// ─── Color schemes ────────────────────────────────────────────────────────────

function agentColors(status?: string) {
  if (status === 'running' || status === 'working') return { fill: '#1e3a5f', stroke: '#3b82f6', text: '#bfdbfe' }
  if (status === 'failed')                          return { fill: '#450a0a', stroke: '#ef4444', text: '#fecaca' }
  return { fill: '#052e16', stroke: '#22c55e', text: '#bbf7d0' }
}

const PROCESS_COLORS  = { fill: '#2d1b69', stroke: '#8b5cf6', text: '#ddd6fe' }
const ENV_COLORS      = { fill: '#1c1917', stroke: '#d97706', text: '#fde68a' }
const EXTERNAL_COLORS = { fill: '#111827', stroke: '#6b7280', text: '#d1d5db' }

function nodeColors(node: GraphNode, status?: string) {
  switch (node.type) {
    case 'agent':       return agentColors(status)
    case 'process':     return PROCESS_COLORS
    case 'environment': return ENV_COLORS
    case 'external':    return EXTERNAL_COLORS
  }
}

// ─── Inline SVG icons ─────────────────────────────────────────────────────────

function SvgIcon({ icon, cx, cy, size = 16, color }: {
  icon: string; cx: number; cy: number; size?: number; color: string
}) {
  const h = size / 2
  const s = size
  const st = { stroke: color, fill: 'none', strokeWidth: 1.5, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

  const inner = (() => {
    switch (icon) {
      case 'briefcase':
        return <>
          <rect x="1" y="4" width={s-2} height={s-5} rx="2" style={st}/>
          <path d={`M${s/2-3} 4 V2 a1 1 0 0 1 1-1 h4 a1 1 0 0 1 1 1 v2`} style={st}/>
          <line x1="1" y1="9" x2={s-1} y2="9" style={{...st, strokeWidth:1}}/>
        </>
      case 'code':
        return <>
          <polyline points={`${s*0.3},${s*0.25} ${s*0.05},${s/2} ${s*0.3},${s*0.75}`} style={st}/>
          <polyline points={`${s*0.7},${s*0.25} ${s*0.95},${s/2} ${s*0.7},${s*0.75}`} style={st}/>
        </>
      case 'flask':
        return <>
          <path d={`M${s*0.35} 2 v${s*0.35} L${s*0.05} ${s-2} h${s*0.9} L${s*0.65} ${s*0.35} V2`} style={st}/>
          <line x1={s*0.3} y1="2" x2={s*0.7} y2="2" style={st}/>
        </>
      case 'chart':
        return <>
          <line x1="2" y1={s-2} x2={s-2} y2={s-2} style={st}/>
          <rect x="3"       y={s*0.55} width={s*0.2} height={s*0.35} rx="1" fill={color} stroke="none"/>
          <rect x={s*0.4}   y={s*0.3}  width={s*0.2} height={s*0.6}  rx="1" fill={color} stroke="none"/>
          <rect x={s*0.73}  y={s*0.1}  width={s*0.2} height={s*0.8}  rx="1" fill={color} stroke="none"/>
        </>
      case 'gear':
        return <>
          <circle cx={s/2} cy={s/2} r={s*0.22} style={st}/>
          {[0,45,90,135,180,225,270,315].map(deg => {
            const r = deg * Math.PI / 180
            return (
              <line key={deg}
                x1={s/2 + Math.cos(r)*s*0.3} y1={s/2 + Math.sin(r)*s*0.3}
                x2={s/2 + Math.cos(r)*s*0.46} y2={s/2 + Math.sin(r)*s*0.46}
                style={{...st, strokeWidth: 2}}/>
            )
          })}
        </>
      case 'eye':
        return <>
          <path d={`M 1 ${s/2} C ${s*0.2} ${s*0.1} ${s*0.8} ${s*0.1} ${s-1} ${s/2} C ${s*0.8} ${s*0.9} ${s*0.2} ${s*0.9} 1 ${s/2}`} style={st}/>
          <circle cx={s/2} cy={s/2} r={s*0.2} style={st}/>
        </>
      case 'package':
        return <>
          <path d={`M${s/2} 1 L${s-1} ${s*0.3} V${s*0.7} L${s/2} ${s-1} L1 ${s*0.7} V${s*0.3} Z`} style={st}/>
          <line x1={s/2} y1="1" x2={s/2} y2={s-1} style={{...st, strokeWidth:1, strokeDasharray:'2,2'}}/>
          <line x1="1" y1={s*0.3} x2={s-1} y2={s*0.3} style={{...st, strokeWidth:1, strokeDasharray:'2,2'}}/>
        </>
      case 'chat':
        return <>
          <rect x="1" y="1" width={s-2} height={s*0.75} rx="3" style={st}/>
          <path d={`M${s*0.2} ${s*0.76} L${s*0.1} ${s-1} L${s*0.4} ${s*0.76}`} style={st}/>
          <line x1={s*0.25} y1={s*0.3} x2={s*0.75} y2={s*0.3} style={{...st, strokeWidth:1.5}}/>
          <line x1={s*0.25} y1={s*0.5} x2={s*0.6}  y2={s*0.5} style={{...st, strokeWidth:1.5}}/>
        </>
      default:
        return <circle cx={h} cy={h} r={h*0.5} stroke={color} strokeWidth={1.5} fill="none"/>
    }
  })()

  return <g transform={`translate(${cx - h},${cy - h})`}>{inner}</g>
}

// ─── Node renderer ────────────────────────────────────────────────────────────

function RenderNode({ node, status }: { node: GraphNode; status?: string }) {
  const colors = nodeColors(node, status)
  const cx = node.x + node.w / 2
  const cy = node.y + node.h / 2
  const isWorking = status === 'running' || status === 'working'
  const iconOffset = node.icon ? 10 : 0

  if (node.type === 'environment') {
    return (
      <g>
        {/* Double border outer */}
        <rect x={node.x - 6} y={node.y - 6} width={node.w + 12} height={node.h + 12}
          rx="3" fill="none" stroke={colors.stroke} strokeWidth="1.5" opacity="0.45"/>
        {/* Inner fill */}
        <rect x={node.x} y={node.y} width={node.w} height={node.h}
          rx="3" fill={colors.fill} stroke={colors.stroke} strokeWidth="2"/>
        <text x={cx} y={cy + 6} textAnchor="middle" fontSize="16" fontWeight="800"
          fill={colors.text} fontFamily="ui-monospace, monospace" letterSpacing="4">
          {node.label}
        </text>
      </g>
    )
  }

  if (node.type === 'process') {
    return (
      <g>
        {/* Pill shape */}
        <rect x={node.x} y={node.y} width={node.w} height={node.h}
          rx={node.h / 2} fill={colors.fill} stroke={colors.stroke} strokeWidth="2"/>
        {node.icon && (
          <SvgIcon icon={node.icon} cx={node.x + 26} cy={cy} size={16} color={colors.text}/>
        )}
        <text x={cx + iconOffset} y={cy - 5} textAnchor="middle" fontSize="13" fontWeight="600"
          fill={colors.text} fontFamily="ui-sans-serif, system-ui, sans-serif">
          {node.label}
        </text>
        {node.sublabel && (
          <text x={cx + iconOffset} y={cy + 9} textAnchor="middle" fontSize="9"
            fill={colors.text} opacity="0.7" fontFamily="ui-monospace, monospace">
            {node.sublabel}
          </text>
        )}
      </g>
    )
  }

  if (node.type === 'external') {
    return (
      <g>
        <rect x={node.x} y={node.y} width={node.w} height={node.h}
          rx="6" fill={colors.fill} stroke={colors.stroke} strokeWidth="1.5" strokeDasharray="7 4"/>
        <text x={cx} y={cy - (node.sublabel ? 6 : 0)} textAnchor="middle" fontSize="13" fontWeight="600"
          fill={colors.text} fontFamily="ui-sans-serif, system-ui, sans-serif">
          {node.label}
        </text>
        {node.sublabel && (
          <text x={cx} y={cy + 9} textAnchor="middle" fontSize="10"
            fill={colors.text} opacity="0.65" fontFamily="ui-monospace, monospace">
            {node.sublabel}
          </text>
        )}
      </g>
    )
  }

  // Agent
  return (
    <g filter={isWorking ? 'url(#glow)' : undefined}>
      {isWorking && (
        <rect x={node.x - 4} y={node.y - 4} width={node.w + 8} height={node.h + 8}
          rx="12" fill="none" stroke={colors.stroke} strokeWidth="2" opacity="0.4"
          className="animate-ping"/>
      )}
      <rect x={node.x} y={node.y} width={node.w} height={node.h}
        rx="8" fill={colors.fill} stroke={colors.stroke} strokeWidth="1.5"/>
      {node.icon && (
        <SvgIcon icon={node.icon} cx={node.x + 24} cy={cy} size={16} color={colors.text}/>
      )}
      <text x={cx + iconOffset} y={cy - (status ? 5 : 0)} textAnchor="middle" fontSize="13" fontWeight="600"
        fill={colors.text} fontFamily="ui-sans-serif, system-ui, sans-serif">
        {node.label}
      </text>
      {status && (
        <text x={cx + iconOffset} y={cy + 9} textAnchor="middle" fontSize="9"
          fill={colors.text} opacity="0.7" fontFamily="ui-monospace, monospace">
          {status}
        </text>
      )}
    </g>
  )
}

// ─── Edge renderer ────────────────────────────────────────────────────────────

function RenderEdge({ edge }: { edge: GraphEdge }) {
  const isFeedback = !!edge.feedback
  const strokeColor = isFeedback ? '#f97316' : '#4b5563'
  const textColor   = isFeedback ? '#fdba74' : '#9ca3af'
  const markerId    = isFeedback ? 'url(#arrow-fb)' : 'url(#arrow)'
  const labelLen    = edge.label.length

  return (
    <g>
      <path
        d={edge.path}
        stroke={strokeColor}
        strokeWidth="1.5"
        fill="none"
        strokeDasharray={edge.dashed ? '7 4' : undefined}
        markerEnd={markerId}
      />
      <rect
        x={edge.labelX - labelLen * 3.3}
        y={edge.labelY - 9}
        width={labelLen * 6.6}
        height={16}
        rx="3"
        fill="#0f172a"
        opacity="0.92"
      />
      <text
        x={edge.labelX}
        y={edge.labelY + 4}
        textAnchor="middle"
        fontSize="10"
        fill={textColor}
        fontFamily="ui-monospace, monospace"
      >
        {edge.label}
      </text>
    </g>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AgentGraphPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)

  const loadAgents = () => {
    setLoading(true)
    getAgents()
      .then(a => { setAgents(a); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { loadAgents() }, [])

  const statusMap: Record<string, string> = {}
  agents.forEach(a => { statusMap[a.id] = a.status })

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-white">Agent Release Graph</h2>
          <p className="text-gray-400 text-sm mt-1">
            Полный релизный цикл: агенты → CI/Review → среды → прод
          </p>
        </div>
        <button
          onClick={loadAgents}
          className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm text-gray-300 transition-colors self-start sm:self-auto"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`}/>
          Обновить
        </button>
      </div>

      {/* Graph */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-6 h-6 text-gray-500 animate-spin"/>
          </div>
        ) : (
          <svg
            viewBox="0 0 900 1000"
            className="w-full h-auto"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              {/* Arrow — default (gray) */}
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="#4b5563"/>
              </marker>
              {/* Arrow — feedback (orange) */}
              <marker id="arrow-fb" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="#f97316"/>
              </marker>
              {/* Glow for active/working agents */}
              <filter id="glow">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge>
                  <feMergeNode in="coloredBlur"/>
                  <feMergeNode in="SourceGraphic"/>
                </feMerge>
              </filter>
            </defs>

            {/* ── Edges (drawn first, behind nodes) ── */}
            {EDGES.map(edge => <RenderEdge key={edge.id} edge={edge}/>)}

            {/* ── Nodes ── */}
            {NODES.map(node => (
              <RenderNode key={node.id} node={node} status={statusMap[node.id]}/>
            ))}
          </svg>
        )}
      </div>

      {/* Legend */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-3 font-medium">Легенда</p>
        <div className="flex flex-wrap gap-x-6 gap-y-3 text-xs text-gray-400">

          <span className="flex items-center gap-2">
            <span className="inline-block w-5 h-5 rounded bg-green-950 border border-green-500 shrink-0"/>
            🟢 Агент (idle)
          </span>
          <span className="flex items-center gap-2">
            <span className="inline-block w-5 h-5 rounded bg-blue-950 border border-blue-500 shrink-0"/>
            🔵 Агент (working)
          </span>
          <span className="flex items-center gap-2">
            <span className="inline-block w-5 h-5 rounded bg-red-950 border border-red-500 shrink-0"/>
            🔴 Агент (failed)
          </span>

          <span className="flex items-center gap-2">
            <svg width="20" height="20" viewBox="0 0 20 20" className="shrink-0">
              <rect x="0" y="3" width="20" height="14" rx="7" fill="#2d1b69" stroke="#8b5cf6" strokeWidth="1.5"/>
            </svg>
            ◇ Процесс (CI / Review)
          </span>

          <span className="flex items-center gap-2">
            <svg width="20" height="20" viewBox="0 0 20 20" className="shrink-0">
              <rect x="0" y="0" width="20" height="20" rx="2" fill="#1c1917" stroke="#d97706" strokeWidth="1.5"/>
              <rect x="3" y="3" width="14" height="14" rx="1" fill="none" stroke="#d97706" strokeWidth="1"/>
            </svg>
            ╔╗ Среда (Staging / Production)
          </span>

          <span className="flex items-center gap-2">
            <svg width="20" height="14" viewBox="0 0 20 14" className="shrink-0">
              <rect x="0" y="1" width="20" height="12" rx="2" fill="#111827" stroke="#6b7280" strokeWidth="1.5" strokeDasharray="5 3"/>
            </svg>
            Внешний (GitHub / Human)
          </span>

          <span className="flex items-center gap-2">
            <svg width="24" height="10" viewBox="0 0 24 10" className="shrink-0">
              <line x1="0" y1="5" x2="20" y2="5" stroke="#f97316" strokeWidth="1.5" strokeDasharray="5 3"/>
              <path d="M17,2 L22,5 L17,8 z" fill="#f97316"/>
            </svg>
            ↩ Обратная связь (bug.found)
          </span>
        </div>
      </div>

    </div>
  )
}
