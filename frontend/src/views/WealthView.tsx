import { FormEvent, useLayoutEffect, useMemo, useRef, useState } from 'react'
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

import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import type {
  Account,
  Debt,
  Holding,
  InvestmentContribution,
  NetWorthPoint,
  NetWorthSummary,
  PerformancePoint,
  PortfolioAllocation,
  PortfolioSummary,
  RealEstateAsset,
  RecurringSeries,
} from '../api/types'
import { supportsHoldings } from '../accountCapabilities'
import { isRouteBeta } from '../featureValidation'
import { routeHash, type Route, type WealthTab } from '../routing'
import { ScheduleImportModal } from '../ScheduleImportModal'
import {
  BetaBadge,
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
  money,
  signedMoney,
  useLinkedEntityFocus,
} from '../ui'

const allocationColors = ['#615fff', '#16c79a', '#1da9e8', '#f97316', '#8758f6', '#ec4899', '#f7b500']

export function WealthView({
  tab,
  focusId,
  accounts,
  navigate,
}: {
  tab: WealthTab
  focusId?: number
  accounts: Account[]
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
  const allocation = useQuery({
    queryKey: ['portfolio-allocation'],
    queryFn: () => apiGet<PortfolioAllocation[]>('/portfolio/allocation'),
  })
  const contributions = useQuery({
    queryKey: ['investment-contributions'],
    queryFn: () => apiGet<InvestmentContribution[]>('/contributions'),
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
    allocation.error,
    contributions.error,
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
          {isRouteBeta({ name: 'wealth', tab: 'overview' }) && <BetaBadge />}
        </button>
        <button className={tab === 'holdings' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'holdings' })}>
          <Icon name="holdings" /> Actifs
          {isRouteBeta({ name: 'wealth', tab: 'holdings' }) && <BetaBadge />}
        </button>
        <button className={tab === 'real-estate' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'real-estate' })}>
          <Icon name="home" /> Immobilier
          {isRouteBeta({ name: 'wealth', tab: 'real-estate' }) && <BetaBadge />}
        </button>
        <button className={tab === 'debts' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'debts' })}>
          <Icon name="debt" /> Dettes
          {isRouteBeta({ name: 'wealth', tab: 'debts' }) && <BetaBadge />}
        </button>
      </nav>

      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}

      {tab === 'overview' && (
        <WealthOverview
          accounts={accounts}
          allocation={allocation.data ?? []}
          contributions={contributions.data ?? []}
          holdings={holdings.data ?? []}
          netWorth={netWorth.data}
          netWorthHistory={netWorthHistory.data ?? []}
          performance={performance.data ?? []}
          summary={summary.data}
        />
      )}
      {tab === 'holdings' && (
        <HoldingsPanel accounts={accounts} holdings={holdings.data ?? []} />
      )}
      {tab === 'real-estate' && (
        <RealEstatePanel
          assets={realEstate.data ?? []}
          debts={debts.data ?? []}
          focusId={focusId}
        />
      )}
      {tab === 'debts' && (
        <DebtsPanel
          accounts={accounts}
          debts={debts.data ?? []}
          assets={realEstate.data ?? []}
          focusId={focusId}
          recurringSeries={recurringSeries.data ?? []}
        />
      )}
    </div>
  )
}

