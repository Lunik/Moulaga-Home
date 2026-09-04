import { lazy, Suspense, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet } from './api/client'
import type { Account, AppSettings, Category, MerchantIdentity, Transaction } from './api/types'
import { ViewErrorBoundary } from './ErrorBoundary'
import { type Route, useRoute } from './routing'
import { Icon, configureUiPreferences, errorMessage, longToday } from './ui'

const AccountsView = lazy(() => import('./views/AccountsView').then((module) => ({ default: module.AccountsView })))
const AccountDetailView = lazy(() => import('./views/AccountsView').then((module) => ({ default: module.AccountDetailView })))
const BudgetView = lazy(() => import('./views/BudgetView').then((module) => ({ default: module.BudgetView })))
const DashboardView = lazy(() => import('./views/DashboardView').then((module) => ({ default: module.DashboardView })))
const FamilyView = lazy(() => import('./views/FamilyView').then((module) => ({ default: module.FamilyView })))
const SettingsView = lazy(() => import('./views/SettingsView').then((module) => ({ default: module.SettingsView })))
const WealthView = lazy(() => import('./views/WealthView').then((module) => ({ default: module.WealthView })))

const navigation: Array<{
  id: Route['name']
  label: string
  caption: string
  icon: Parameters<typeof Icon>[0]['name']
  route: Route
}> = [
  { id: 'dashboard', label: 'Tableau de bord', caption: "Vue d'ensemble", icon: 'grid', route: { name: 'dashboard' } },
  { id: 'accounts', label: 'Comptes', caption: 'Soldes & relevés', icon: 'accounts', route: { name: 'accounts' } },
  { id: 'budget', label: 'Budget', caption: 'Cashflow & récurrents', icon: 'budget', route: { name: 'budget', tab: 'overview' } },
  { id: 'wealth', label: 'Patrimoine', caption: 'Actifs & dettes', icon: 'wealth', route: { name: 'wealth', tab: 'overview' } },
  { id: 'family', label: 'Famille', caption: 'Objectifs partagés', icon: 'family', route: { name: 'family' } },
  { id: 'settings', label: 'Paramètres', caption: 'Préférences locales', icon: 'settings', route: { name: 'settings' } },
]

export default function App() {
  const [route, navigate] = useRoute()
  const queryClient = useQueryClient()
  const accounts = useQuery({
    queryKey: ['accounts'],
    queryFn: () => apiGet<Account[]>('/accounts?include_archived=true'),
  })
  const categories = useQuery({
    queryKey: ['categories'],
    queryFn: () => apiGet<Category[]>('/categories?include_archived=true'),
  })
  const transactions = useQuery({
    queryKey: ['transactions'],
    queryFn: () => apiGet<Transaction[]>('/transactions?limit=1000'),
  })
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiGet<AppSettings>('/preferences'),
  })
  const merchants = useQuery({
    queryKey: ['merchants'],
    queryFn: () => apiGet<MerchantIdentity[]>('/merchants'),
    enabled: settings.data?.local_merchant_identities === true,
  })

  configureUiPreferences(settings.data?.language, settings.data?.date_format)
  useAppearance(settings.data)

  const refreshCore = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
      queryClient.invalidateQueries({ queryKey: ['transactions'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-spending'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-cashflow'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
    ])
  }
  const firstError = [
    accounts.error,
    categories.error,
    transactions.error,
    settings.error,
    settings.data?.local_merchant_identities ? merchants.error : null,
  ].find(Boolean)
  const pageTitle = titleForRoute(route)
  const activeSection = route.name === 'account' ? 'accounts' : route.name

  return (
    <div className="app-shell" data-navigation={settings.data?.navigation_style ?? 'sidebar'}>
      <Sidebar activeSection={activeSection} navigate={navigate} />
      <main className="app-content">
        <header className="page-header">
          <div>
            <p className="page-date">{longToday()}</p>
            <h1>{pageTitle}</h1>
          </div>
          {route.name !== 'settings' && route.name !== 'account' && (
            <button className="primary-button page-action" type="button" onClick={() => navigate({ name: 'budget', tab: 'transactions' })}>
              <Icon name="plus" />Ajouter une transaction
            </button>
          )}
        </header>

        {firstError && <div className="error-banner" role="alert">Impossible de charger les données locales : {errorMessage(firstError)}</div>}

        <ViewErrorBoundary key={window.location.hash}>
          <Suspense fallback={<div className="loading-card">Chargement de la vue…</div>}>
            {route.name === 'dashboard' && (
            <DashboardView
              accounts={accounts.data ?? []}
              merchants={settings.data?.local_merchant_identities ? merchants.data ?? [] : []}
              transactions={transactions.data ?? []}
              navigate={navigate}
            />
          )}
          {route.name === 'accounts' && (
            <AccountsView
              accounts={accounts.data ?? []}
              navigate={navigate}
              onRefresh={refreshCore}
            />
          )}
          {route.name === 'account' && (
            <AccountDetailView
              accountId={route.accountId}
              accounts={accounts.data ?? []}
              categories={categories.data ?? []}
              navigate={navigate}
              onRefresh={refreshCore}
            />
          )}
          {route.name === 'budget' && (
            <BudgetView
              tab={route.tab}
              accounts={accounts.data ?? []}
              categories={categories.data ?? []}
              merchants={settings.data?.local_merchant_identities ? merchants.data ?? [] : []}
              transactions={transactions.data ?? []}
              settings={settings.data}
              navigate={navigate}
              onRefresh={refreshCore}
            />
          )}
          {route.name === 'wealth' && <WealthView tab={route.tab} accounts={accounts.data ?? []} navigate={navigate} />}
          {route.name === 'family' && <FamilyView accounts={accounts.data ?? []} />}
            {route.name === 'settings' && <SettingsView />}
          </Suspense>
        </ViewErrorBoundary>
      </main>
    </div>
  )
}

