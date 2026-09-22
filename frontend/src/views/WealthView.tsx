import { Fragment, FormEvent, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiDelete, apiGet, apiPatch, apiPost, apiUpload } from '../api/client'
import {
  AttachmentManager,
  AttachmentPicker,
  uploadOwnerAttachment,
} from '../AttachmentManager'
import type {
  Account,
  AssetPerformancePoint,
  Debt,
  Holding,
  HoldingOperation,
  HoldingOperationResult,
  NetWorthPoint,
  NetWorthSummary,
  PerformancePoint,
  PortfolioAllocation,
  PortfolioSummary,
  RealEstateAsset,
  RecurringSeries,
  UserProfile,
} from '../api/types'
import { ProfileOwnership } from '../ProfileOwnership'
import { supportsHoldings } from '../accountCapabilities'
import { routeHash, type HoldingsTab, type Route, type WealthTab } from '../routing'
import {
  DatePicker,
  EmptyState,
  Field,
  FormInput,
  FormSelect,
  Icon,
  LinkedEntityLink,
  Modal,
  Panel,
  ProgressBar,
  StatusBadge,
  chartTooltipStyle,
  compactMoney,
  errorMessage,
  formatDate,
  initials,
  linkedEntityTargetId,
  localDateInputValue,
  maskNumericValue,
  monthBoundaryDate,
  monthInputValue,
  money,
  signedMoney,
  useLinkedEntityFocus,
} from '../ui'

const allocationColors = ['#615fff', '#16c79a', '#1da9e8', '#f97316', '#8758f6', '#ec4899', '#f7b500']

type HoldingSort =
  | 'default'
  | 'market-value-desc'
  | 'market-value-asc'
  | 'gain-desc'
  | 'gain-asc'
  | 'gain-percent-desc'
  | 'gain-percent-asc'

export function WealthView({
  tab,
  holdingsTab = 'positions',
  focusId,
  accounts,
  activeProfile,
  profiles,
  navigate,
}: {
  tab: WealthTab
  holdingsTab?: HoldingsTab
  focusId?: number
  accounts: Account[]
  activeProfile: UserProfile
  profiles: UserProfile[]
  navigate: (route: Route) => void
}) {
  const tabsRef = useRef<HTMLElement>(null)
  const summary = useQuery({
    queryKey: ['wealth-summary'],
    queryFn: () => apiGet<PortfolioSummary>('/portfolio/summary'),
  })
  const netWorth = useQuery({
    queryKey: ['net-worth'],
    queryFn: () => apiGet<NetWorthSummary>('/networth/overview'),
  })
  const netWorthHistory = useQuery({
    queryKey: ['net-worth-history'],
    queryFn: () => apiGet<NetWorthPoint[]>('/networth/history'),
  })
  const holdings = useQuery({
    queryKey: ['holdings'],
    queryFn: () => apiGet<Holding[]>('/holdings'),
  })
  const debts = useQuery({
    queryKey: ['debts'],
    queryFn: () => apiGet<Debt[]>('/debts'),
  })
  const recurringSeries = useQuery({
    queryKey: ['recurring-series'],
    queryFn: () => apiGet<RecurringSeries[]>('/recurring'),
  })
  const realEstate = useQuery({
    queryKey: ['real-estate'],
    queryFn: () => apiGet<RealEstateAsset[]>('/real-estate'),
  })
  const performance = useQuery({
    queryKey: ['portfolio-performance'],
    queryFn: () => apiGet<PerformancePoint[]>('/portfolio/performance'),
  })
  const assetPerformance = useQuery({
    queryKey: ['asset-performance'],
    queryFn: () => apiGet<AssetPerformancePoint[]>('/holdings/performance'),
  })
  const allocation = useQuery({
    queryKey: ['portfolio-allocation'],
    queryFn: () => apiGet<PortfolioAllocation[]>('/portfolio/allocation'),
  })
  const errors = [
    summary.error,
    netWorth.error,
    netWorthHistory.error,
    holdings.error,
    debts.error,
    recurringSeries.error,
    realEstate.error,
    performance.error,
    assetPerformance.error,
    allocation.error,
  ].filter(Boolean)

  useLayoutEffect(() => {
    const tabs = tabsRef.current
    const activeTab = tabs?.querySelector<HTMLButtonElement>('.active')
    if (!tabs || !activeTab) return
    const tabsBounds = tabs.getBoundingClientRect()
    const activeBounds = activeTab.getBoundingClientRect()
    tabs.scrollLeft += activeBounds.left
      - tabsBounds.left
      - (tabs.clientWidth - activeTab.clientWidth) / 2
  }, [tab])

  return (
    <div className="view-stack">
      <nav className="module-tabs" aria-label="Patrimoine" ref={tabsRef}>
        <button className={tab === 'overview' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'overview' })}>
          <Icon name="wealth" /> Vue d'ensemble
        </button>
        <button className={tab === 'holdings' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'holdings' })}>
          <Icon name="holdings" /> Actifs
        </button>
        <button className={tab === 'real-estate' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'real-estate' })}>
          <Icon name="home" /> Immobilier
        </button>
        <button className={tab === 'debts' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'debts' })}>
          <Icon name="debt" /> Dettes
        </button>
      </nav>

      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}

      {tab === 'overview' && (
        <WealthOverview
          allocation={allocation.data ?? []}
          netWorth={netWorth.data}
          netWorthHistory={netWorthHistory.data ?? []}
          performance={performance.data ?? []}
          summary={summary.data}
        />
      )}
      {tab === 'holdings' && (
        <AssetsPanel
          accounts={accounts}
          focusId={focusId}
          performance={assetPerformance.data ?? []}
          holdings={holdings.data ?? []}
          navigate={navigate}
          view={holdingsTab}
        />
      )}
      {tab === 'real-estate' && (
        <RealEstatePanel
          assets={realEstate.data ?? []}
          debts={debts.data ?? []}
          focusId={focusId}
          activeProfile={activeProfile}
          profiles={profiles}
        />
      )}
      {tab === 'debts' && (
        <DebtsPanel
          accounts={accounts}
          debts={debts.data ?? []}
          assets={realEstate.data ?? []}
          focusId={focusId}
          recurringSeries={recurringSeries.data ?? []}
          activeProfile={activeProfile}
          profiles={profiles}
        />
      )}
    </div>
  )
}