function WealthOverview({
  accounts,
  allocation,
  contributions,
  holdings,
  netWorth,
  netWorthHistory,
  performance,
  summary,
}: {
  accounts: Account[]
  allocation: PortfolioAllocation[]
  contributions: InvestmentContribution[]
  holdings: Holding[]
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
  const recentContributions = [...contributions]
    .sort((left, right) => right.occurred_on.localeCompare(left.occurred_on))
    .slice(0, 5)
  const assets = Number(netWorth?.cash ?? 0)
    + Number(netWorth?.investments ?? 0)
    + Number(netWorth?.real_estate ?? 0)
  const gainPercent = Number(summary?.cost_basis ?? 0) > 0
    ? (Number(summary?.gain ?? 0) / Number(summary?.cost_basis ?? 0)) * 100
    : 0
  const netWorthChartData = netWorthHistory.map((point) => ({
    ...point,
    net_worth: Number(point.net_worth),
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
        </div>
        <div className="wealth-performance">
          <span className={Number(summary?.gain ?? 0) >= 0 ? 'positive' : 'negative'}>
            <Icon name="trend" />
            {signedMoney(summary?.gain ?? 0)}
          </span>
          <small>{gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}% de performance</small>
        </div>
      </section>

      <section className="dashboard-grid">
        <Panel title="Évolution du patrimoine net" subtitle="Historique des actifs, dettes et patrimoine">
          <div className="chart-container tall-chart">
            {netWorthChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={netWorthChartData} margin={{ top: 12, right: 10, left: -8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="net-worth-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} padding={{ top: 12 }} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
                  <Area dataKey="net_worth" name="Patrimoine net" type="monotone" stroke="#16c79a" strokeWidth={2.5} fill="url(#net-worth-fill)" />
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
                      <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
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
                  <strong>{slice.percentage.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%</strong>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </section>

      <section className="dashboard-grid lower-grid">
        <Panel title="Plus-value / moins-value" subtitle="Valeur du portefeuille et capital investi">
          <div className="chart-container">
            {performance.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={performance} margin={{ top: 12, right: 12, left: -8, bottom: 0 }}>
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
        </Panel>

        <Panel
          title="Contributions récentes"
          subtitle={`Total versé : ${money(summary?.contributions_total)}`}
          action={<ContributionForm accounts={accounts} holdings={holdings} />}
        >
          {recentContributions.length > 0 ? (
            <div className="data-list">
              {recentContributions.map((contribution) => (
                <div key={contribution.id}>
                  <span className="data-list-icon"><Icon name="plus" /></span>
                  <span>
                    <strong>Versement</strong>
                    <small>{formatDate(contribution.occurred_on)}</small>
                  </span>
                  <strong>{money(contribution.amount)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon="plus" text="Aucune contribution enregistrée." />
          )}
        </Panel>
      </section>
    </>
  )
}

function ContributionForm({ accounts, holdings }: { accounts: Account[]; holdings: Holding[] }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [accountId, setAccountId] = useState('')
  const [holdingId, setHoldingId] = useState('')
  const [amount, setAmount] = useState('')
  const [bookedAt, setBookedAt] = useState(localDateInputValue)
  const availableHoldings = accountId
    ? holdings.filter((holding) => holding.account_id === Number(accountId))
    : holdings
  const mutation = useMutation({
    mutationFn: () => apiPost<InvestmentContribution>('/contributions', {
      holding_id: Number(holdingId || availableHoldings[0]?.id),
      occurred_on: bookedAt,
      amount,
      note: null,
    }),
    onSuccess: async () => {
      setOpen(false)
      setAmount('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['investment-contributions'] }),
        queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-performance'] }),
        queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
      ])
    },
  })
  if (!open) {
    return (
      <button className="secondary-button small-button" type="button" onClick={() => setOpen(true)}>
        <Icon name="plus" />Versement
      </button>
    )
  }
  return (
    <form className="compact-inline-form contribution-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <FormSelect aria-label="Compte" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
        <option value="">Tous les comptes</option>
        {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
      </FormSelect>
      <FormSelect aria-label="Actif" value={holdingId} onChange={(event) => setHoldingId(event.target.value)} required>
        <option value="">Choisir un actif</option>
        {availableHoldings.map((holding) => <option key={holding.id} value={holding.id}>{holding.name}</option>)}
      </FormSelect>
      <FormInput aria-label="Date" type="date" value={bookedAt} onChange={(event) => setBookedAt(event.target.value)} />
      <FormInput aria-label="Montant" type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
      <button className="primary-button icon-button" type="submit" aria-label="Enregistrer" disabled={availableHoldings.length === 0}><Icon name="check" /></button>
      <button className="text-button icon-button" type="button" aria-label="Annuler" onClick={() => setOpen(false)}><Icon name="close" /></button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function HoldingsPanel({ accounts, holdings }: { accounts: Account[]; holdings: Holding[] }) {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingHolding, setEditingHolding] = useState<Holding | null>(null)
  const [search, setSearch] = useState('')
  const [assetClass, setAssetClass] = useState('all')
  const selectableAccounts = useMemo(
    () => accounts.filter((account) => !account.archived && supportsHoldings(account.type)),
    [accounts],
  )
  const filtered = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('fr-FR')
    return holdings.filter((holding) => {
      const matchesSearch =
        !normalized
        || holding.name.toLocaleLowerCase('fr-FR').includes(normalized)
        || (holding.symbol ?? '').toLocaleLowerCase('fr-FR').includes(normalized)
      return matchesSearch && (assetClass === 'all' || holding.asset_class === assetClass)
    })
  }, [assetClass, holdings, search])
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['holdings'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
    ])
  }

  return (
    <>
      <section className="section-intro">
        <p>Valorisez vos positions sans synchronisation bancaire externe.</p>
        <button className="primary-button" type="button" onClick={() => setShowCreateModal(true)}>
          <Icon name="plus" /> Ajouter un actif
        </button>
      </section>
      {showCreateModal && (
        <HoldingModal
          accounts={selectableAccounts}
          onClose={() => setShowCreateModal(false)}
          onSaved={async () => {
            await refresh()
            setShowCreateModal(false)
          }}
        />
      )}
      {editingHolding && (
        <HoldingModal
          accounts={selectableAccounts}
          holding={editingHolding}
          onClose={() => setEditingHolding(null)}
          onSaved={async () => {
            await refresh()
            setEditingHolding(null)
          }}
        />
      )}
      <Panel title="Patrimoine" subtitle="Votre portefeuille en un coup d'œil">
        <div className="filter-row">
          <label className="search-field">
            <Icon name="search" />
            <FormInput value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un titre ou un symbole" />
          </label>
          <FormSelect value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
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
        </div>
        {filtered.length > 0 ? (
          <div className="holding-list">
            {filtered.map((holding) => (
              <HoldingRow
                accounts={accounts}
                holding={holding}
                key={holding.id}
                onChanged={refresh}
                onEdit={() => setEditingHolding(holding)}
              />
            ))}
          </div>
        ) : (
          <EmptyState icon="holdings" text={holdings.length === 0 ? 'Ajoutez votre première position.' : 'Aucun actif ne correspond aux filtres.'} />
        )}
      </Panel>
    </>
  )
}

function HoldingRow({
  accounts,
  holding,
  onChanged,
  onEdit,
}: {
  accounts: Account[]
  holding: Holding
  onChanged: () => Promise<void>
  onEdit: () => void
}) {
  const remove = useMutation({
    mutationFn: () => apiDelete(`/holdings/${holding.id}`),
    onSuccess: onChanged,
  })
  return (
    <article>
      <span className="asset-symbol">{holding.symbol || initials(holding.name)}</span>
      <span className="holding-copy">
        <strong>{holding.name}</strong>
        <small>
          {formatQuantity(holding.quantity)} unité{Number(holding.quantity) === 1 ? '' : 's'} ·{' '}
          {accounts.find((account) => account.id === holding.account_id)?.name ?? `Compte ${holding.account_id}`}
        </small>
      </span>
      <StatusBadge>{assetLabel(holding.asset_class)}</StatusBadge>
      <span className="holding-value">
        <strong>{money(holding.market_value)}</strong>
        <small className={Number(holding.gain) >= 0 ? 'positive' : 'negative'}>
          {signedMoney(holding.gain)} · {holdingGainPercent(holding).toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
        </small>
      </span>
      <span className="row-actions">
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

function HoldingModal({
  accounts,
  holding,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  holding?: Holding
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const initialAccountId = accounts.some((account) => account.id === holding?.account_id)
    ? String(holding?.account_id)
    : String(accounts[0]?.id ?? '')
  const [accountId, setAccountId] = useState(initialAccountId)
  const [symbol, setSymbol] = useState(holding?.symbol ?? '')
  const [name, setName] = useState(holding?.name ?? '')
  const [assetClass, setAssetClass] = useState(holding?.asset_class ?? 'equity')
  const [quantity, setQuantity] = useState(holding?.quantity ?? '')
  const [averageCost, setAverageCost] = useState(holding?.average_price ?? '')
  const [currentPrice, setCurrentPrice] = useState(holding?.current_price ?? '')
  const selectedAccountId = accountId || initialAccountId
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        account_id: Number(selectedAccountId),
        symbol: symbol.trim() || null,
        name,
        asset_class: assetClass,
        quantity,
        average_price: averageCost,
        current_price: currentPrice,
      }
      return holding
        ? apiPatch<Holding>(`/holdings/${holding.id}`, payload)
        : apiPost<Holding>('/holdings', payload)
    },
    onSuccess: onSaved,
  })
  const formId = holding ? `holding-edit-${holding.id}` : 'holding-create'

  return (
    <Modal
      title={holding ? "Modifier l'actif" : 'Nouvel actif'}
      description="Les valorisations restent enregistrées dans votre base locale."
      onClose={onClose}
      actions={(
        <>
          <button
            className="primary-button"
            type="submit"
            form={formId}
            disabled={mutation.isPending || !selectedAccountId}
          >
            {mutation.isPending ? 'Enregistrement…' : holding ? 'Enregistrer' : 'Ajouter'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form holding-modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <div className="holding-modal-grid">
          <Field label="Compte">
            <FormSelect value={selectedAccountId} onChange={(event) => setAccountId(event.target.value)} required>
              {!selectedAccountId && <option value="">Aucun compte compatible</option>}
              {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </FormSelect>
          </Field>
          <Field label="Symbole">
            <FormInput value={symbol} onChange={(event) => setSymbol(event.target.value)} maxLength={32} />
          </Field>
          <Field label="Nom">
            <FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
          </Field>
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
          <Field label="Quantité">
            <FormInput type="number" min="0" step="0.000001" value={quantity} onChange={(event) => setQuantity(event.target.value)} required />
          </Field>
          <Field label="Prix de revient">
            <FormInput type="number" min="0" step="0.01" value={averageCost} onChange={(event) => setAverageCost(event.target.value)} required />
          </Field>
          <Field label="Prix actuel">
            <FormInput type="number" min="0" step="0.01" value={currentPrice} onChange={(event) => setCurrentPrice(event.target.value)} required />
          </Field>
        </div>
        <p className="modal-hint">
          Seuls les comptes d'investissement actifs (PEA, PEG, PER/PERCOL, compte-titres,
          assurance-vie et wallet crypto) sont proposés.
        </p>
        {accounts.length === 0 && (
          <p className="form-error" role="alert">
            Aucun compte compatible n'est disponible. Créez ou restaurez d'abord un compte d'investissement.
          </p>
        )}
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function RealEstatePanel({
  assets,
  debts,
  focusId,
}: {
  assets: RealEstateAsset[]
  debts: Debt[]
  focusId?: number
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
  const totalOwned = assets.reduce((sum, asset) => sum + Number(asset.owned_value), 0)
  const totalDebt = assets.reduce((sum, asset) => sum + Number(asset.debt_balance), 0)
  const totalEquity = totalOwned - totalDebt
  useLinkedEntityFocus('real-estate', focusId, assets.length > 0)
  const availableDebts = debts.filter(
    (debt) => !assets.some((asset) => asset.debt_id === debt.id && asset.id !== editingAsset?.id),
  )
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['real-estate'] }),
      queryClient.invalidateQueries({ queryKey: ['wealth-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
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
                debt={debts.find((debt) => debt.id === asset.debt_id)}
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
  debt,
  focused,
  onChanged,
  onEdit,
}: {
  asset: RealEstateAsset
  debt?: Debt
  focused: boolean
  onChanged: () => Promise<void>
  onEdit: () => void
}) {
  const remove = useMutation({
    mutationFn: () => apiDelete(`/real-estate/${asset.id}`),
    onSuccess: onChanged,
  })
  const gainPercent = Number(asset.owned_purchase_price) > 0
    ? (Number(asset.gain) / Number(asset.owned_purchase_price)) * 100
    : 0

  return (
    <article
      className={focused ? 'linked-entity-target' : undefined}
      id={linkedEntityTargetId('real-estate', asset.id)}
      tabIndex={focused ? -1 : undefined}
    >
      <span className="property-mark"><Icon name="home" /></span>
      <span className="property-copy">
        <strong>{asset.name}</strong>
        <small>{propertyTypeLabel(asset.property_type)}{asset.address ? ` · ${asset.address}` : ''}</small>
        <small>
          Quote-part {Number(asset.ownership_share).toLocaleString('fr-FR', { maximumFractionDigits: 2 })}%
          {asset.acquired_on ? ` · Acquis le ${formatDate(asset.acquired_on)}` : ''}
        </small>
      </span>
      <span className="property-value">
        <small>{asset.current_value === null ? 'Valeur détenue au prix d’achat' : 'Valeur détenue'}</small>
        <strong>{money(asset.owned_value)}</strong>
        {asset.current_value === null ? (
          <small>Valeur actuelle non renseignée</small>
        ) : (
          <small className={Number(asset.gain) >= 0 ? 'positive' : 'negative'}>
            {signedMoney(asset.gain)} · {gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
          </small>
        )}
      </span>
      <span className="property-equity">
        <small>Valeur nette</small>
        <strong className={Number(asset.net_equity) >= 0 ? 'positive' : 'negative'}>{money(asset.net_equity)}</strong>
        {debt && (
          <span className="linked-entities property-links">
            <LinkedEntityLink
              href={routeHash({ name: 'wealth', tab: 'debts', focusId: debt.id })}
              icon="debt"
              label={`Dette : ${debt.name}`}
            />
            {debt.recurring_series_id && debt.recurring_series_name && (
              <LinkedEntityLink
                href={routeHash({
                  name: 'budget',
                  tab: 'recurring',
                  focusId: debt.recurring_series_id,
                })}
                icon="recurring"
                label={`Récurrence : ${debt.recurring_series_name}`}
              />
            )}
          </span>
        )}
      </span>
      <span className="row-actions">
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
    </article>
  )
}

function RealEstateModal({
  asset,
  debts,
  onClose,
  onSaved,
}: {
  asset?: RealEstateAsset
  debts: Debt[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [name, setName] = useState(asset?.name ?? '')
  const [propertyType, setPropertyType] = useState(asset?.property_type ?? 'primary_residence')
  const [address, setAddress] = useState(asset?.address ?? '')
  const [acquiredOn, setAcquiredOn] = useState(asset?.acquired_on ?? '')
  const [purchasePrice, setPurchasePrice] = useState(asset?.purchase_price ?? '')
  const [currentValue, setCurrentValue] = useState(asset?.current_value ?? '')
  const [ownershipShare, setOwnershipShare] = useState(asset?.ownership_share ?? '100')
  const [debtId, setDebtId] = useState(asset?.debt_id ? String(asset.debt_id) : '')
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        name,
        property_type: propertyType,
        address,
        acquired_on: acquiredOn || null,
        purchase_price: purchasePrice,
        current_value: currentValue || null,
        ownership_share: ownershipShare,
        debt_id: debtId ? Number(debtId) : null,
      }
      return asset
        ? apiPatch<RealEstateAsset>(`/real-estate/${asset.id}`, payload)
        : apiPost<RealEstateAsset>('/real-estate', payload)
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
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : asset ? 'Enregistrer' : 'Ajouter'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
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
        <Field label="Date d’acquisition">
          <FormInput type="date" value={acquiredOn} onChange={(event) => setAcquiredOn(event.target.value)} />
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
        <Field label="Emprunt associé">
          <FormSelect value={debtId} onChange={(event) => setDebtId(event.target.value)}>
            <option value="">Aucun emprunt</option>
            {debts.map((debt) => (
              <option key={debt.id} value={debt.id}>{debt.name} · {money(debt.balance)}</option>
            ))}
          </FormSelect>
        </Field>
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
}: {
  accounts: Account[]
  debts: Debt[]
  assets: RealEstateAsset[]
  focusId?: number
  recurringSeries: RecurringSeries[]
}) {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [debtToEdit, setDebtToEdit] = useState<Debt | null>(null)
  const [debtForSchedule, setDebtForSchedule] = useState<Debt | null>(null)
  const total = debts.reduce((sum, debt) => sum + Number(debt.balance), 0)
  const monthly = debts.reduce((sum, debt) => sum + Number(debt.minimum_payment ?? 0), 0)
  useLinkedEntityFocus('debt', focusId, debts.length > 0)
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['debts'] }),
      queryClient.invalidateQueries({ queryKey: ['real-estate'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth'] }),
      queryClient.invalidateQueries({ queryKey: ['net-worth-history'] }),
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
      {debtForSchedule && (
        <ScheduleImportModal
          title={`Échéancier · ${debtForSchedule.name}`}
          description="Collez deux colonnes TSV : la date, puis le capital restant dû."
          endpoint={`/debts/${debtForSchedule.id}/schedule/import`}
          amountLabel="capital restant dû"
          ariaLabel={`Échéancier TSV de ${debtForSchedule.name}`}
          placeholder={'15/10/2026\t176 840,20 €\n15/11/2026\t175 675,10 €'}
          onClose={() => setDebtForSchedule(null)}
          onSaved={async () => {
            await refresh()
            setDebtForSchedule(null)
          }}
        />
      )}
      <Panel title="Dettes" subtitle={`Total restant : ${money(total)} · Mensualités : ${money(monthly)} / mois`}>
        {debts.length > 0 ? (
          <div className="debt-list">
            {debts.map((debt) => (
              <DebtRow
                asset={assets.find((asset) => asset.debt_id === debt.id)}
                debt={debt}
                focused={focusId === debt.id}
                key={debt.id}
                onEdit={() => setDebtToEdit(debt)}
                onImportSchedule={() => setDebtForSchedule(debt)}
                onSaved={refresh}
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
  focused,
  onEdit,
  onImportSchedule,
  onSaved,
}: {
  asset?: RealEstateAsset
  debt: Debt
  focused: boolean
  onEdit: () => void
  onImportSchedule: () => void
  onSaved: () => Promise<void>
}) {
  const remove = useMutation({
    mutationFn: () => apiDelete(`/debts/${debt.id}`),
    onSuccess: onSaved,
  })
  const canImportSchedule = debt.debt_type === 'consumer_credit' || debt.debt_type === 'mortgage'
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
        <strong className="negative">{money(debt.balance)}</strong>
      </div>
      <ProgressBar value={Number(debt.progress) * 100} color={debt.color ?? '#ff6b70'} />
      <div className="debt-meta">
        <span>{(Number(debt.progress) * 100).toLocaleString('fr-FR', { maximumFractionDigits: 0 })}% remboursé</span>
        {debt.minimum_payment !== null && <span>{money(debt.minimum_payment)} / mois</span>}
        {debt.interest_rate !== null && <span>Taux {Number(debt.interest_rate).toLocaleString('fr-FR')}%</span>}
        {debt.due_date && <span>Fin prévue {formatDate(debt.due_date)}</span>}
        {debt.schedule_count > 0 && (
          <span>{debt.schedule_count} échéance{debt.schedule_count === 1 ? '' : 's'}</span>
        )}
        {debt.next_schedule_date && debt.next_schedule_balance !== null && (
          <span>
            Projection au {formatDate(debt.next_schedule_date)} : {money(debt.next_schedule_balance)}
          </span>
        )}
        {(asset || (debt.recurring_series_id && debt.recurring_series_name)) && (
          <span className="linked-entities debt-links">
            {asset && (
              <LinkedEntityLink
                href={routeHash({ name: 'wealth', tab: 'real-estate', focusId: asset.id })}
                icon="home"
                label={`Bien : ${asset.name}`}
              />
            )}
            {debt.recurring_series_id && debt.recurring_series_name && (
              <LinkedEntityLink
                href={routeHash({
                  name: 'budget',
                  tab: 'recurring',
                  focusId: debt.recurring_series_id,
                })}
                icon="recurring"
                label={`Récurrence : ${debt.recurring_series_name}`}
              />
            )}
          </span>
        )}
        {canImportSchedule && (
          <button className="secondary-button small-button" type="button" onClick={onImportSchedule}>
            <Icon name="database" /> Échéancier
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
    </article>
  )
}

function DebtModal({
  accounts,
  debt,
  recurringSeries,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  debt?: Debt
  recurringSeries: RecurringSeries[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const selectableAccounts = accounts.filter((account) => !account.archived || account.id === debt?.account_id)
  const [name, setName] = useState(debt?.name ?? '')
  const [debtType, setDebtType] = useState<Debt['debt_type']>(debt?.debt_type ?? 'other')
  const [initialAmount, setInitialAmount] = useState(debt?.principal ?? '')
  const [remainingAmount, setRemainingAmount] = useState(debt?.balance ?? '')
  const [monthlyPayment, setMonthlyPayment] = useState(debt?.minimum_payment ?? '')
  const [interestRate, setInterestRate] = useState(debt?.interest_rate ?? '')
  const [accountId, setAccountId] = useState(String(debt?.account_id ?? ''))
  const [recurringSeriesId, setRecurringSeriesId] = useState(String(debt?.recurring_series_id ?? ''))
  const [dueDate, setDueDate] = useState(debt?.due_date ?? '')
  const [color, setColor] = useState(debt?.color ?? '#ff6b70')
  const [archived, setArchived] = useState(debt?.archived ?? false)
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        name,
        debt_type: debtType,
        principal: initialAmount,
        balance: remainingAmount,
        minimum_payment: monthlyPayment || null,
        interest_rate: interestRate || null,
        account_id: accountId ? Number(accountId) : null,
        recurring_series_id: recurringSeriesId ? Number(recurringSeriesId) : null,
        due_date: dueDate || null,
        color,
        ...(debt ? { archived } : {}),
      }
      return debt
        ? apiPatch<Debt>(`/debts/${debt.id}`, payload)
        : apiPost<Debt>('/debts', payload)
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
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            {mutation.isPending ? 'Enregistrement…' : debt ? 'Enregistrer' : 'Créer la dette'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
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
        <Field label="Mensualité">
          <FormInput type="number" min="0" step="0.01" value={monthlyPayment} onChange={(event) => setMonthlyPayment(event.target.value)} />
        </Field>
        <Field label="Taux annuel (%)">
          <FormInput type="number" min="0" step="0.01" value={interestRate} onChange={(event) => setInterestRate(event.target.value)} />
        </Field>
        <Field label="Compte associé">
          <FormSelect value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="">Aucun compte</option>
            {selectableAccounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Série récurrente">
          <FormSelect value={recurringSeriesId} onChange={(event) => setRecurringSeriesId(event.target.value)}>
            <option value="">Aucune série</option>
            {recurringSeries.map((series) => (
              <option key={series.id} value={series.id}>{series.label}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Fin prévue">
          <FormInput type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
        </Field>
        <Field label="Couleur">
          <FormInput type="color" value={color} onChange={(event) => setColor(event.target.value)} />
        </Field>
        {(debtType === 'consumer_credit' || debtType === 'mortgage') && (
          <p className="modal-hint debt-modal-wide">
            Une fois la dette enregistrée, l’action « Échéancier » permet d’importer les
            capitaux restants dus au format TSV.
          </p>
        )}
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

function holdingGainPercent(holding: Holding): number {
  return Number(holding.cost_basis) > 0
    ? (Number(holding.gain) / Number(holding.cost_basis)) * 100
    : 0
}

function formatQuantity(value: string): string {
  return Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 6 })
}