function Sidebar({
  activeSection,
  navigate,
}: {
  activeSection: Route['name']
  navigate: (route: Route) => void
}) {
  return (
    <aside className="sidebar">
      <button className="brand" type="button" onClick={() => navigate({ name: 'dashboard' })}>
        <span className="brand-mark">M</span>
        <span><strong>Moulaga</strong><small>Finances privées</small></span>
      </button>
      <nav className="main-navigation" aria-label="Navigation principale">
        {navigation.map((item) => (
          <button
            className={`nav-item ${activeSection === item.id ? 'active' : ''}`}
            type="button"
            key={item.id}
            aria-current={activeSection === item.id ? 'page' : undefined}
            onClick={() => navigate(item.route)}
          >
            <span className="nav-icon"><Icon name={item.icon} /></span>
            <span className="nav-copy"><strong>{item.label}</strong><small>{item.caption}</small></span>
            <Icon name="arrow" />
          </button>
        ))}
      </nav>
      <div className="storage-status">
        <span className="status-icon"><Icon name="database" /></span>
        <span><strong>Stockage local</strong><small>Base SQLite persistante</small></span>
        <span className="status-dot" aria-label="Disponible" />
      </div>
    </aside>
  )
}

function useAppearance(settings?: AppSettings) {
  useEffect(() => {
    const root = document.documentElement
    const applyTheme = () => {
      const requested = settings?.theme ?? 'system'
      const effective = requested === 'system'
        ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
        : requested
      root.dataset.theme = effective
      root.lang = settings?.language ?? 'fr'
      document.querySelector('meta[name="theme-color"]')?.setAttribute(
        'content',
        effective === 'light' ? '#f4f4f6' : '#080809',
      )
    }
    applyTheme()
    const media = window.matchMedia('(prefers-color-scheme: light)')
    media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [settings?.language, settings?.theme])
}

function titleForRoute(route: Route): string {
  switch (route.name) {
    case 'dashboard':
      return 'Tableau de bord'
    case 'accounts':
      return 'Comptes'
    case 'account':
      return 'Détail du compte'
    case 'budget':
      return 'Budget & Cashflow'
    case 'wealth':
      return 'Patrimoine'
    case 'family':
      return 'Famille'
    case 'settings':
      return 'Paramètres'
  }
}
