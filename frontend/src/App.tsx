import { lazy, Suspense, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet } from './api/client'
import type { Account, AppSettings, Category, UserProfile } from './api/types'
import { ViewErrorBoundary } from './ErrorBoundary'
import { isRouteBeta } from './featureValidation'
import { ProfileBadge } from './ProfileOwnership'
import { ProfileGate } from './ProfileGate'
import { UpdatePromptCenter } from './UpdatePromptCenter'
import { useOnlineStatus } from './pwa'
import { type Route, useRoute } from './routing'
import { BetaBadge, Icon, configureUiPreferences, errorMessage, longToday } from './ui'

const AccountsView = lazy(() => import('./views/AccountsView').then((module) => ({ default: module.AccountsView })))
const AccountDetailView = lazy(() => import('./views/AccountsView').then((module) => ({ default: module.AccountDetailView })))
const BudgetView = lazy(() => import('./views/BudgetView').then((module) => ({ default: module.BudgetView })))
const DashboardView = lazy(() => import('./views/DashboardView').then((module) => ({ default: module.DashboardView })))
const DocumentsView = lazy(() => import('./views/DocumentsView').then((module) => ({ default: module.DocumentsView })))
const FamilyView = lazy(() => import('./views/FamilyView').then((module) => ({ default: module.FamilyView })))
const SettingsView = lazy(() => import('./views/SettingsView').then((module) => ({ default: module.SettingsView })))
const WealthView = lazy(() => import('./views/WealthView').then((module) => ({ default: module.WealthView })))
const WorkView = lazy(() => import('./views/WorkView').then((module) => ({ default: module.WorkView })))

const navigation: Array<{
  id: Route['name']
  label: string
  caption: string
  icon: Parameters<typeof Icon>[0]['name']
  route: Route
}> = [
  { id: 'dashboard', label: 'Tableau de bord', caption: "Vue d'ensemble", icon: 'grid', route: { name: 'dashboard' } },
  { id: 'accounts', label: 'Comptes', caption: 'Soldes & relevés', icon: 'accounts', route: { name: 'accounts' } },
  { id: 'budget', label: 'Budget', caption: 'Prévisions récurrentes', icon: 'budget', route: { name: 'budget', tab: 'overview' } },
  { id: 'wealth', label: 'Patrimoine', caption: 'Actifs & dettes', icon: 'wealth', route: { name: 'wealth', tab: 'overview' } },
  { id: 'documents', label: 'Documents', caption: 'Pièces & justificatifs', icon: 'documents', route: { name: 'documents', tab: 'overview' } },
  { id: 'work', label: 'Travail', caption: 'Salaires & retraite', icon: 'briefcase', route: { name: 'work', tab: 'overview' } },
  { id: 'family', label: 'Famille', caption: 'Foyer & membres', icon: 'family', route: { name: 'family' } },
  { id: 'settings', label: 'Paramètres', caption: 'Préférences locales', icon: 'settings', route: { name: 'settings' } },
]

const primaryNavigationIds: Array<Route['name']> = ['dashboard', 'accounts', 'budget']
const primaryNavigation = navigation.filter((item) => primaryNavigationIds.includes(item.id))
const secondaryNavigation = navigation.filter((item) => !primaryNavigationIds.includes(item.id))

export default function App() {
  return (
    <ProfileGate>
      {({ profile, profiles, inactivityTimeout, lock, switchProfile, manageProfiles }) => (
        <AuthenticatedApp
          activeProfile={profile}
          profiles={profiles}
          inactivityTimeout={inactivityTimeout}
          lock={lock}
          manageProfiles={manageProfiles}
          switchProfile={switchProfile}
        />
      )}
    </ProfileGate>
  )
}

