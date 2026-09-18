import { useEffect, useState } from 'react'
import { ResponsiveContainer, Sankey, Tooltip } from 'recharts'

import type { CashflowFlow, Category } from './api/types'
import { effectiveCategoryParentIds } from './categoryHierarchy'
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
  const compact = useNarrowViewport()
  const data = buildSankey(sourceFlows, categoryFlows, categories, compact)
  const chartHeight = Math.max(
    compact ? 400 : 432,
    data.maxColumnNodes * 34 + 54,
  )
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
      <small className="sankey-scroll-hint">
        Faites glisser le graphique pour suivre les sous-catégories.
      </small>
      <div className="sankey-container" style={{ height: chartHeight }}>
        {data.links.length > 0 ? (
          <div className="sankey-chart">
            <ResponsiveContainer width="100%" height="100%">
              <Sankey
                data={data}
                link={CashflowSankeyLink}
                nodePadding={28}
                nodeWidth={12}
                node={CashflowSankeyNode}
                linkCurvature={0.52}
                iterations={32}
                margin={compact
                  ? { top: 34, right: 28, bottom: 18, left: 24 }
                  : { top: 34, right: 90, bottom: 20, left: 90 }}
                sort={false}
              >
                <Tooltip content={<CashflowTooltip />} />
              </Sankey>
            </ResponsiveContainer>
          </div>
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

function useNarrowViewport() {
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 680px)').matches)

  useEffect(() => {
    const media = window.matchMedia('(max-width: 680px)')
    const update = () => setNarrow(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  return narrow
}

function buildSankey(
  sourceFlows: CashflowFlow[],
  categoryFlows: CashflowFlow[],
  categories: Category[],
  compact: boolean,
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
      flow,
      amount: Number(flow.outflow),
      categoryId: categoryIdFromFlow(flow),
    }))
    .sort((left, right) => right.amount - left.amount)
  const totalIncome = sources.reduce((total, source) => total + source.amount, 0)
  const totalExpenses = destinations.reduce(
    (total, destination) => total + destination.amount,
    0,
  )
  const remainingAvailable = Math.round((totalIncome - totalExpenses) * 100) / 100
  if (sources.length === 0 || (destinations.length === 0 && remainingAvailable <= 0)) {
    return { nodes: [], links: [], maxColumnNodes: 0 }
  }

  const categoryById = new Map(
    categories
      .filter((category) => category.kind === 'expense' && !category.archived)
      .map((category) => [category.id, category]),
  )
  const effectiveParents = effectiveCategoryParentIds(categories)
  const categoryNodes = new Map<string, CashflowNode>()
  const categoryLinks = new Map<string, CashflowLink>()

  for (const destination of destinations) {
    const path = categoryPath(destination.categoryId, categoryById, effectiveParents)
    const resolvedPath = path.length > 0
      ? path.map((category) => ({
          key: `category:${category.id}`,
          name: category.name,
          color: category.color,
        }))
      : [{
          key: destination.flow.key,
          name: destination.flow.label,
          color: '#85858c',
        }]

    for (const [depth, category] of resolvedPath.entries()) {
      const existing = categoryNodes.get(category.key)
      categoryNodes.set(category.key, {
        ...category,
        role: 'destination',
        depth,
        amount: (existing?.amount ?? 0) + destination.amount,
      })
      const sourceKey = depth === 0 ? 'hub' : resolvedPath[depth - 1].key
      const linkKey = `${sourceKey}->${category.key}`
      const existingLink = categoryLinks.get(linkKey)
      categoryLinks.set(linkKey, {
        sourceKey,
        targetKey: category.key,
        value: (existingLink?.value ?? 0) + destination.amount,
        color: category.color,
      })
    }
  }

  const orderedCategoryNodes = orderCategoryNodes(categoryNodes, categoryLinks)
  const nodes: CashflowNode[] = [
    ...(!compact
      ? sources.map((node) => ({
          key: `source:${node.name}`,
          name: node.name,
          color: node.color,
          role: 'source' as const,
          depth: 0,
          amount: node.amount,
        }))
      : []),
    {
      key: 'hub',
      name: 'Disponible',
      color: '#10a37f',
      role: 'hub',
      depth: 0,
      amount: totalIncome,
    },
    ...orderedCategoryNodes,
  ]
  if (remainingAvailable > 0) {
    nodes.push({
      key: 'remaining',
      name: 'Reste disponible',
      color: '#16c79a',
      role: 'destination',
      depth: 0,
      amount: remainingAvailable,
    })
  }

  const nodeIndexByKey = new Map(nodes.map((node, index) => [node.key, index]))
  const hubIndex = compact ? 0 : sources.length
  const links: SankeyLink[] = [
    ...(!compact
      ? sources.map((node, index) => ({
          source: index,
          target: hubIndex,
          value: node.amount,
          color: node.color,
        }))
      : []),
    ...[...categoryLinks.values()].map((link) => ({
      source: nodeIndexByKey.get(link.sourceKey) ?? hubIndex,
      target: nodeIndexByKey.get(link.targetKey) ?? hubIndex,
      value: link.value,
      color: link.color,
    })),
  ]
  if (remainingAvailable > 0) {
    links.push({
      source: hubIndex,
      target: nodeIndexByKey.get('remaining') ?? hubIndex,
      value: remainingAvailable,
      color: '#16c79a',
    })
  }

  const maxCategoryDepth = Math.max(
    0,
    ...orderedCategoryNodes.map((category) => category.depth),
  )
  const parentCategoryKeys = new Set(
    [...categoryLinks.values()]
      .filter((link) => link.sourceKey !== 'hub')
      .map((link) => link.sourceKey),
  )
  const shallowLeafKeys = orderedCategoryNodes.filter(
    (category) => category.depth < maxCategoryDepth && !parentCategoryKeys.has(category.key),
  ).map((category) => category.key)
  if (remainingAvailable > 0 && maxCategoryDepth > 0) {
    shallowLeafKeys.push('remaining')
  }
  if (shallowLeafKeys.length > 0) {
    const spacerIndex = nodes.push({
      key: 'depth-spacer',
      name: '',
      color: 'transparent',
      role: 'spacer',
      depth: maxCategoryDepth,
      amount: 0,
    }) - 1
    for (const categoryKey of shallowLeafKeys) {
      links.push({
        source: nodeIndexByKey.get(categoryKey) ?? hubIndex,
        target: spacerIndex,
        value: 0.000001,
        color: 'transparent',
        hidden: true,
      })
    }
  }
  return {
    nodes,
    links,
    maxColumnNodes: maxSankeyColumnNodes(nodes.length, links),
  }
}

function orderCategoryNodes(
  categoryNodes: Map<string, CashflowNode>,
  categoryLinks: Map<string, CashflowLink>,
): CashflowNode[] {
  const childrenByParent = new Map<string, CashflowNode[]>()
  for (const link of categoryLinks.values()) {
    const target = categoryNodes.get(link.targetKey)
    if (!target) continue
    childrenByParent.set(link.sourceKey, [
      ...(childrenByParent.get(link.sourceKey) ?? []),
      target,
    ])
  }
  for (const children of childrenByParent.values()) {
    children.sort(
      (left, right) =>
        right.amount - left.amount || left.name.localeCompare(right.name, 'fr'),
    )
  }

  const ordered: CashflowNode[] = []
  const visited = new Set<string>()
  const visitChildren = (parentKey: string) => {
    for (const child of childrenByParent.get(parentKey) ?? []) {
      if (visited.has(child.key)) continue
      visited.add(child.key)
      ordered.push(child)
      visitChildren(child.key)
    }
  }
  visitChildren('hub')

  for (const node of categoryNodes.values()) {
    if (!visited.has(node.key)) ordered.push(node)
  }
  return ordered
}

function maxSankeyColumnNodes(nodeCount: number, links: SankeyLink[]): number {
  const depths = Array<number>(nodeCount).fill(0)
  const outgoingCounts = Array<number>(nodeCount).fill(0)

  for (const link of links) {
    outgoingCounts[link.source] += 1
  }
  for (let pass = 0; pass < nodeCount; pass += 1) {
    let changed = false
    for (const link of links) {
      const targetDepth = depths[link.source] + 1
      if (targetDepth > depths[link.target]) {
        depths[link.target] = targetDepth
        changed = true
      }
    }
    if (!changed) break
  }

  const maxDepth = Math.max(0, ...depths)
  const columnCounts = new Map<number, number>()
  for (let nodeIndex = 0; nodeIndex < nodeCount; nodeIndex += 1) {
    const depth = outgoingCounts[nodeIndex] === 0 ? maxDepth : depths[nodeIndex]
    columnCounts.set(depth, (columnCounts.get(depth) ?? 0) + 1)
  }
  return Math.max(0, ...columnCounts.values())
}

interface CashflowNode {
  key: string
  name: string
  color: string
  role: 'source' | 'hub' | 'destination' | 'spacer'
  depth: number
  amount: number
}

interface CashflowLink {
  sourceKey: string
  targetKey: string
  value: number
  color: string
}

interface SankeyLink {
  source: number
  target: number
  value: number
  color: string
  hidden?: boolean
}

function categoryIdFromFlow(flow: CashflowFlow): number | null {
  const rawCategoryId = flow.key.startsWith('category:')
    ? flow.key.slice('category:'.length)
    : ''
  const categoryId = Number(rawCategoryId)
  return Number.isInteger(categoryId) ? categoryId : null
}

function categoryPath(
  categoryId: number | null,
  categoryById: Map<number, Category>,
  effectiveParents: Map<number, number | null>,
): Category[] {
  if (categoryId === null || !categoryById.has(categoryId)) return []
  const path: Category[] = []
  const visited = new Set<number>()
  let currentId: number | null = categoryId
  while (currentId !== null && !visited.has(currentId)) {
    visited.add(currentId)
    const category = categoryById.get(currentId)
    if (!category) break
    path.unshift(category)
    currentId = effectiveParents.get(currentId) ?? null
  }
  return path
}

interface CashflowSankeyLinkProps {
  sourceX: number
  sourceY: number
  sourceControlX: number
  targetX: number
  targetY: number
  targetControlX: number
  linkWidth: number
  payload: { color?: string; hidden?: boolean }
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
  if (payload.hidden) return <path aria-hidden="true" d="" />
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
    role: 'source' | 'hub' | 'destination' | 'spacer'
  }
}

function CashflowSankeyNode({
  x,
  y,
  width,
  height,
  payload,
}: CashflowSankeyNodeProps) {
  if (payload.role === 'spacer') return <g aria-hidden="true" />
  const destinationNode = payload.role === 'destination'
  const sourceNode = payload.role === 'source'
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
        x={destinationNode ? x + width / 2 : sourceNode ? x + width + 9 : x - 9}
        y={destinationNode ? Math.max(y - 8, 14) : y + Math.max(height, 12) / 2}
        fill="var(--text)"
        fontSize={12}
        textAnchor={destinationNode ? 'middle' : sourceNode ? 'start' : 'end'}
        dominantBaseline="middle"
      >
        {payload.name}
      </text>
    </g>
  )
}