function WealthOverview({
  allocation,
  netWorth,
  netWorthHistory,
  performance,
  summary,
}: {
  allocation: PortfolioAllocation[]
  netWorth?: NetWorthSummary
  netWorthHistory: NetWorthPoint[]
  performance: PerformancePoint[]
  summary?: PortfolioSummary
}) {
  const allocationData = allocation.map((slice, index) => ({
    ...slice,
    name: assetLabel(slice.asset_class),
    numericValue: Number(slice.market_value),
    percentage: Number(slice.weight) * 100,
    color: allocationColors[index % allocationColors.length],
  }))
  const assets = Number(netWorth?.cash ?? 0)
    + Number(netWorth?.investments ?? 0)
    + Number(netWorth?.real_estate ?? 0)
  const totalGain = Number(summary?.total_gain ?? summary?.gain ?? 0)
  const totalCostBasis = Number(summary?.total_cost_basis ?? summary?.cost_basis ?? 0)
  const gainPercent = totalCostBasis > 0
    ? (totalGain / totalCostBasis) * 100
    : 0
  const netWorthChartData = [...netWorthHistory]
    .sort((left, right) => left.period.localeCompare(right.period))
    .map((point) => ({
      ...point,
      net_worth: Number(point.net_worth),
    }))
  const netWorthValues = netWorthChartData.map((point) => point.net_worth)
  const netWorthMinimum = Math.min(0, ...netWorthValues)
  const netWorthMaximum = Math.max(0, ...netWorthValues)
  const netWorthRange = netWorthMaximum - netWorthMinimum
  const netWorthZeroOffset = netWorthRange > 0
    ? `${(netWorthMaximum / netWorthRange) * 100}%`
    : '0%'
  const performanceData = [...performance]
    .sort((left, right) => left.period.localeCompare(right.period))
    .map((point) => ({
      ...point,
      market_value: Number(point.market_value ?? 0),
      cost_basis: Number(point.cost_basis ?? 0),
      realized_gain: Number(point.realized_gain ?? 0),
      unrealized_gain: Number(point.unrealized_gain ?? 0),
      total_gain: Number(point.total_gain ?? point.gain ?? 0),
    }))

  return (
    <>
      <section className="wealth-hero">
        <div>
          <p className="eyebrow">Patrimoine net</p>
          <p className="hero-value">{money(netWorth?.net_worth)}</p>
          <div className="wealth-equation">
            <span>Actifs <strong>{money(assets)}</strong></span>
            <i>−</i>
            <span>Dettes <strong className="negative">{money(netWorth?.debts)}</strong></span>
          </div>
          <small>Les liquidités proviennent des derniers relevés de comptes.</small>
        </div>
        <div className="wealth-performance">
          <span className={totalGain >= 0 ? 'positive' : 'negative'}>
            <Icon name="trend" />
            {signedMoney(summary?.total_gain ?? summary?.gain ?? 0, true)}
          </span>
          <small>{gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}% de performance</small>
          <small className={Number(summary?.realized_gain ?? 0) >= 0 ? 'positive' : 'negative'}>
            Réalisé : {signedMoney(summary?.realized_gain ?? 0, true)}
          </small>
          <small className={Number(summary?.unrealized_gain ?? 0) >= 0 ? 'positive' : 'negative'}>
            Latent : {signedMoney(summary?.unrealized_gain ?? 0, true)}
          </small>
        </div>
      </section>

      <section className="dashboard-grid">
        <Panel title="Évolution du patrimoine net" subtitle="Relevés de comptes et valorisations patrimoniales">
          <div className="chart-container tall-chart">
            {netWorthChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={netWorthChartData} margin={{ top: 12, right: 10, left: -8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="net-worth-stroke" x1="0" x2="0" y1="0" y2="1">
                      <stop offset={netWorthZeroOffset} stopColor="#16c79a" />
                      <stop offset={netWorthZeroOffset} stopColor="#e11d48" />
                    </linearGradient>
                    <linearGradient id="net-worth-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset={netWorthZeroOffset} stopColor="#16c79a" stopOpacity={0.04} />
                      <stop offset={netWorthZeroOffset} stopColor="#e11d48" stopOpacity={0.04} />
                      <stop offset="100%" stopColor="#e11d48" stopOpacity={0.3} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} padding={{ top: 12 }} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
                  <Area dataKey="net_worth" name="Patrimoine net" type="monotone" stroke="url(#net-worth-stroke)" strokeWidth={2.5} fill="url(#net-worth-fill)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState icon="trend" text="L'historique apparaîtra avec les premiers relevés mensuels." />
            )}
          </div>
        </Panel>

        <Panel title="Allocation" subtitle="Répartition de vos actifs">
          <div className="distribution-layout wealth-distribution">
            <div className="donut-container">
              {allocationData.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={allocationData} dataKey="numericValue" innerRadius="64%" outerRadius="88%" paddingAngle={2} stroke="none">
                        {allocationData.map((allocation) => <Cell key={allocation.asset_class} fill={allocation.color} />)}
                      </Pie>
                      <Tooltip contentStyle={chartTooltipStyle} itemStyle={{ color: 'var(--text)' }} labelStyle={{ color: 'var(--text)' }} label="" formatter={(value) => money(Number(value))} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-label">
                    <strong>{compactMoney(Number(summary?.market_value ?? 0))}</strong>
                    <span>EUR</span>
                  </div>
                </>
              ) : (
                <EmptyState icon="holdings" text="Ajoutez des actifs pour afficher leur répartition." />
              )}
            </div>
            <div className="distribution-list">
              {allocationData.map((slice) => (
                <div key={slice.asset_class}>
                  <span><i style={{ background: slice.color }} />{slice.name}</span>
                  <strong>{maskNumericValue(`${slice.percentage.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%`)}</strong>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </section>

      <section className="dashboard-grid full-width-grid">
        <Panel title="Plus-value / moins-value" subtitle="Valeur du portefeuille, capital investi et gains réalisés">
          <div className="chart-container">
            {performanceData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={performanceData} margin={{ top: 12, right: 12, left: -8, bottom: 0 }}>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
                  <Line dataKey="market_value" name="Valeur" type="monotone" stroke="#615fff" strokeWidth={2.5} dot={false} />
                  <Line dataKey="cost_basis" name="Capital investi" type="monotone" stroke="#f97316" strokeWidth={2.2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState icon="trend" text="La performance sera calculée à partir des relevés et positions." />
            )}
          </div>
          <div className="wealth-performance-breakdown">
            <span>
              <small>Performance totale</small>
              <strong className={totalGain >= 0 ? 'positive' : 'negative'}>
                {signedMoney(summary?.total_gain ?? summary?.gain ?? 0, true)}
              </strong>
            </span>
            <span>
              <small>Plus-values réalisées</small>
              <strong className={Number(summary?.realized_gain ?? 0) >= 0 ? 'positive' : 'negative'}>
                {signedMoney(summary?.realized_gain ?? 0, true)}
              </strong>
            </span>
            <span>
              <small>Plus-values latentes</small>
              <strong className={Number(summary?.unrealized_gain ?? 0) >= 0 ? 'positive' : 'negative'}>
                {signedMoney(summary?.unrealized_gain ?? 0, true)}
              </strong>
            </span>
          </div>
        </Panel>
      </section>
    </>
  )
}

function AssetsPanel({
  accounts,
  focusId,
  holdings,
  navigate,
  performance,
  view,
}: {
  accounts: Account[]
  focusId?: number
  holdings: Holding[]
  navigate: (route: Route) => void
  performance: AssetPerformancePoint[]
  view: HoldingsTab
}) {
  const queryClient = useQueryClient()
  const [showOperationModal, setShowOperationModal] = useState(false)
  const selectableAccounts = useMemo(
    () => accounts.filter((account) => !account.archived && supportsHoldings(account.type)),
    [accounts],
  )
  const selectableAccountIds = useMemo(
    () => new Set(selectableAccounts.map((account) => account.id)),
    [selectableAccounts],
  )
  const operationalHoldings = useMemo(
    () => holdings.filter((holding) => selectableAccountIds.has(holding.account_id)),
    [holdings, selectableAccountIds],
  )
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['holdings'] }),
      queryClient.invalidateQueries({ queryKey: ['holding-operations'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
      queryClient.invalidateQueries({ queryKey: ['portfolio-performance'] }),
      queryClient.invalidateQueries({ queryKey: ['asset-performance'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
    ])
  }

  return (
    <>
      <section className="section-intro">
        <p>Valorisez vos positions sans synchronisation bancaire externe.</p>
        <button className="primary-button" type="button" onClick={() => setShowOperationModal(true)}>
          <Icon name="plus" /> Ajouter une opération
        </button>
      </section>
      {showOperationModal && (
        <HoldingOperationModal
          accounts={selectableAccounts}
          holdings={operationalHoldings}
          onClose={() => setShowOperationModal(false)}
          onSaved={async () => {
            await refresh()
            setShowOperationModal(false)
          }}
        />
      )}
      <AssetPerformanceChart performance={performance} />
      <nav className="module-tabs asset-subtabs" aria-label="Vues des actifs">
        <button
          className={view === 'positions' ? 'active' : ''}
          type="button"
          onClick={() => navigate({ name: 'wealth', tab: 'holdings', holdingsTab: 'positions' })}
        >
          <Icon name="holdings" /> Positions
        </button>
        <button
          className={view === 'operations' ? 'active' : ''}
          type="button"
          onClick={() => navigate({ name: 'wealth', tab: 'holdings', holdingsTab: 'operations' })}
        >
          <Icon name="calendar" /> Opérations
        </button>
      </nav>
      {view === 'positions' ? (
        <HoldingsPanel
          accounts={accounts}
          focusId={focusId}
          holdings={holdings}
          onChanged={refresh}
          selectableAccounts={selectableAccounts}
        />
      ) : (
        <HoldingOperationsPanel
          accounts={accounts}
          holdings={holdings}
          onChanged={refresh}
          selectableAccounts={selectableAccounts}
        />
      )}
    </>
  )
}

function AssetPerformanceChart({ performance }: { performance: AssetPerformancePoint[] }) {
  const data = [...performance]
    .sort((left, right) => left.period.localeCompare(right.period))
    .map((point) => ({
      ...point,
      market_value: Number(point.market_value),
      cost_basis: Number(point.cost_basis),
      realized_gain: Number(point.realized_gain),
      unrealized_gain: Number(point.unrealized_gain),
      total_gain: Number(point.total_gain),
    }))
  const latest = data.at(-1)

  return (
    <Panel title="Évolution des actifs" subtitle="Valeur de marché, capital investi et gains réalisés">
      <div className="chart-container asset-performance-chart">
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 12, right: 12, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
              <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
              <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
              <Line dataKey="market_value" name="Valeur de marché" type="monotone" stroke="#615fff" strokeWidth={2.5} dot={false} />
              <Line dataKey="cost_basis" name="Capital investi" type="monotone" stroke="#f97316" strokeWidth={2.2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState icon="trend" text="Ajoutez une première opération pour afficher l'évolution de vos actifs." />
        )}
      </div>
      {latest && (
        <div className="wealth-performance-breakdown">
          <span>
            <small>Performance totale</small>
            <strong className={latest.total_gain >= 0 ? 'positive' : 'negative'}>
              {signedMoney(latest.total_gain, true)}
            </strong>
          </span>
          <span>
            <small>Plus-values réalisées</small>
            <strong className={latest.realized_gain >= 0 ? 'positive' : 'negative'}>
              {signedMoney(latest.realized_gain, true)}
            </strong>
          </span>
          <span>
            <small>Plus-values latentes</small>
            <strong className={latest.unrealized_gain >= 0 ? 'positive' : 'negative'}>
              {signedMoney(latest.unrealized_gain, true)}
            </strong>
          </span>
        </div>
      )}
    </Panel>
  )
}

function HoldingsPanel({
  accounts,
  focusId,
  holdings,
  onChanged,
  selectableAccounts,
}: {
  accounts: Account[]
  focusId?: number
  holdings: Holding[]
  onChanged: () => Promise<void>
  selectableAccounts: Account[]
}) {
  const [editingHolding, setEditingHolding] = useState<Holding | null>(null)
  const [operationsHolding, setOperationsHolding] = useState<Holding | null>(null)
  const [search, setSearch] = useState('')
  const [assetClass, setAssetClass] = useState('all')
  const [accountId, setAccountId] = useState('all')
  const [status, setStatus] = useState<'all' | 'open' | 'closed'>('all')
  const [sort, setSort] = useState<HoldingSort>('default')
  const filterableAccounts = useMemo(() => {
    const holdingAccountIds = new Set(holdings.map((holding) => holding.account_id))
    return accounts.filter((account) =>
      supportsHoldings(account.type)
      && (holdingAccountIds.has(account.id) || accountId === String(account.id)),
    )
  }, [accountId, accounts, holdings])
  const visibleHoldings = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('fr-FR')
    return holdings
      .filter((holding) => {
        const matchesSearch =
          !normalized
          || holding.name.toLocaleLowerCase('fr-FR').includes(normalized)
          || (holding.symbol ?? '').toLocaleLowerCase('fr-FR').includes(normalized)
        const matchesAccount = accountId === 'all' || holding.account_id === Number(accountId)
        const matchesStatus = status === 'all'
          || (status === 'open' && Number(holding.active_profile_quantity ?? holding.quantity) > 0)
          || (status === 'closed' && Number(holding.active_profile_quantity ?? holding.quantity) === 0)
        return matchesSearch
          && matchesAccount
          && matchesStatus
          && (assetClass === 'all' || holding.asset_class === assetClass)
      })
      .sort((left, right) => compareHoldings(left, right, sort))
  }, [accountId, assetClass, holdings, search, sort, status])
  useLinkedEntityFocus('holding', focusId, holdings.length > 0)

  return (
    <>
      {editingHolding && (
        <HoldingModal
          accounts={selectableAccounts}
          holding={editingHolding}
          onClose={() => setEditingHolding(null)}
          onSaved={async () => {
            await onChanged()
            setEditingHolding(null)
          }}
        />
      )}
      {operationsHolding && (
        <HoldingOperationsModal
          accounts={selectableAccounts}
          holding={operationsHolding}
          onClose={() => setOperationsHolding(null)}
        />
      )}
      <Panel title="Patrimoine" subtitle="Votre portefeuille en un coup d'œil">
        <div className="filter-row asset-position-filters">
          <label className="search-field">
            <Icon name="search" />
            <FormInput value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un titre ou un symbole" />
          </label>
          <FormSelect aria-label="Filtrer par type d'actif" value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
            <option value="all">Tous les actifs</option>
            <option value="cash">Liquidités</option>
            <option value="savings">Épargne</option>
            <option value="equity">Actions</option>
            <option value="fund">Fonds</option>
            <option value="bond">Obligations</option>
            <option value="crypto">Crypto</option>
            <option value="real_estate">Immobilier</option>
            <option value="other">Autres</option>
          </FormSelect>
          <FormSelect aria-label="Filtrer par compte" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="all">Tous les comptes</option>
            {filterableAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}{account.archived ? ' (archivé)' : ''}
              </option>
            ))}
          </FormSelect>
          <FormSelect aria-label="Filtrer par statut" value={status} onChange={(event) => setStatus(event.target.value as 'all' | 'open' | 'closed')}>
            <option value="all">Ouvertes et clôturées</option>
            <option value="open">Positions ouvertes</option>
            <option value="closed">Positions clôturées</option>
          </FormSelect>
          <FormSelect
            aria-label="Trier les actifs"
            value={sort}
            onChange={(event) => setSort(event.target.value as HoldingSort)}
          >
            <option value="default">Tri par défaut</option>
            <option value="market-value-desc">Valeur nette : décroissante</option>
            <option value="market-value-asc">Valeur nette : croissante</option>
            <option value="gain-desc">Plus / moins-value (€) : décroissante</option>
            <option value="gain-asc">Plus / moins-value (€) : croissante</option>
            <option value="gain-percent-desc">Plus / moins-value (%) : décroissante</option>
            <option value="gain-percent-asc">Plus / moins-value (%) : croissante</option>
          </FormSelect>
        </div>
        {visibleHoldings.length > 0 ? (
          <div className="holding-list">
            {visibleHoldings.map((holding) => (
              <HoldingRow
                accounts={accounts}
                focused={holding.id === focusId}
                holding={holding}
                key={holding.id}
                onChanged={onChanged}
                onEdit={() => setEditingHolding(holding)}
                onShowOperations={() => setOperationsHolding(holding)}
              />
            ))}
          </div>
        ) : (
          <EmptyState icon="holdings" text={holdings.length === 0 ? 'Ajoutez une première opération pour créer votre position.' : 'Aucun actif ne correspond aux filtres.'} />
        )}
      </Panel>
    </>
  )
}