function AuthenticatedApp({
  activeProfile,
  profiles,
  inactivityTimeout,
  lock,
  manageProfiles,
  switchProfile,
}: {
  activeProfile: UserProfile
  profiles: UserProfile[]
  inactivityTimeout: number | null
  lock: () => Promise<void>
  manageProfiles: () => void
  switchProfile: () => Promise<void>
}) {
  const [route, navigate] = useRoute()
  const queryClient = useQueryClient()
  const isOnline = useOnlineStatus()
  const accounts = useQuery({
    queryKey: ['accounts'],
    queryFn: () => apiGet<Account[]>('/accounts?include_archived=true'),
  })
  const categories = useQuery({
    queryKey: ['categories'],
    queryFn: () => apiGet<Category[]>('/categories?include_archived=true'),
  })
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiGet<AppSettings>('/preferences'),
  })
  const [hideNumericValues, setHideNumericValues] = usePrivacyMode()
  useProtectedProfileAutoLock(activeProfile.has_pin, inactivityTimeout, lock)
  configureUiPreferences(settings.data?.date_format, hideNumericValues)
  useAppearance(settings.data)

  const refreshCore = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-spending'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-cashflow'] }),
      queryClient.invalidateQueries({ queryKey: ['overview'] }),
      queryClient.invalidateQueries({ queryKey: ['monthly-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard-accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['debts'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
      queryClient.invalidateQueries({ queryKey: ['account-institution-history'] }),
      queryClient.invalidateQueries({ queryKey: ['shared-accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['work-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['work-contracts'] }),
      queryClient.invalidateQueries({ queryKey: ['work-payslips'] }),
      queryClient.invalidateQueries({ queryKey: ['work-pension'] }),
      queryClient.invalidateQueries({ queryKey: ['update-prompts'] }),
    ])
  }
  const firstError = [
    accounts.error,
    categories.error,
    settings.error,
  ].find(Boolean)
  const pageTitle = titleForRoute(route)
  const activeSection = route.name === 'account' ? 'accounts' : route.name

  return (
    <div className="app-shell" data-navigation={settings.data?.navigation_style ?? 'sidebar'}>
      <Sidebar activeSection={activeSection} isOnline={isOnline} navigate={navigate} />
      <main className="app-content">
        <header className="page-header">
          <div>
            <p className="page-date">{longToday()}</p>
            <div className="page-title">
              <h1>{pageTitle}</h1>
              {isRouteBeta(route) && <BetaBadge />}
            </div>
          </div>
          <div className="page-header-actions">
            {!isOnline && (
              <span className="offline-status" role="status">
                <Icon name="database" /> Hors ligne · données indisponibles
              </span>
            )}
            <UpdatePromptCenter
              activeProfile={activeProfile}
              isOnline={isOnline}
              navigate={navigate}
            />
            <button
              aria-label={hideNumericValues ? 'Afficher les valeurs' : 'Masquer les valeurs'}
              className={`privacy-toggle${hideNumericValues ? ' active' : ''}`}
              onClick={() => setHideNumericValues((hidden) => !hidden)}
              title={hideNumericValues ? 'Afficher les valeurs' : 'Masquer les valeurs'}
              type="button"
            >
              <Icon name={hideNumericValues ? 'eye-off' : 'eye'} />
            </button>
            <div className="active-profile-menu">
              <button
                aria-label={`Changer de profil depuis ${activeProfile.name}`}
                className="active-profile-button"
                onClick={() => void switchProfile()}
                title="Changer de profil"
                type="button"
              >
                <ProfileBadge profile={activeProfile} />
              </button>
              {activeProfile.has_pin && <button className="text-button" onClick={() => void lock()} type="button">Verrouiller</button>}
            </div>
          </div>
        </header>

        {firstError && route.name !== 'dashboard' && (
          <div className="error-banner" role="alert">Impossible de charger les données locales : {errorMessage(firstError)}</div>
        )}

        <ViewErrorBoundary key={window.location.hash}>
          <Suspense fallback={<div className="loading-card">Chargement de la vue…</div>}>
            {route.name === 'dashboard' && (
              <DashboardView
                categories={categories.data ?? []}
                navigate={navigate}
                onRefresh={refreshCore}
              />
            )}
            {route.name === 'accounts' && (
              <AccountsView
                accounts={accounts.data ?? []}
                activeProfile={activeProfile}
                profiles={profiles}
                navigate={navigate}
                onRefresh={refreshCore}
              />
            )}
            {route.name === 'account' && (
              <AccountDetailView
                accountId={route.accountId}
                accounts={accounts.data ?? []}
                activeProfile={activeProfile}
                profiles={profiles}
                navigate={navigate}
                onRefresh={refreshCore}
              />
            )}
            {route.name === 'budget' && (
              <BudgetView
                tab={route.tab}
                focusId={route.focusId}
                accounts={accounts.data ?? []}
                categories={categories.data ?? []}
                navigate={navigate}
                onRefresh={refreshCore}
              />
            )}
            {route.name === 'wealth' && (
              <WealthView
                tab={route.tab}
                holdingsTab={route.holdingsTab}
                focusId={route.focusId}
                accounts={accounts.data ?? []}
                activeProfile={activeProfile}
                profiles={profiles}
                navigate={navigate}
              />
            )}
            {route.name === 'documents' && (
              <DocumentsView tab={route.tab} navigate={navigate} />
            )}
            {route.name === 'work' && (
              <WorkView
                focusId={route.focusId}
                tab={route.tab}
                navigate={navigate}
                profileId={activeProfile.id}
              />
            )}
            {route.name === 'family' && (
              <FamilyView activeProfile={activeProfile} manageProfiles={manageProfiles} />
            )}
            {route.name === 'settings' && <SettingsView />}
          </Suspense>
        </ViewErrorBoundary>
      </main>
      <MobileNavigation activeSection={activeSection} navigate={navigate} />
    </div>
  )
}

