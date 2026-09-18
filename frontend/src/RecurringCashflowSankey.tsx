import { ResponsiveContainer, Sankey, Tooltip } from 'recharts'

import type { CashflowFlow, Category } from './api/types'
import { EmptyState, Icon, money } from './ui'

export type CashflowPeriodMonths = 1 | 3 | 6 | 12

const cashflowPeriods: Array<{ value: CashflowPeriodMonths; label: string }> = [
  { value: 1, label: '1mo' },
  { value: 3, label: '3mo' },
  { value: 6, label: '6mo' },
  { value: 12, label: '1an' },
]

export function CashflowPeriodSelector({
  value,
  onChange,
}: {
  value: CashflowPeriodMonths
  onChange: (value: CashflowPeriodMonths) => void
}) {
  return (
    <div className="segmented-control cashflow-period-selector" role="group" aria-label="Période du cashflow">
      {cashflowPeriods.map((period) => (
        <button
          className={value === period.value ? 'active' : ''}
          type="button"
          key={period.value}
          aria-pressed={value === period.value}
          onClick={() => onChange(period.value)}
        >
          {period.label}
        </button>
      ))}
    </div>
  )
}

export function RecurringCashflowSankey({
  categories,
  categoryFlows,
  sourceFlows,
}: {
  categories: Category[]
  categoryFlows: CashflowFlow[]
  sourceFlows: CashflowFlow[]
}) {
  const data = buildSankey(sourceFlows, categoryFlows, categories)
  return (
    <>
      <div className="sankey-mobile-summary">
        <span>
          {sourceFlows
            .filter((flow) => Number(flow.inflow) > 0)
            .map((flow) => flow.label)
            .join(', ') || 'Sources récurrentes'}
        </span>
        <Icon name="arrow" />
        <strong>Disponible</strong>
      </div>
      <div className="sankey-container">
        {data.links.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <Sankey
              data={data}
              link={CashflowSankeyLink}
              nodePadding={28}
              nodeWidth={12}
              node={CashflowSankeyNode}
              linkCurvature={0.52}
              iterations={32}
              margin={{ top: 20, right: 120, bottom: 20, left: 90 }}
              sort={false}
            >
              <Tooltip content={<CashflowTooltip />} />
            </Sankey>
          </ResponsiveContainer>
        ) : (
          <EmptyState
            icon="trend"
            text="Ajoutez au moins un revenu et une dépense récurrents pour construire le cashflow."
          />
        )}
      </div>
    </>
  )
}

function buildSankey(
  sourceFlows: CashflowFlow[],
  categoryFlows: CashflowFlow[],
  categories: Category[],
) {
  const sources = sourceFlows
    .filter((flow) => Number(flow.inflow) > 0)
    .map((flow) => ({
      name: flow.label,
      amount: Number(flow.inflow),
      color: '#16c79a',
    }))
    .sort((left, right) => right.amount - left.amount)
  const destinations = categoryFlows
    .filter((flow) => Number(flow.outflow) > 0)
    .map((flow) => ({
      name: flow.label,
      amount: Number(flow.outflow),
      color: categoryColor(flow, categories),
    }))
    .sort((left, right) => right.amount - left.amount)
  const totalIncome = sources.reduce((total, source) => total + source.amount, 0)
  const totalExpenses = destinations.reduce(
    (total, destination) => total + destination.amount,
    0,
  )
  const remainingAvailable = Math.round((totalIncome - totalExpenses) * 100) / 100
  if (remainingAvailable > 0) {
    destinations.push({
      name: 'Reste disponible',
      amount: remainingAvailable,
      color: '#16c79a',
    })
  }
  if (sources.length === 0 || destinations.length === 0) {
    return { nodes: [], links: [] }
  }

  const nodes = [
    ...sources.map((node) => ({ name: node.name, color: node.color, role: 'source' })),
    { name: 'Disponible', color: '#10a37f', role: 'hub' },
    ...destinations.map((node) => ({
      name: node.name,
      color: node.color,
      role: 'destination',
    })),
  ]
  const hubIndex = sources.length
  const links = [
    ...sources.map((node, index) => ({
      source: index,
      target: hubIndex,
      value: node.amount,
      color: node.color,
    })),
    ...destinations.map((node, index) => ({
      source: hubIndex,
      target: hubIndex + 1 + index,
      value: node.amount,
      color: node.color,
    })),
  ]
  return { nodes, links }
}

function categoryColor(flow: CashflowFlow, categories: Category[]): string {
  const rawCategoryId = flow.key.startsWith('category:')
    ? flow.key.slice('category:'.length)
    : ''
  const categoryId = Number(rawCategoryId)
  return Number.isInteger(categoryId)
    ? categories.find((category) => category.id === categoryId)?.color ?? '#85858c'
    : '#85858c'
}

interface CashflowSankeyLinkProps {
  sourceX: number
  sourceY: number
  sourceControlX: number
  targetX: number
  targetY: number
  targetControlX: number
  linkWidth: number
  payload: { color?: string }
}

function CashflowSankeyLink({
  sourceX,
  sourceY,
  sourceControlX,
  targetX,
  targetY,
  targetControlX,
  linkWidth,
  payload,
}: CashflowSankeyLinkProps) {
  return (
    <path
      className="cashflow-sankey-link"
      d={`M${sourceX},${sourceY} C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}`}
      fill="none"
      stroke={payload.color ?? '#85858c'}
      strokeOpacity={0.5}
      strokeWidth={Math.max(linkWidth, 1)}
    />
  )
}

function CashflowTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number | string }>
}) {
  const item = payload?.[0]
  if (!active || !item) return null
  return (
    <div className="cashflow-tooltip">
      <span>{item.name ?? 'Flux récurrent'}</span>
      <strong>{money(Number(item.value ?? 0))}</strong>
    </div>
  )
}

interface CashflowSankeyNodeProps {
  x: number
  y: number
  width: number
  height: number
  payload: {
    name: string
    color: string
    role: 'source' | 'hub' | 'destination'
  }
}

function CashflowSankeyNode({
  x,
  y,
  width,
  height,
  payload,
}: CashflowSankeyNodeProps) {
  const sourceNode = x < 200
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={Math.max(height, 3)}
        rx={3}
        fill={payload.color}
      />
      <text
        className={`sankey-node-label ${payload.role}`}
        x={sourceNode ? x + width + 9 : x - 9}
        y={y + Math.max(height, 12) / 2}
        fill="var(--text)"
        fontSize={12}
        textAnchor={sourceNode ? 'start' : 'end'}
        dominantBaseline="middle"
      >
        {payload.name}
      </text>
    </g>
  )
}