function HoldingRow({
  accounts,
  focused,
  holding,
  onChanged,
  onEdit,
  onShowOperations,
}: {
  accounts: Account[]
  focused: boolean
  holding: Holding
  onChanged: () => Promise<void>
  onEdit: () => void
  onShowOperations: () => void
}) {
  const account = accounts.find((candidate) => candidate.id === holding.account_id)
  const quantity = holding.active_profile_quantity ?? holding.quantity
  const marketValue = holding.active_profile_market_value ?? holding.market_value
  const totalGain = holding.active_profile_total_gain ?? holding.total_gain
  const realizedGain = holding.active_profile_realized_gain ?? holding.realized_gain
  const unrealizedGain = holding.active_profile_unrealized_gain ?? holding.unrealized_gain
  const shared = (account?.owner_profile_ids?.length ?? 0) > 1
  const remove = useMutation({
    mutationFn: () => apiDelete(`/holdings/${holding.id}`),
    onSuccess: onChanged,
  })
  return (
    <article
      className={focused ? 'linked-entity-target' : undefined}
      id={linkedEntityTargetId('holding', holding.id)}
      tabIndex={focused ? -1 : undefined}
    >
      <span className="asset-symbol">{holding.symbol || initials(holding.name)}</span>
      <span className="holding-copy">
        <strong>{holding.name}</strong>
        <small>
          {formatQuantity(quantity, holding.asset_class)} unité{Number(quantity) === 1 ? '' : 's'} ·{' '}
          {account?.name ?? `Compte ${holding.account_id}`}
        </small>
        {shared && <small>Position totale : {formatQuantity(holding.quantity, holding.asset_class)} unités</small>}
        <button className="holding-operation-count" type="button" onClick={onShowOperations}>
          {holding.operation_count} opération{holding.operation_count === 1 ? '' : 's'}
        </button>
      </span>
      <span className="holding-badges">
        <StatusBadge>{assetLabel(holding.asset_class)}</StatusBadge>
        {Number(quantity) === 0 && <StatusBadge tone="warning">Clôturée</StatusBadge>}
      </span>
      <span className="holding-value">
        <strong>{money(marketValue)}</strong>
        {shared && <small>Valeur totale : {money(holding.market_value)}</small>}
        <small>Prix actuel : {money(holding.current_price)} / unité</small>
        <small className={Number(totalGain) >= 0 ? 'positive' : 'negative'}>
          Total : {signedMoney(totalGain, true)} · {holdingTotalGainPercent(holding).toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
        </small>
        <small className={Number(realizedGain) >= 0 ? 'positive' : 'negative'}>
          Réalisé : {signedMoney(realizedGain, true)} · {holdingRealizedGainPercent(holding).toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
        </small>
        <small className={Number(unrealizedGain) >= 0 ? 'positive' : 'negative'}>
          Latent : {signedMoney(unrealizedGain, true)} · {holdingUnrealizedGainPercent(holding).toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
        </small>
      </span>
      <span className="row-actions">
        <button className="icon-action" type="button" aria-label={`Voir les opérations de ${holding.name}`} onClick={onShowOperations}><Icon name="calendar" /></button>
        <button className="icon-action" type="button" aria-label="Modifier l'actif" onClick={onEdit}><Icon name="edit" /></button>
        <button
          className="icon-action"
          type="button"
          aria-label="Supprimer"
          onClick={() => {
            if (window.confirm('Supprimer cet actif ?')) remove.mutate()
          }}
        >
          <Icon name="trash" />
        </button>
      </span>
      {remove.error && <span className="form-error row-error">{errorMessage(remove.error)}</span>}
    </article>
  )
}

type HoldingOperationContext = {
  holding: Holding
  operation: HoldingOperation
}

function HoldingOperationsPanel({
  accounts,
  holdings,
  onChanged,
  selectableAccounts,
}: {
  accounts: Account[]
  holdings: Holding[]
  onChanged: () => Promise<void>
  selectableAccounts: Account[]
}) {
  const [editing, setEditing] = useState<HoldingOperationContext | null>(null)
  const [search, setSearch] = useState('')
  const [operationType, setOperationType] = useState('all')
  const [accountId, setAccountId] = useState('all')
  const operations = useQuery({
    queryKey: ['holding-operations'],
    queryFn: () => apiGet<HoldingOperation[]>('/holding-operations'),
  })
  const holdingById = useMemo(
    () => new Map(holdings.map((holding) => [holding.id, holding])),
    [holdings],
  )
  const accountById = useMemo(
    () => new Map(accounts.map((account) => [account.id, account])),
    [accounts],
  )
  const operationAccounts = useMemo(() => {
    const accountIds = new Set(holdings.map((holding) => holding.account_id))
    return accounts.filter((account) => accountIds.has(account.id))
  }, [accounts, holdings])
  const filtered = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('fr-FR')
    return (operations.data ?? []).filter((operation) => {
      const holding = holdingById.get(operation.holding_id)
      if (!holding) return false
      const account = accountById.get(holding.account_id)
      const matchesSearch =
        !normalized
        || holding.name.toLocaleLowerCase('fr-FR').includes(normalized)
        || (holding.symbol ?? '').toLocaleLowerCase('fr-FR').includes(normalized)
        || (account?.name ?? '').toLocaleLowerCase('fr-FR').includes(normalized)
      return matchesSearch
        && (operationType === 'all' || operation.operation_type === operationType)
        && (accountId === 'all' || holding.account_id === Number(accountId))
    })
  }, [accountById, accountId, holdingById, operationType, operations.data, search])
  const removeOperation = useMutation({
    mutationFn: ({ holding, operation }: HoldingOperationContext) => apiDelete<Holding>(
      `/holdings/${holding.id}/operations/${operation.id}`,
    ),
    onSuccess: onChanged,
  })

  if (editing) {
    return (
      <HoldingOperationEditModal
        accounts={selectableAccounts}
        holding={editing.holding}
        operation={editing.operation}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          await onChanged()
          setEditing(null)
        }}
      />
    )
  }

  return (
    <Panel title="Opérations" subtitle="Tous les achats et ventes de vos actifs">
      <div className="filter-row asset-operation-filters">
        <label className="search-field">
          <Icon name="search" />
          <FormInput
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Rechercher un actif ou un compte"
          />
        </label>
        <FormSelect value={operationType} onChange={(event) => setOperationType(event.target.value)}>
          <option value="all">Achats et ventes</option>
          <option value="buy">Achats</option>
          <option value="sell">Ventes</option>
        </FormSelect>
        <FormSelect value={accountId} onChange={(event) => setAccountId(event.target.value)}>
          <option value="all">Tous les comptes</option>
          {operationAccounts.map((account) => (
            <option key={account.id} value={account.id}>{account.name}</option>
          ))}
        </FormSelect>
      </div>
      {operations.error && <p className="form-error">{errorMessage(operations.error)}</p>}
      {operations.isPending ? (
        <p className="modal-hint">Chargement des opérations…</p>
      ) : filtered.length > 0 ? (
        <div className="holding-operation-list asset-operation-list">
          {filtered.map((operation) => {
            const holding = holdingById.get(operation.holding_id)
            if (!holding) return null
            const account = accountById.get(holding.account_id)
            const quantity = Math.abs(Number(operation.quantity_delta))
            return (
              <article key={operation.id}>
                <StatusBadge tone={operation.operation_type === 'buy' ? 'positive' : 'warning'}>
                  {operation.operation_type === 'buy' ? 'Achat' : 'Vente'}
                </StatusBadge>
                <span>
                  <strong>
                    {holding.name}{holding.symbol ? ` · ${holding.symbol}` : ''}
                  </strong>
                  <small>
                    {account?.name ?? `Compte ${holding.account_id}`} · {formatDate(operation.occurred_on)}
                    {' · '}{operation.operation_type === 'buy' ? '+' : '−'}
                    {formatQuantity(String(quantity), holding.asset_class)} unité{quantity === 1 ? '' : 's'}
                    {' à '}{money(operation.unit_price)}
                  </small>
                </span>
                <strong className={`operation-cash-flow ${Number(operation.cash_flow) >= 0 ? 'positive' : 'negative'}`}>
                  Flux {signedMoney(operation.cash_flow)}
                </strong>
                <strong className={`operation-gain ${Number(operation.realized_gain ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                  P/MV {operation.realized_gain == null ? '—' : signedMoney(operation.realized_gain, true)}
                </strong>
                <span className="row-actions">
                  <button
                    className="icon-action"
                    type="button"
                    aria-label={`Modifier l’opération ${holding.name} du ${formatDate(operation.occurred_on)}`}
                    onClick={() => setEditing({ holding, operation })}
                  >
                    <Icon name="edit" />
                  </button>
                  <button
                    className="icon-action"
                    type="button"
                    aria-label={`Supprimer l’opération ${holding.name} du ${formatDate(operation.occurred_on)}`}
                    disabled={removeOperation.isPending}
                    onClick={() => {
                      if (window.confirm('Supprimer cette opération ?')) {
                        removeOperation.mutate({ holding, operation })
                      }
                    }}
                  >
                    <Icon name="trash" />
                  </button>
                </span>
              </article>
            )
          })}
        </div>
      ) : (
        <EmptyState
          icon="holdings"
          text={operations.data?.length
            ? 'Aucune opération ne correspond aux filtres.'
            : 'Ajoutez une première opération pour alimenter cet historique.'}
        />
      )}
      {removeOperation.error && <p className="form-error">{errorMessage(removeOperation.error)}</p>}
    </Panel>
  )
}

function HoldingModal({
  accounts,
  holding,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  holding: Holding
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [accountId, setAccountId] = useState(String(holding.account_id))
  const [symbol, setSymbol] = useState(holding.symbol ?? '')
  const [name, setName] = useState(holding.name)
  const [currentPrice, setCurrentPrice] = useState(holding.current_price)
  const mutation = useMutation({
    mutationFn: () => apiPatch<Holding>(`/holdings/${holding.id}`, {
      account_id: Number(accountId),
      symbol: symbol.trim() || null,
      name,
      current_price: currentPrice,
    }),
    onSuccess: onSaved,
  })
  const formId = `holding-edit-${holding.id}`

  return (
    <Modal
      title="Modifier l'actif"
      description="La position et le prix de revient sont calculés à partir des opérations."
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button
            className="primary-button"
            type="submit"
            form={formId}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </>
      )}
    >
      <form className="modal-form holding-modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <div className="holding-modal-grid">
          <Field label="Compte">
            <FormSelect value={accountId} onChange={(event) => setAccountId(event.target.value)} required>
              {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </FormSelect>
          </Field>
          <Field label="Symbole">
            <FormInput value={symbol} onChange={(event) => setSymbol(event.target.value)} maxLength={32} />
          </Field>
          <Field label="Nom">
            <FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
          </Field>
          <Field label="Prix actuel">
            <FormInput type="number" min="0" step="0.01" value={currentPrice} onChange={(event) => setCurrentPrice(event.target.value)} required />
          </Field>
        </div>
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function HoldingOperationModal({
  accounts,
  holdings,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  holdings: Holding[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const initialHolding = holdings[0]
  const [target, setTarget] = useState(initialHolding ? String(initialHolding.id) : 'new')
  const [operationType, setOperationType] = useState<'buy' | 'sell'>('buy')
  const [accountId, setAccountId] = useState(String(initialHolding?.account_id ?? accounts[0]?.id ?? ''))
  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('')
  const [assetClass, setAssetClass] = useState('equity')
  const [quantity, setQuantity] = useState('')
  const [unitPrice, setUnitPrice] = useState('')
  const [occurredOn, setOccurredOn] = useState(monthInputValue(localDateInputValue()))
  const selectedHolding = holdings.find((holding) => holding.id === Number(target))
  const isNew = target === 'new'
  const targetHolding = selectedHolding && !isNew
    ? holdings.find((holding) => (
        holding.account_id === Number(accountId)
        && holding.name === selectedHolding.name
        && holding.symbol === selectedHolding.symbol
        && holding.asset_class === selectedHolding.asset_class
      ))
    : undefined
  const canSell = !isNew && Number(targetHolding?.quantity ?? 0) > 0
  const quantityStep = holdingQuantityStep(isNew ? assetClass : selectedHolding?.asset_class)
  const mutation = useMutation({
    mutationFn: () => apiPost<HoldingOperationResult>('/holding-operations', {
      ...(isNew
        ? {
            new_holding: {
              account_id: Number(accountId),
              name,
              symbol: symbol.trim() || null,
              asset_class: assetClass,
            },
          }
        : { holding_id: Number(target) }),
      ...(!isNew && { target_account_id: Number(accountId) }),
      operation_type: operationType,
      quantity,
      unit_price: unitPrice,
      occurred_on: monthBoundaryDate(occurredOn),
    }),
    onSuccess: onSaved,
  })
  const formId = 'holding-operation-create'

  return (
    <Modal
      title="Ajouter une opération"
      description="La quantité et le prix de revient de l'actif seront recalculés automatiquement."
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button
            className="primary-button"
            type="submit"
            form={formId}
            disabled={mutation.isPending || (isNew && !accountId)}
          >
            {mutation.isPending ? 'Enregistrement…' : 'Ajouter l’opération'}
          </button>
        </>
      )}
    >
      <form className="modal-form holding-operation-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <div className="holding-operation-type" role="group" aria-label="Type d’opération">
          <button
            className={operationType === 'buy' ? 'active' : ''}
            type="button"
            onClick={() => setOperationType('buy')}
          >
            Achat
          </button>
          <button
            className={operationType === 'sell' ? 'active' : ''}
            type="button"
            disabled={!canSell}
            onClick={() => setOperationType('sell')}
          >
            Vente
          </button>
        </div>
        <Field label="Actif">
          <FormSelect value={target} onChange={(event) => {
            const nextTarget = event.target.value
            setTarget(nextTarget)
            if (nextTarget === 'new') {
              setOperationType('buy')
              setAccountId(String(accounts[0]?.id ?? ''))
            } else {
              const nextHolding = holdings.find((holding) => holding.id === Number(nextTarget))
              setAccountId(String(nextHolding?.account_id ?? ''))
            }
          }}>
            {holdings.map((holding) => (
              <option key={holding.id} value={holding.id}>
                {holding.name}{holding.symbol ? ` (${holding.symbol})` : ''} ·{' '}
                {accounts.find((account) => account.id === holding.account_id)?.name ?? `Compte ${holding.account_id}`}
              </option>
            ))}
            <option value="new">Nouvel actif…</option>
          </FormSelect>
        </Field>
        <Field label="Compte">
          <FormSelect value={accountId} onChange={(event) => {
            const nextAccountId = event.target.value
            setAccountId(nextAccountId)
            if (
              operationType === 'sell'
              && !holdings.some((holding) => (
                holding.account_id === Number(nextAccountId)
                && holding.name === selectedHolding?.name
                && holding.symbol === selectedHolding?.symbol
                && holding.asset_class === selectedHolding?.asset_class
                && Number(holding.quantity) > 0
              ))
            ) {
              setOperationType('buy')
            }
          }} required>
            {!accountId && <option value="">Aucun compte compatible</option>}
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </FormSelect>
        </Field>
        {isNew && (
          <div className="holding-modal-grid">
            <Field label="Classe">
              <FormSelect value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
                <option value="equity">Action</option>
                <option value="fund">Fonds</option>
                <option value="bond">Obligations</option>
                <option value="crypto">Crypto</option>
                <option value="savings">Épargne</option>
                <option value="cash">Liquidités</option>
                <option value="real_estate">Immobilier</option>
                <option value="other">Autre</option>
              </FormSelect>
            </Field>
            <Field label="Nom">
              <FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
            </Field>
            <Field label="Symbole">
              <FormInput value={symbol} onChange={(event) => setSymbol(event.target.value)} maxLength={32} />
            </Field>
          </div>
        )}
        <div className="holding-modal-grid">
          <Field label="Mois de l’opération">
            <DatePicker value={occurredOn} onChange={(event) => setOccurredOn(event.target.value)} required />
          </Field>
          <Field label="Quantité">
            <FormInput
              type="number"
              min={quantityStep}
              max={operationType === 'sell' ? targetHolding?.quantity : undefined}
              step={quantityStep}
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              required
            />
          </Field>
          <Field label={operationType === 'buy' ? "Prix d'achat unitaire" : 'Prix de vente unitaire'}>
            <FormInput type="number" min="0.01" step="0.01" value={unitPrice} onChange={(event) => setUnitPrice(event.target.value)} required />
          </Field>
        </div>
        {operationType === 'sell' && targetHolding && (
          <p className="modal-hint">Position disponible : {formatQuantity(targetHolding.quantity, targetHolding.asset_class)} unités sur ce compte.</p>
        )}
        {isNew && accounts.length === 0 && (
          <p className="form-error" role="alert">
            Aucun compte compatible n'est disponible. Créez ou restaurez d'abord un compte d'investissement.
          </p>
        )}
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function HoldingOperationsModal({
  accounts,
  holding,
  onClose,
}: {
  accounts: Account[]
  holding: Holding
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [editingOperation, setEditingOperation] = useState<HoldingOperation | null>(null)
  const [currentHolding, setCurrentHolding] = useState(holding)
  const operations = useQuery({
    queryKey: ['holding-operations', holding.id],
    queryFn: () => apiGet<HoldingOperation[]>(`/holdings/${holding.id}/operations`),
  })
  const refreshHoldingQueries = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['holding-operations', holding.id] }),
      queryClient.invalidateQueries({ queryKey: ['holdings'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
    ])
  }
  const refreshAfterEdit = async (result: HoldingOperationResult) => {
    await refreshHoldingQueries()
    if (result.holding.id !== currentHolding.id) {
      onClose()
      return
    }
    setCurrentHolding(result.holding)
    setEditingOperation(null)
  }
  const removeOperation = useMutation({
    mutationFn: (operation: HoldingOperation) => apiDelete<Holding>(
      `/holdings/${holding.id}/operations/${operation.id}`,
    ),
    onSuccess: async (updatedHolding) => {
      setCurrentHolding(updatedHolding)
      await refreshHoldingQueries()
    },
  })

  if (editingOperation) {
    return (
      <HoldingOperationEditModal
        accounts={accounts}
        holding={currentHolding}
        operation={editingOperation}
        onClose={() => setEditingOperation(null)}
        onSaved={refreshAfterEdit}
      />
    )
  }

  return (
    <Modal
      title={`Opérations · ${currentHolding.name}`}
      description={`${formatQuantity(currentHolding.quantity, currentHolding.asset_class)} unités détenues · total ${signedMoney(currentHolding.total_gain, true)}`}
      onClose={onClose}
      actions={<button className="text-button" type="button" onClick={onClose}>Fermer</button>}
    >
      {operations.error && <p className="form-error">{errorMessage(operations.error)}</p>}
      {operations.isPending ? (
        <p className="modal-hint">Chargement des opérations…</p>
      ) : operations.data?.length ? (
        <div className="holding-operation-list">
          {operations.data.map((operation) => (
            <article key={operation.id}>
              <StatusBadge tone={operation.operation_type === 'buy' ? 'positive' : 'warning'}>
                {operation.operation_type === 'buy' ? 'Achat' : 'Vente'}
              </StatusBadge>
              <span>
                <strong className={Number(operation.quantity_delta) >= 0 ? 'positive' : 'negative'}>
                  {Number(operation.quantity_delta) >= 0 ? '+' : '−'}
                  {formatQuantity(String(Math.abs(Number(operation.quantity_delta))), currentHolding.asset_class)} unité
                  {Math.abs(Number(operation.quantity_delta)) === 1 ? '' : 's'}
                </strong>
                <small>{formatDate(operation.occurred_on)} · {money(operation.unit_price)} / unité</small>
              </span>
              <strong className={Number(operation.cash_flow) >= 0 ? 'positive' : 'negative'}>
                Flux {signedMoney(operation.cash_flow)}
              </strong>
              <strong className={`operation-gain ${Number(operation.realized_gain ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                P/MV {operation.realized_gain == null ? '—' : signedMoney(operation.realized_gain, true)}
              </strong>
              <button
                className="icon-action"
                type="button"
                aria-label={`Modifier l’opération du ${formatDate(operation.occurred_on)}`}
                onClick={() => setEditingOperation(operation)}
              >
                <Icon name="edit" />
              </button>
              <button
                className="icon-action"
                type="button"
                aria-label={`Supprimer l’opération du ${formatDate(operation.occurred_on)}`}
                disabled={removeOperation.isPending}
                onClick={() => {
                  if (window.confirm('Supprimer cette opération ?')) {
                    removeOperation.mutate(operation)
                  }
                }}
              >
                <Icon name="trash" />
              </button>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState icon="holdings" text="Aucune opération enregistrée pour cet actif." />
      )}
      {removeOperation.error && <p className="form-error">{errorMessage(removeOperation.error)}</p>}
    </Modal>
  )
}

function HoldingOperationEditModal({
  accounts,
  holding,
  operation,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  holding: Holding
  operation: HoldingOperation
  onClose: () => void
  onSaved: (result: HoldingOperationResult) => Promise<void>
}) {
  const [accountId, setAccountId] = useState(String(holding.account_id))
  const [operationType, setOperationType] = useState(operation.operation_type)
  const [quantity, setQuantity] = useState(operation.quantity)
  const [unitPrice, setUnitPrice] = useState(operation.unit_price)
  const [occurredOn, setOccurredOn] = useState(monthInputValue(operation.occurred_on))
  const mutation = useMutation({
    mutationFn: () => apiPatch<HoldingOperationResult>(
      `/holdings/${holding.id}/operations/${operation.id}`,
      {
        target_account_id: Number(accountId),
        operation_type: operationType,
        quantity,
        unit_price: unitPrice,
        occurred_on: monthBoundaryDate(occurredOn),
      },
    ),
    onSuccess: onSaved,
  })
  const formId = `holding-operation-edit-${operation.id}`

  return (
    <Modal
      title={`Modifier l’opération · ${holding.name}`}
      description="La position sera recalculée à partir de tout l’historique."
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </>
      )}
    >
      <form className="modal-form holding-operation-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <div className="holding-operation-type" role="group" aria-label="Type d’opération">
          <button
            className={operationType === 'buy' ? 'active' : ''}
            type="button"
            onClick={() => setOperationType('buy')}
          >
            Achat
          </button>
          <button
            className={operationType === 'sell' ? 'active' : ''}
            type="button"
            onClick={() => setOperationType('sell')}
          >
            Vente
          </button>
        </div>
        <Field label="Compte">
          <FormSelect value={accountId} onChange={(event) => setAccountId(event.target.value)} required>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </FormSelect>
        </Field>
        <div className="holding-modal-grid">
          <Field label="Mois de l’opération">
            <DatePicker value={occurredOn} onChange={(event) => setOccurredOn(event.target.value)} required />
          </Field>
          <Field label="Quantité">
            <FormInput
              type="number"
              min={holdingQuantityStep(holding.asset_class)}
              step={holdingQuantityStep(holding.asset_class)}
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              required
            />
          </Field>
          <Field label={operationType === 'buy' ? "Prix d'achat unitaire" : 'Prix de vente unitaire'}>
            <FormInput type="number" min="0.01" step="0.01" value={unitPrice} onChange={(event) => setUnitPrice(event.target.value)} required />
          </Field>
        </div>
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function RealEstatePanel({
  assets,
  debts,
  focusId,
  activeProfile,
  profiles,
}: {
  assets: RealEstateAsset[]
  debts: Debt[]
  focusId?: number
  activeProfile: UserProfile
  profiles: UserProfile[]
}) {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingAsset, setEditingAsset] = useState<RealEstateAsset | null>(null)
  const [search, setSearch] = useState('')
  const [propertyType, setPropertyType] = useState('all')
  const filtered = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('fr-FR')
    return assets.filter((asset) => {
      const matchesSearch =
        !normalized
        || asset.name.toLocaleLowerCase('fr-FR').includes(normalized)
        || (asset.address ?? '').toLocaleLowerCase('fr-FR').includes(normalized)
      return matchesSearch && (propertyType === 'all' || asset.property_type === propertyType)
    })
  }, [assets, propertyType, search])
  const totalOwned = assets.reduce(
    (sum, asset) => sum + Number(asset.active_profile_owned_value ?? asset.owned_value),
    0,
  )
  const totalDebt = assets.reduce(
    (sum, asset) => sum + Number(asset.active_profile_debt_balance ?? asset.debt_balance),
    0,
  )
  const totalEquity = assets.reduce(
    (sum, asset) => sum + Number(asset.active_profile_net_equity ?? asset.net_equity),
    0,
  )
  useLinkedEntityFocus('real-estate', focusId, assets.length > 0)
  const availableDebts = debts.filter(
    (debt) => !assets.some(
      (asset) => asset.debt_ids.includes(debt.id) && asset.id !== editingAsset?.id,
    ),
  )
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['real-estate'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
    ])
  }
  const closeModal = () => {
    setShowCreateModal(false)
    setEditingAsset(null)
  }

  return (
    <>
      <section className="section-intro">
        <p>Suivez la valeur de vos biens, votre quote-part et les emprunts associés.</p>
        <button
          className="primary-button"
          type="button"
          onClick={() => {
            setEditingAsset(null)
            setShowCreateModal(true)
          }}
        >
          <Icon name="plus" /> Ajouter un bien
        </button>
      </section>
      {(showCreateModal || editingAsset) && (
        <RealEstateModal
          asset={editingAsset ?? undefined}
          debts={availableDebts}
          activeProfile={activeProfile}
          profiles={profiles}
          key={editingAsset?.id ?? 'new-property'}
          onClose={closeModal}
          onSaved={async () => {
            await refresh()
            closeModal()
          }}
        />
      )}
      <div className="real-estate-summary">
        <span>
          <small>Valeur détenue</small>
          <strong>{money(totalOwned)}</strong>
        </span>
        <span>
          <small>Emprunts associés</small>
          <strong className={totalDebt > 0 ? 'negative' : ''}>{money(totalDebt)}</strong>
        </span>
        <span>
          <small>Valeur nette immobilière</small>
          <strong className={totalEquity >= 0 ? 'positive' : 'negative'}>{money(totalEquity)}</strong>
        </span>
      </div>
      <Panel
        title="Biens immobiliers"
        subtitle={`${assets.length} bien${assets.length === 1 ? '' : 's'} enregistré${assets.length === 1 ? '' : 's'}`}
      >
        <div className="filter-row">
          <label className="search-field">
            <Icon name="search" />
            <FormInput
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Rechercher un bien ou une adresse"
            />
          </label>
          <FormSelect value={propertyType} onChange={(event) => setPropertyType(event.target.value)}>
            <option value="all">Tous les biens</option>
            <option value="primary_residence">Résidence principale</option>
            <option value="secondary_residence">Résidence secondaire</option>
            <option value="rental">Locatif</option>
            <option value="commercial">Local commercial</option>
            <option value="land">Terrain</option>
            <option value="other">Autre</option>
          </FormSelect>
        </div>
        {filtered.length > 0 ? (
          <div className="real-estate-list">
            {filtered.map((asset) => (
              <RealEstateRow
                asset={asset}
                activeProfile={activeProfile}
                debts={asset.debts}
                focused={focusId === asset.id}
                key={asset.id}
                onChanged={refresh}
                onEdit={() => {
                  setShowCreateModal(false)
                  setEditingAsset(asset)
                }}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon="home"
            text={assets.length === 0 ? 'Ajoutez votre premier bien immobilier.' : 'Aucun bien ne correspond aux filtres.'}
          />
        )}
      </Panel>
    </>
  )
}

function RealEstateRow({
  asset,
  activeProfile,
  debts,
  focused,
  onChanged,
  onEdit,
}: {
  asset: RealEstateAsset
  activeProfile: UserProfile
  debts: RealEstateAsset['debts']
  focused: boolean
  onChanged: () => Promise<void>
  onEdit: () => void
}) {
  const [showAttachments, setShowAttachments] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const iconUpload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return apiUpload(`/real-estate/${asset.id}/icon`, form)
    },
    onSuccess: onChanged,
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/real-estate/${asset.id}`),
    onSuccess: onChanged,
  })
  const profilePurchasePrice = asset.active_profile_purchase_price ?? asset.owned_purchase_price
  const profileGain = asset.active_profile_gain ?? asset.gain
  const gainPercent = Number(profilePurchasePrice) > 0
    ? (Number(profileGain) / Number(profilePurchasePrice)) * 100
    : 0

  return (
    <article
      className={focused ? 'linked-entity-target' : undefined}
      id={linkedEntityTargetId('real-estate', asset.id)}
      tabIndex={focused ? -1 : undefined}
    >
      <span
        className="property-mark"
        style={{ cursor: 'pointer', display: 'inline-block', width: 60, height: 60, overflow: 'hidden', borderRadius: 8 }}
        onClick={() => fileInputRef.current?.click()}
        aria-label={asset.icon_path ? 'Modifier l\'icône' : 'Ajouter une icône'}
        role="button"
      >
        {asset.icon_path ? (
          <img
            src={`/api/real-estate/${asset.id}/icon/download?t=${asset.icon_path || '0'}`}
            alt={asset.name}
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
        ) : (
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%', background: 'var(--surface)', borderRadius: 8 }}>
            <Icon name="home" />
          </span>
        )}
      </span>
      <span className="property-copy">
        <strong>{asset.name}</strong>
        <small>{propertyTypeLabel(asset.property_type)}{asset.address ? ` · ${asset.address}` : ''}</small>
        <small>
          Quote-part {maskNumericValue(`${Number(asset.ownership_share).toLocaleString('fr-FR', { maximumFractionDigits: 2 })}%`)}
          {asset.acquired_on ? ` · Acquis le ${formatDate(asset.acquired_on)}` : ''}
        </small>
      </span>
      <span className="property-value">
        <small>{asset.current_value === null ? 'Valeur détenue au prix d’achat' : 'Valeur détenue'}</small>
        <strong>{money(asset.active_profile_owned_value ?? asset.owned_value)}</strong>
        {asset.owners && asset.owners.length > 1 && (
          <small>Valeur totale : {money(asset.total_owned_value ?? asset.owned_value)} · partagé avec {asset.owners.filter((owner) => owner.id !== activeProfile.id).map((owner) => owner.name).join(', ')}</small>
        )}
        {asset.current_value === null ? (
          <small>Valeur actuelle non renseignée</small>
        ) : (
          <small className={Number(profileGain) >= 0 ? 'positive' : 'negative'}>
            {signedMoney(profileGain, true)} · {gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
          </small>
        )}
      </span>
      <span className="property-equity">
        <small>Valeur nette</small>
        <strong className={Number(asset.active_profile_net_equity ?? asset.net_equity) >= 0 ? 'positive' : 'negative'}>{money(asset.active_profile_net_equity ?? asset.net_equity)}</strong>
        {asset.owners && asset.owners.length > 1 && <small>Total : {money(asset.total_net_equity ?? asset.net_equity)}</small>}
        {debts.length > 0 && (
          <span className="linked-entities property-links">
            {debts.map((debt) => (
              <Fragment key={debt.id}>
                <LinkedEntityLink
                  href={routeHash({ name: 'wealth', tab: 'debts', focusId: debt.id })}
                  icon="debt"
                  label={`Dette : ${debt.name}`}
                />
                {debt.recurring_series_repayment_id && (
                  <LinkedEntityLink
                    href={routeHash({
                      name: 'budget',
                      tab: 'recurring',
                      focusId: debt.recurring_series_repayment_id,
                    })}
                    icon="recurring"
                    label={`Récurrence remboursement : ${debt.recurring_series_name_repayment || 'Remboursement'}`}
                  />
                )}
                {debt.recurring_series_insurance_id && (
                  <LinkedEntityLink
                    href={routeHash({
                      name: 'budget',
                      tab: 'recurring',
                      focusId: debt.recurring_series_insurance_id,
                    })}
                    icon="recurring"
                    label={`Récurrence assurance : ${debt.recurring_series_name_insurance || 'Assurance'}`}
                  />
                )}
              </Fragment>
            ))}
          </span>
        )}
      </span>
      <span className="row-actions">
        <button
          className="icon-action attachment-button"
          type="button"
          aria-label={`Pièces jointes${asset.attachment_count > 0 ? ` (${asset.attachment_count})` : ''}`}
          aria-expanded={showAttachments}
          onClick={() => setShowAttachments((current) => !current)}
        >
          <Icon name="attachment" />
          {asset.attachment_count > 0 && (
            <span className="attachment-count-badge">{asset.attachment_count}</span>
          )}
        </button>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: 'none' }}
          accept="image/*"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) {
              iconUpload.mutate(file)
              e.target.value = ''
            }
          }}
        />
        <button className="icon-action" type="button" aria-label="Modifier" onClick={onEdit}><Icon name="edit" /></button>
        <button
          className="icon-action"
          type="button"
          aria-label="Supprimer"
          onClick={() => {
            if (window.confirm('Supprimer ce bien immobilier ?')) remove.mutate()
          }}
        >
          <Icon name="trash" />
        </button>
      </span>
      {remove.error && <span className="form-error row-error">{errorMessage(remove.error)}</span>}
      {showAttachments && (
        <div className="entity-attachment-panel">
          <AttachmentManager
            owner={{ kind: 'real-estate', assetId: asset.id }}
            readOnly={false}
          />
        </div>
      )}
    </article>
  )
}

function RealEstateModal({
  asset,
  debts,
  activeProfile,
  profiles,
  onClose,
  onSaved,
}: {
  asset?: RealEstateAsset
  debts: Debt[]
  activeProfile: UserProfile
  profiles: UserProfile[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [name, setName] = useState(asset?.name ?? '')
  const [propertyType, setPropertyType] = useState(asset?.property_type ?? 'primary_residence')
  const [address, setAddress] = useState(asset?.address ?? '')
  const [acquiredOn, setAcquiredOn] = useState(monthInputValue(asset?.acquired_on))
  const [purchasePrice, setPurchasePrice] = useState(asset?.purchase_price ?? '')
  const [currentValue, setCurrentValue] = useState(asset?.current_value ?? '')
  const [ownershipShare, setOwnershipShare] = useState(asset?.ownership_share ?? '100')
  const [debtIds, setDebtIds] = useState<number[]>(asset?.debt_ids ?? [])
  const [ownerProfileIds, setOwnerProfileIds] = useState(asset?.owners?.map((owner) => owner.id) ?? [activeProfile.id])
  const [attachment, setAttachment] = useState<File | null>(null)
  const createdAssetId = useRef<number | null>(null)
  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name,
        property_type: propertyType,
        address,
        acquired_on: acquiredOn ? monthBoundaryDate(acquiredOn) : null,
        purchase_price: purchasePrice,
        current_value: currentValue || null,
        ownership_share: ownershipShare,
        debt_ids: debtIds,
        owner_profile_ids: ownerProfileIds,
      }
      const existingId = asset?.id ?? createdAssetId.current
      const savedAsset = await (existingId
        ? apiPatch<RealEstateAsset>(`/real-estate/${existingId}`, payload)
        : apiPost<RealEstateAsset>('/real-estate', payload))
      createdAssetId.current = savedAsset.id
      if (!asset && attachment) {
        await uploadOwnerAttachment({ kind: 'real-estate', assetId: savedAsset.id }, attachment)
      }
      return savedAsset
    },
    onSuccess: onSaved,
  })
  const formId = asset ? `real-estate-edit-${asset.id}` : 'real-estate-create'

  return (
    <Modal
      title={asset ? 'Modifier le bien' : 'Nouveau bien immobilier'}
      description="Les montants et l’adresse restent exclusivement dans votre base locale."
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : asset ? 'Enregistrer' : 'Ajouter'}
          </button>
        </>
      )}
    >
      <form className="modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom">
          <FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
        </Field>
        <Field label="Type de bien">
          <FormSelect value={propertyType} onChange={(event) => setPropertyType(event.target.value)}>
            <option value="primary_residence">Résidence principale</option>
            <option value="secondary_residence">Résidence secondaire</option>
            <option value="rental">Locatif</option>
            <option value="commercial">Local commercial</option>
            <option value="land">Terrain</option>
            <option value="other">Autre</option>
          </FormSelect>
        </Field>
        <Field label="Adresse">
          <FormInput value={address} onChange={(event) => setAddress(event.target.value)} maxLength={200} placeholder="Facultatif" />
        </Field>
        <Field label="Mois d’acquisition">
          <DatePicker value={acquiredOn} onChange={(event) => setAcquiredOn(event.target.value)} />
        </Field>
        <Field label="Prix d’achat">
          <FormInput type="number" min="0" step="0.01" value={purchasePrice} onChange={(event) => setPurchasePrice(event.target.value)} required />
        </Field>
        <Field label="Valeur actuelle (facultatif)" hint="Sans estimation, le prix d’achat est retenu dans les totaux.">
          <FormInput type="number" min="0" step="0.01" value={currentValue} onChange={(event) => setCurrentValue(event.target.value)} />
        </Field>
        <Field label="Quote-part (%)">
          <FormInput type="number" min="0.01" max="100" step="0.01" value={ownershipShare} onChange={(event) => setOwnershipShare(event.target.value)} required />
        </Field>
        <ProfileOwnership activeProfileId={activeProfile.id} onChange={setOwnerProfileIds} profiles={profiles} selectedIds={ownerProfileIds} />
        <div className="field real-estate-debt-field">
          <span>Emprunts associés</span>
          {debts.length > 0 ? (
            <div className="real-estate-debt-options">
              {debts.map((debt) => (
                <label className="real-estate-debt-option" key={debt.id}>
                  <FormInput
                    type="checkbox"
                    checked={debtIds.includes(debt.id)}
                    onChange={() => setDebtIds((current) => (
                      current.includes(debt.id)
                        ? current.filter((debtId) => debtId !== debt.id)
                        : [...current, debt.id]
                    ))}
                  />
                  <span>
                    <strong>{debt.name}</strong>
                    <small>{money(debt.balance)} restant</small>
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <small className="modal-hint">Aucun emprunt disponible.</small>
          )}
        </div>
        <div className="modal-attachment-field">
          {asset ? (
            <AttachmentManager
              owner={{ kind: 'real-estate', assetId: asset.id }}
              readOnly={false}
            />
          ) : (
            <AttachmentPicker
              file={attachment}
              onChange={setAttachment}
              disabled={mutation.isPending}
            />
          )}
        </div>
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function DebtsPanel({
  accounts,
  debts,
  assets,
  focusId,
  recurringSeries,
  activeProfile,
  profiles,
}: {
  accounts: Account[]
  debts: Debt[]
  assets: RealEstateAsset[]
  focusId?: number
  recurringSeries: RecurringSeries[]
  activeProfile: UserProfile
  profiles: UserProfile[]
}) {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [debtToEdit, setDebtToEdit] = useState<Debt | null>(null)
  const total = debts.reduce(
    (sum, debt) => sum + Number(debt.active_profile_balance ?? debt.balance),
    0,
  )
  const monthly = debts.reduce(
    (sum, debt) => sum + Number(
      debt.active_profile_minimum_payment ?? debt.minimum_payment ?? 0,
    ),
    0,
  )
  useLinkedEntityFocus('debt', focusId, debts.length > 0)
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['debts'] }),
      queryClient.invalidateQueries({ queryKey: ['real-estate'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-series'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-forecast'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-cashflow'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-spending'] }),
      queryClient.invalidateQueries({ queryKey: ['overview'] }),
      queryClient.invalidateQueries({ queryKey: ['monthly-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
    ])
  }

  return (
    <>
      <section className="section-intro">
        <p>Visualisez le capital restant et les mensualités de vos dettes.</p>
        <button className="primary-button" type="button" onClick={() => setShowCreateModal(true)}>
          <Icon name="plus" /> Ajouter une dette
        </button>
      </section>
      {showCreateModal && (
        <DebtModal
          accounts={accounts}
          activeProfile={activeProfile}
          profiles={profiles}
          recurringSeries={recurringSeries}
          onClose={() => setShowCreateModal(false)}
          onSaved={async () => {
            await refresh()
            setShowCreateModal(false)
          }}
        />
      )}
      {debtToEdit && (
        <DebtModal
          accounts={accounts}
          activeProfile={activeProfile}
          profiles={profiles}
          debt={debtToEdit}
          key={debtToEdit.id}
          recurringSeries={recurringSeries}
          onClose={() => setDebtToEdit(null)}
          onSaved={async () => {
            await refresh()
            setDebtToEdit(null)
          }}
        />
      )}
      <Panel title="Dettes" subtitle={`Total restant : ${money(total)} · Mensualités : ${money(monthly)} / mois`}>
        {debts.length > 0 ? (
          <div className="debt-list">
            {debts.map((debt) => (
              <DebtRow
                asset={assets.find((asset) => asset.debt_ids.includes(debt.id))}
                debt={debt}
                activeProfile={activeProfile}
                focused={focusId === debt.id}
                key={debt.id}
                onEdit={() => setDebtToEdit(debt)}
                onSaved={refresh}
                readOnly={accounts.find((account) => account.id === debt.account_id)?.archived ?? false}
              />
            ))}
          </div>
        ) : (
          <EmptyState icon="debt" text="Aucune dette enregistrée." />
        )}
      </Panel>
    </>
  )
}

function DebtRow({
  asset,
  debt,
  activeProfile,
  focused,
  onEdit,
  onSaved,
  readOnly,
}: {
  asset?: RealEstateAsset
  debt: Debt
  activeProfile: UserProfile
  focused: boolean
  onEdit: () => void
  onSaved: () => Promise<void>
  readOnly: boolean
}) {
  const [showAttachments, setShowAttachments] = useState(false)
  const remove = useMutation({
    mutationFn: () => apiDelete(`/debts/${debt.id}`),
    onSuccess: onSaved,
  })
  return (
    <article
      className={focused ? 'linked-entity-target' : undefined}
      id={linkedEntityTargetId('debt', debt.id)}
      tabIndex={focused ? -1 : undefined}
    >
      <div className="debt-head">
        <span>
          <i style={{ background: debt.color ?? '#ff6b70' }} />
          <strong>{debt.name}</strong>
          <StatusBadge>{debtTypeLabel(debt.debt_type)}</StatusBadge>
          {debt.archived && <StatusBadge tone="warning">Archivée</StatusBadge>}
        </span>
        <strong className="negative">{money(debt.active_profile_balance ?? debt.balance)}</strong>
      </div>
      <ProgressBar value={Number(debt.progress) * 100} color={debt.color ?? '#ff6b70'} />
      <div className="debt-meta">
        <span>{maskNumericValue(`${(Number(debt.progress) * 100).toLocaleString('fr-FR', { maximumFractionDigits: 0 })}%`)} remboursé</span>
        {debt.minimum_payment !== null && (
          <span>{money(debt.active_profile_minimum_payment ?? debt.minimum_payment)} / mois</span>
        )}
        {debt.interest_rate !== null && <span>Taux {maskNumericValue(`${Number(debt.interest_rate).toLocaleString('fr-FR')}%`)}</span>}
        {debt.due_date && <span>Fin prévue {formatDate(debt.due_date)}</span>}
        {debt.owners && debt.owners.length > 1 && (
          <span>Capital total : {money(debt.total_balance ?? debt.balance)} · partagé avec {debt.owners.filter((owner) => owner.id !== activeProfile.id).map((owner) => owner.name).join(', ')}</span>
        )}
        {(asset || (debt.recurring_series_repayment_id || debt.recurring_series_insurance_id)) && (
          <span className="linked-entities debt-links">
            {asset && (
              <LinkedEntityLink
                href={routeHash({ name: 'wealth', tab: 'real-estate', focusId: asset.id })}
                icon="home"
                label={`Bien : ${asset.name}`}
              />
            )}
            {debt.recurring_series_repayment_id && (
              <LinkedEntityLink
                href={routeHash({
                  name: 'budget',
                  tab: 'recurring',
                  focusId: debt.recurring_series_repayment_id,
                })}
                icon="recurring"
                label={`Récurrence remboursement : ${debt.recurring_series_name_repayment || 'Remboursement'}`}
              />
            )}
            {debt.recurring_series_insurance_id && (
              <LinkedEntityLink
                href={routeHash({
                  name: 'budget',
                  tab: 'recurring',
                  focusId: debt.recurring_series_insurance_id,
                })}
                icon="recurring"
                label={`Récurrence assurance : ${debt.recurring_series_name_insurance || 'Assurance'}`}
              />
            )}
          </span>
        )}
        {(!readOnly || debt.attachment_count > 0) && (
          <button
            className="icon-action attachment-button"
            type="button"
            aria-label={`Pièces jointes${debt.attachment_count > 0 ? ` (${debt.attachment_count})` : ''}`}
            aria-expanded={showAttachments}
            onClick={() => setShowAttachments((current) => !current)}
          >
            <Icon name="attachment" />
            {debt.attachment_count > 0 && (
              <span className="attachment-count-badge">{debt.attachment_count}</span>
            )}
          </button>
        )}
        <button className="icon-action" type="button" aria-label="Modifier" onClick={onEdit}>
          <Icon name="edit" />
        </button>
        <button
          className="icon-action"
          type="button"
          aria-label="Supprimer"
          onClick={() => {
            if (window.confirm('Supprimer cette dette ?')) remove.mutate()
          }}
        >
          <Icon name="trash" />
        </button>
      </div>
      {remove.error && <p className="form-error">{errorMessage(remove.error)}</p>}
      {showAttachments && (
        <div className="entity-attachment-panel">
          <AttachmentManager
            owner={{ kind: 'debt', debtId: debt.id }}
            readOnly={readOnly}
          />
        </div>
      )}
    </article>
  )
}

function DebtModal({
  accounts,
  debt,
  recurringSeries,
  activeProfile,
  profiles,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  debt?: Debt
  recurringSeries: RecurringSeries[]
  activeProfile: UserProfile
  profiles: UserProfile[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const selectableAccounts = accounts.filter((account) => !account.archived || account.id === debt?.account_id)
  const [name, setName] = useState(debt?.name ?? '')
  const [debtType, setDebtType] = useState<Debt['debt_type']>(debt?.debt_type ?? 'other')
  const [initialAmount, setInitialAmount] = useState(debt?.principal ?? '')
  const [remainingAmount, setRemainingAmount] = useState(debt?.balance ?? '')
  const [interestRate, setInterestRate] = useState(debt?.interest_rate ?? '')
  const [accountId, setAccountId] = useState(String(debt?.account_id ?? ''))
  const [recurringSeriesRepaymentId, setRecurringSeriesRepaymentId] = useState(String(debt?.recurring_series_repayment_id ?? ''))
  const [recurringSeriesInsuranceId, setRecurringSeriesInsuranceId] = useState(String(debt?.recurring_series_insurance_id ?? ''))
  const [dueDate, setDueDate] = useState(monthInputValue(debt?.due_date))
  const [color, setColor] = useState(debt?.color ?? '#ff6b70')
  const [archived, setArchived] = useState(debt?.archived ?? false)
  const [attachment, setAttachment] = useState<File | null>(null)
  const [ownerProfileIds, setOwnerProfileIds] = useState(debt?.owners?.map((owner) => owner.id) ?? [activeProfile.id])
  const createdDebtId = useRef<number | null>(null)
  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name,
        debt_type: debtType,
        principal: initialAmount,
        balance: remainingAmount,
                interest_rate: interestRate || null,
        account_id: accountId ? Number(accountId) : null,
        recurring_series_repayment_id: recurringSeriesRepaymentId ? Number(recurringSeriesRepaymentId) : null,
        recurring_series_insurance_id: recurringSeriesInsuranceId ? Number(recurringSeriesInsuranceId) : null,
        due_date: dueDate ? monthBoundaryDate(dueDate, 'end') : null,
        color,
        owner_profile_ids: ownerProfileIds,
        ...(debt ? { archived } : {}),
      }
      const existingId = debt?.id ?? createdDebtId.current
      const savedDebt = await (existingId
        ? apiPatch<Debt>(`/debts/${existingId}`, payload)
        : apiPost<Debt>('/debts', payload))
      createdDebtId.current = savedDebt.id
      if (!debt && attachment) {
        await uploadOwnerAttachment({ kind: 'debt', debtId: savedDebt.id }, attachment)
      }
      return savedDebt
    },
    onSuccess: onSaved,
  })
  const formId = debt ? `debt-edit-${debt.id}` : 'debt-create'

  return (
    <Modal
      title={debt ? 'Modifier la dette' : 'Nouvelle dette'}
      description={debt
        ? 'Tous les paramètres de la dette peuvent être mis à jour.'
        : 'Ajoutez une dette à votre patrimoine.'}
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : debt ? 'Enregistrer' : 'Créer la dette'}
          </button>
        </>
      )}
    >
      <form className="modal-form debt-modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom">
          <FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
        </Field>
        <Field label="Type">
          <FormSelect value={debtType} onChange={(event) => setDebtType(event.target.value as Debt['debt_type'])}>
            <option value="consumer_credit">Crédit à la consommation</option>
            <option value="mortgage">Prêt immobilier</option>
            <option value="other">Autre dette</option>
          </FormSelect>
        </Field>
        <Field label="Capital initial">
          <FormInput type="number" min="0" step="0.01" value={initialAmount} onChange={(event) => setInitialAmount(event.target.value)} required />
        </Field>
        <Field label="Capital restant">
          <FormInput type="number" min="0" step="0.01" value={remainingAmount} onChange={(event) => setRemainingAmount(event.target.value)} required />
        </Field>
        <Field label="Taux annuel (%)">
          <FormInput type="number" min="0" step="0.01" value={interestRate} onChange={(event) => setInterestRate(event.target.value)} />
        </Field>
        <Field label="Compte associé">
          <FormSelect
            value={accountId}
            onChange={(event) => setAccountId(event.target.value)}
            required={!recurringSeriesRepaymentId && !recurringSeriesInsuranceId}
          >
            <option value="">Aucun compte</option>
            {selectableAccounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Série récurrente remboursement">
          <FormSelect value={recurringSeriesRepaymentId} onChange={(event) => setRecurringSeriesRepaymentId(event.target.value)}>
            <option value="">Aucune série</option>
            {recurringSeries.map((series) => {
              if (series.recurring_type === 'loan_payment') {
                return <option key={series.id} value={series.id}>{series.label}</option>
              }
              return null
            })}
          </FormSelect>
        </Field>
        <Field label="Série récurrente assurance">
          <FormSelect value={recurringSeriesInsuranceId} onChange={(event) => setRecurringSeriesInsuranceId(event.target.value)}>
            <option value="">Aucune série</option>
            {recurringSeries.map((series) => {
              if (series.recurring_type === 'credit_insurance') {
                return <option key={series.id} value={series.id}>{series.label}</option>
              }
              return null
            })}
          </FormSelect>
        </Field>
        {(!recurringSeriesRepaymentId && !recurringSeriesInsuranceId) && (
          <p className="modal-hint debt-modal-wide">
            Une série mensuelle de remboursement sera créée automatiquement dans le budget.
          </p>
        )}
        <Field label="Mois de fin prévu">
          <DatePicker value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
        </Field>
        <Field label="Couleur">
          <FormInput type="color" value={color} onChange={(event) => setColor(event.target.value)} />
        </Field>
        <div className="debt-modal-wide">
          <ProfileOwnership activeProfileId={activeProfile.id} onChange={setOwnerProfileIds} profiles={profiles} selectedIds={ownerProfileIds} />
        </div>
        {debt && (
          <label className="toggle-row debt-modal-wide">
            <span>
              <strong>Dette archivée</strong>
              <small>Elle reste consultable mais est identifiée comme terminée ou inactive.</small>
            </span>
            <FormInput type="checkbox" checked={archived} onChange={(event) => setArchived(event.target.checked)} />
            <span className="toggle-visual" aria-hidden="true"><Icon name="check" /></span>
          </label>
        )}
        <div className="modal-attachment-field debt-modal-wide">
          {debt ? (
            <AttachmentManager
              owner={{ kind: 'debt', debtId: debt.id }}
              readOnly={selectableAccounts.find((account) => account.id === debt.account_id)?.archived ?? false}
            />
          ) : (
            <AttachmentPicker
              file={attachment}
              onChange={setAttachment}
              disabled={mutation.isPending}
            />
          )}
        </div>
        {mutation.error && <p className="form-error debt-modal-wide">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function assetLabel(assetClass: Holding['asset_class']): string {
  const labels: Record<string, string> = {
    cash: 'Liquidités',
    savings: 'Épargne',
    equity: 'Action',
    fund: 'Fonds',
    bond: 'Obligations',
    crypto: 'Crypto',
    real_estate: 'Immobilier',
    other: 'Autre',
  }
  return labels[assetClass] ?? assetClass
}

function debtTypeLabel(debtType: Debt['debt_type']): string {
  return {
    consumer_credit: 'Crédit conso',
    mortgage: 'Prêt immobilier',
    other: 'Autre dette',
  }[debtType]
}

function propertyTypeLabel(propertyType: RealEstateAsset['property_type']): string {
  const labels: Record<string, string> = {
    primary_residence: 'Résidence principale',
    secondary_residence: 'Résidence secondaire',
    rental: 'Bien locatif',
    commercial: 'Local commercial',
    land: 'Terrain',
    other: 'Autre',
  }
  return labels[propertyType] ?? propertyType
}

function gainPercent(gain: string | number, costBasis: string | number): number {
  return Number(costBasis) > 0
    ? (Number(gain) / Number(costBasis)) * 100
    : 0
}

function holdingTotalGainPercent(holding: Holding): number {
  return gainPercent(
    holding.active_profile_total_gain ?? holding.total_gain,
    holding.active_profile_total_cost_basis ?? holding.total_cost_basis,
  )
}

function holdingRealizedGainPercent(holding: Holding): number {
  return gainPercent(
    holding.active_profile_realized_gain ?? holding.realized_gain,
    holding.active_profile_realized_cost_basis ?? holding.realized_cost_basis,
  )
}

function holdingUnrealizedGainPercent(holding: Holding): number {
  return gainPercent(
    holding.active_profile_unrealized_gain ?? holding.unrealized_gain,
    holding.active_profile_unrealized_cost_basis ?? holding.unrealized_cost_basis,
  )
}

function compareHoldings(left: Holding, right: Holding, sort: HoldingSort): number {
  if (sort === 'market-value-desc') return Number(right.active_profile_market_value ?? right.market_value) - Number(left.active_profile_market_value ?? left.market_value)
  if (sort === 'market-value-asc') return Number(left.active_profile_market_value ?? left.market_value) - Number(right.active_profile_market_value ?? right.market_value)
  if (sort === 'gain-desc') return Number(right.active_profile_total_gain ?? right.total_gain) - Number(left.active_profile_total_gain ?? left.total_gain)
  if (sort === 'gain-asc') return Number(left.active_profile_total_gain ?? left.total_gain) - Number(right.active_profile_total_gain ?? right.total_gain)
  if (sort === 'gain-percent-desc') return holdingTotalGainPercent(right) - holdingTotalGainPercent(left)
  if (sort === 'gain-percent-asc') return holdingTotalGainPercent(left) - holdingTotalGainPercent(right)
  return 0
}

function holdingQuantityStep(assetClass?: Holding['asset_class']): string {
  return assetClass === 'crypto' ? '0.0000000001' : '0.000001'
}

function formatQuantity(value: string, assetClass?: Holding['asset_class']): string {
  return maskNumericValue(Number(value).toLocaleString('fr-FR', {
    maximumFractionDigits: assetClass === 'crypto' ? 10 : 6,
  }))
}
