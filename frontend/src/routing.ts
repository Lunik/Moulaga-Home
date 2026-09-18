import { useCallback, useEffect, useState } from 'react'

export type BudgetTab =
  | 'overview'
  | 'cashflow'
  | 'recurring'

export type WealthTab = 'overview' | 'holdings' | 'real-estate' | 'debts'
export type HoldingsTab = 'positions' | 'operations'
export type DocumentsTab = 'overview' | 'all' | 'missing'

export type WorkTab = 'overview' | 'salary' | 'pension'

export type Route =
  | { name: 'dashboard' }
  | { name: 'accounts' }
  | { name: 'account'; accountId: number }
  | { name: 'budget'; tab: BudgetTab; focusId?: number }
  | { name: 'wealth'; tab: WealthTab; holdingsTab?: HoldingsTab; focusId?: number }
  | { name: 'documents'; tab: DocumentsTab }
  | { name: 'work'; tab: WorkTab; focusId?: number }
  | { name: 'family' }
  | { name: 'settings' }

const budgetTabs = new Set<BudgetTab>([
  'overview',
  'cashflow',
  'recurring',
])
// Keep old bookmarks working after category creation moved to recurring series.
const legacyBudgetTabs: Record<string, BudgetTab> = {
  envelopes: 'recurring',
  manage: 'recurring',
}
const wealthTabs = new Set<WealthTab>(['overview', 'holdings', 'real-estate', 'debts'])
const holdingsTabs = new Set<HoldingsTab>(['positions', 'operations'])
const documentsTabs = new Set<DocumentsTab>(['overview', 'all', 'missing'])
const workTabs = new Set<WorkTab>(['overview', 'salary', 'pension'])

export function useRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    if (!window.location.hash) window.history.replaceState(null, '', routeHash({ name: 'dashboard' }))
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const navigate = useCallback((nextRoute: Route) => {
    const nextHash = routeHash(nextRoute)
    if (window.location.hash === nextHash) {
      setRoute(nextRoute)
    } else {
      window.location.hash = nextHash
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  return [route, navigate]
}

export function routeHash(route: Route): string {
  switch (route.name) {
    case 'dashboard':
    case 'accounts':
    case 'family':
    case 'settings':
      return `#/${route.name}`
    case 'account':
      return `#/accounts/${route.accountId}`
    case 'budget':
      return `#/budget/${route.tab}${route.focusId ? `/${route.focusId}` : ''}`
    case 'wealth':
      return `#/wealth/${route.tab}${
        route.tab === 'holdings' && route.holdingsTab && route.holdingsTab !== 'positions'
          ? `/${route.holdingsTab}`
          : route.focusId
            ? `/${route.focusId}`
            : ''
      }`
    case 'documents':
      return `#/documents/${route.tab}`
    case 'work':
      return `#/work/${route.tab}${route.focusId ? `/${route.focusId}` : ''}`
  }
}

function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'accounts' && parts[1]) {
    const accountId = Number(parts[1])
    if (Number.isInteger(accountId) && accountId > 0) return { name: 'account', accountId }
  }
  if (parts[0] === 'accounts') return { name: 'accounts' }
  if (parts[0] === 'budget') {
    const tab = parts[1] as BudgetTab
    if (budgetTabs.has(tab)) {
      const focusId = positiveInteger(parts[2])
      return focusId ? { name: 'budget', tab, focusId } : { name: 'budget', tab }
    }
    return { name: 'budget', tab: legacyBudgetTabs[parts[1]] ?? 'overview' }
  }
  if (parts[0] === 'wealth') {
    const tab = parts[1] as WealthTab
    if (wealthTabs.has(tab)) {
      if (tab === 'holdings' && holdingsTabs.has(parts[2] as HoldingsTab)) {
        return { name: 'wealth', tab, holdingsTab: parts[2] as HoldingsTab }
      }
      const focusId = positiveInteger(parts[2])
      return focusId ? { name: 'wealth', tab, focusId } : { name: 'wealth', tab }
    }
    return { name: 'wealth', tab: 'overview' }
  }
  if (parts[0] === 'documents') {
    const tab = parts[1] as DocumentsTab
    return { name: 'documents', tab: documentsTabs.has(tab) ? tab : 'overview' }
  }
  if (parts[0] === 'work') {
    const tab = parts[1] as WorkTab
    if (workTabs.has(tab)) {
      const focusId = positiveInteger(parts[2])
      return focusId ? { name: 'work', tab, focusId } : { name: 'work', tab }
    }
    return { name: 'work', tab: 'overview' }
  }
  if (parts[0] === 'family') return { name: 'family' }
  if (parts[0] === 'settings') return { name: 'settings' }
  return { name: 'dashboard' }
}

function positiveInteger(value: string | undefined): number | undefined {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
}