function useProtectedProfileAutoLock(
  protectedByPin: boolean,
  timeoutSeconds: number | null,
  lock: () => Promise<void>,
) {
  useEffect(() => {
    if (!protectedByPin || !timeoutSeconds || timeoutSeconds <= 0) return
    let timer: number | undefined
    const schedule = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => { void lock() }, timeoutSeconds * 1000)
    }
    const events = ['pointerdown', 'keydown', 'touchstart', 'mousemove'] as const
    events.forEach((event) => window.addEventListener(event, schedule, { passive: true }))
    schedule()
    return () => {
      window.clearTimeout(timer)
      events.forEach((event) => window.removeEventListener(event, schedule))
    }
  }, [lock, protectedByPin, timeoutSeconds])
}

function usePrivacyMode() {
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem('moulaga-hide-numeric-values') === 'true'
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem('moulaga-hide-numeric-values', String(hidden))
    } catch {
      // Privacy mode remains available for the current session.
    }
    document.documentElement.dataset.numericValues = hidden ? 'hidden' : 'visible'
  }, [hidden])

  return [hidden, setHidden] as const
}

function Sidebar({
  activeSection,
  isOnline,
  navigate,
}: {
  activeSection: Route['name']
  isOnline: boolean
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
            <span className="nav-copy">
              <span className="nav-label">
                <strong>{item.label}</strong>
                {isRouteBeta(item.route) && <BetaBadge />}
              </span>
              <small>{item.caption}</small>
            </span>
            <Icon name="arrow" />
          </button>
        ))}
      </nav>
      <div className={`storage-status ${isOnline ? '' : 'offline'}`}>
        <span className="status-icon"><Icon name="database" /></span>
        <span>
          <strong>{isOnline ? 'Stockage local' : 'Mode hors ligne'}</strong>
          <small>{isOnline ? 'Base SQLite persistante' : 'Données financières indisponibles'}</small>
        </span>
        <span className={`status-dot ${isOnline ? '' : 'offline'}`} aria-label={isOnline ? 'Disponible' : 'Hors ligne'} />
      </div>
    </aside>
  )
}

function MobileNavigation({
  activeSection,
  navigate,
}: {
  activeSection: Route['name']
  navigate: (route: Route) => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const secondaryActive = secondaryNavigation.some((item) => item.id === activeSection)

  useEffect(() => {
    if (!menuOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [menuOpen])

  const goTo = (route: Route) => {
    setMenuOpen(false)
    navigate(route)
  }

  return (
    <>
      {menuOpen && (
        <button
          className="mobile-menu-backdrop"
          type="button"
          tabIndex={-1}
          aria-label="Fermer le menu"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <nav className="mobile-navigation" aria-label="Navigation principale">
        {menuOpen && (
          <div className="mobile-menu-sheet" id="mobile-navigation-menu">
            <p className="mobile-menu-title">Autres sections</p>
            {secondaryNavigation.map((item) => (
              <button
                className={`mobile-menu-item ${activeSection === item.id ? 'active' : ''}`}
                type="button"
                key={item.id}
                aria-current={activeSection === item.id ? 'page' : undefined}
                onClick={() => goTo(item.route)}
              >
                <span className="nav-icon"><Icon name={item.icon} /></span>
                <span className="nav-copy">
                  <span className="nav-label">
                    <strong>{item.label}</strong>
                    {isRouteBeta(item.route) && <BetaBadge />}
                  </span>
                  <small>{item.caption}</small>
                </span>
                <Icon name="arrow" />
              </button>
            ))}
          </div>
        )}
        <div className="mobile-navigation-bar">
          {primaryNavigation.map((item) => (
            <button
              className={`mobile-nav-item ${activeSection === item.id ? 'active' : ''}`}
              type="button"
              key={item.id}
              aria-current={activeSection === item.id ? 'page' : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => goTo(item.route)}
            >
              <Icon name={item.icon} />
            </button>
          ))}
          <button
            className={`mobile-nav-item ${menuOpen || secondaryActive ? 'active' : ''}`}
            type="button"
            aria-label="Autres sections"
            title="Autres sections"
            aria-expanded={menuOpen}
            aria-controls="mobile-navigation-menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <Icon name="menu" />
          </button>
        </div>
      </nav>
    </>
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
      root.lang = 'fr'
      document.querySelector('meta[name="theme-color"]')?.setAttribute(
        'content',
        effective === 'light' ? '#f4f4f6' : '#080809',
      )
    }
    applyTheme()
    const media = window.matchMedia('(prefers-color-scheme: light)')
    media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [settings?.theme])
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
      return 'Budget récurrent'
    case 'wealth':
      return 'Patrimoine'
    case 'documents':
      return 'Documents'
    case 'work':
      return 'Travail'
    case 'family':
      return 'Famille'
    case 'settings':
      return 'Paramètres'
  }
}
