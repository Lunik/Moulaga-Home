import { FormEvent, useMemo, useState } from 'react'
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
} from '../api/types'
import type { Route, WealthTab } from '../routing'
import {
  EmptyState,
  Field,
  Icon,
  Panel,
  ProgressBar,
  StatusBadge,
  chartTooltipStyle,
  compactMoney,
  errorMessage,
  formatDate,
  initials,
  localDateInputValue,
  money,
  signedMoney,
} from '../ui'

const allocationColors = ['#615fff', '#16c79a', '#1da9e8', '#f97316', '#8758f6', '#ec4899', '#f7b500']

export function WealthView({
  tab,
  accounts,
  navigate,
}: {
  tab: WealthTab
  accounts: Account[]
  navigate: (route: Route) => void
}) {
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
    performance.error,
    allocation.error,
    contributions.error,
  ].filter(Boolean)

  return (
    <div className="view-stack">
      <nav className="module-tabs" aria-label="Patrimoine">
        <button className={tab === 'overview' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'overview' })}>
          <Icon name="wealth" /> Vue d'ensemble
        </button>
        <button className={tab === 'holdings' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'holdings' })}>
          <Icon name="holdings" /> Actifs
        </button>
        <button className={tab === 'debts' ? 'active' : ''} type="button" onClick={() => navigate({ name: 'wealth', tab: 'debts' })}>
          <Icon name="debt" /> Dettes
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
      {tab === 'debts' && <DebtsPanel debts={debts.data ?? []} />}
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
  const assets = Number(netWorth?.cash ?? 0) + Number(netWorth?.investments ?? 0)
  const gainPercent = Number(summary?.cost_basis ?? 0) > 0
    ? (Number(summary?.gain ?? 0) / Number(summary?.cost_basis ?? 0)) * 100
    : 0

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
            {netWorthHistory.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={netWorthHistory} margin={{ top: 12, right: 10, left: -8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="net-worth-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
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
      await queryClient.invalidateQueries({ queryKey: ['investment-contributions'] })
      await queryClient.invalidateQueries({ queryKey: ['wealth-summary'] })
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
      <select aria-label="Compte" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
        <option value="">Tous les comptes</option>
        {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
      </select>
      <select aria-label="Actif" value={holdingId} onChange={(event) => setHoldingId(event.target.value)} required>
        <option value="">Choisir un actif</option>
        {availableHoldings.map((holding) => <option key={holding.id} value={holding.id}>{holding.name}</option>)}
      </select>
      <input aria-label="Date" type="date" value={bookedAt} onChange={(event) => setBookedAt(event.target.value)} />
      <input aria-label="Montant" type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
      <button className="primary-button icon-button" type="submit" aria-label="Enregistrer" disabled={availableHoldings.length === 0}><Icon name="check" /></button>
      <button className="text-button icon-button" type="button" aria-label="Annuler" onClick={() => setOpen(false)}><Icon name="close" /></button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function HoldingsPanel({ accounts, holdings }: { accounts: Account[]; holdings: Holding[] }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [search, setSearch] = useState('')
  const [assetClass, setAssetClass] = useState('all')
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

  return (
    <>
      <section className="section-intro">
        <p>Valorisez vos positions sans synchronisation bancaire externe.</p>
        <button className="primary-button" type="button" onClick={() => setShowForm((current) => !current)}>
          <Icon name="plus" /> Ajouter un actif
        </button>
      </section>
      {showForm && (
        <HoldingForm
          accounts={accounts}
          onCancel={() => setShowForm(false)}
          onSaved={async () => {
            await queryClient.invalidateQueries({ queryKey: ['holdings'] })
            await queryClient.invalidateQueries({ queryKey: ['wealth-summary'] })
            setShowForm(false)
          }}
        />
      )}
      <Panel title="Patrimoine" subtitle="Votre portefeuille en un coup d'œil">
        <div className="filter-row">
          <label className="search-field">
            <Icon name="search" />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un titre ou un symbole" />
          </label>
          <select value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
            <option value="all">Tous les actifs</option>
            <option value="cash">Liquidités</option>
            <option value="savings">Épargne</option>
            <option value="equity">Actions</option>
            <option value="fund">Fonds</option>
            <option value="crypto">Crypto</option>
            <option value="real_estate">Immobilier</option>
            <option value="other">Autres</option>
          </select>
        </div>
        {filtered.length > 0 ? (
          <div className="holding-list">
            {filtered.map((holding) => (
              <HoldingRow accounts={accounts} holding={holding} key={holding.id} />
            ))}
          </div>
        ) : (
          <EmptyState icon="holdings" text={holdings.length === 0 ? 'Ajoutez votre première position.' : 'Aucun actif ne correspond aux filtres.'} />
        )}
      </Panel>
    </>
  )
}

function HoldingRow({ accounts, holding }: { accounts: Account[]; holding: Holding }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [price, setPrice] = useState(holding.current_price)
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['holdings'] })
    await queryClient.invalidateQueries({ queryKey: ['wealth-summary'] })
    await queryClient.invalidateQueries({ queryKey: ['net-worth'] })
  }
  const update = useMutation({
    mutationFn: () => apiPatch<Holding>(`/holdings/${holding.id}`, { current_price: price }),
    onSuccess: async () => {
      setEditing(false)
      await refresh()
    },
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/holdings/${holding.id}`),
    onSuccess: refresh,
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
      {editing ? (
        <form className="holding-price-editor" onSubmit={(event) => {
          event.preventDefault()
          update.mutate()
        }}>
          <input aria-label="Prix actuel" type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} />
          <button className="icon-action positive" type="submit" aria-label="Enregistrer"><Icon name="check" /></button>
          <button className="icon-action" type="button" aria-label="Annuler" onClick={() => setEditing(false)}><Icon name="close" /></button>
        </form>
      ) : (
        <span className="holding-value">
          <strong>{money(holding.market_value)}</strong>
          <small className={Number(holding.gain) >= 0 ? 'positive' : 'negative'}>
            {signedMoney(holding.gain)} · {holdingGainPercent(holding).toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%
          </small>
        </span>
      )}
      <span className="row-actions">
        <button className="icon-action" type="button" aria-label="Actualiser le prix" onClick={() => setEditing(true)}><Icon name="edit" /></button>
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
      {(update.error || remove.error) && <span className="form-error row-error">{errorMessage(update.error ?? remove.error)}</span>}
    </article>
  )
}

function HoldingForm({
  accounts,
  onCancel,
  onSaved,
}: {
  accounts: Account[]
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const [accountId, setAccountId] = useState('')
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [assetClass, setAssetClass] = useState('equity')
  const [quantity, setQuantity] = useState('')
  const [averageCost, setAverageCost] = useState('')
  const [currentPrice, setCurrentPrice] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Holding>('/holdings', {
      account_id: Number(accountId || accounts[0]?.id),
      symbol,
      name,
      asset_class: assetClass,
      quantity,
      average_price: averageCost,
      current_price: currentPrice,
    }),
    onSuccess: onSaved,
  })

  return (
    <Panel title="Nouvel actif" subtitle="Les valorisations restent enregistrées dans votre base locale.">
      <form className="feature-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Compte">
          <select value={accountId} onChange={(event) => setAccountId(event.target.value)} required>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </select>
        </Field>
        <Field label="Symbole">
          <input value={symbol} onChange={(event) => setSymbol(event.target.value)} maxLength={20} required />
        </Field>
        <Field label="Nom">
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
        </Field>
        <Field label="Classe">
          <select value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
            <option value="equity">Action</option>
            <option value="fund">Fonds</option>
            <option value="crypto">Crypto</option>
            <option value="savings">Épargne</option>
            <option value="cash">Liquidités</option>
            <option value="real_estate">Immobilier</option>
            <option value="other">Autre</option>
          </select>
        </Field>
        <Field label="Quantité">
          <input type="number" min="0" step="0.000001" value={quantity} onChange={(event) => setQuantity(event.target.value)} required />
        </Field>
        <Field label="Prix de revient">
          <input type="number" min="0" step="0.01" value={averageCost} onChange={(event) => setAverageCost(event.target.value)} required />
        </Field>
        <Field label="Prix actuel">
          <input type="number" min="0" step="0.01" value={currentPrice} onChange={(event) => setCurrentPrice(event.target.value)} required />
        </Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending || accounts.length === 0}>
            {mutation.isPending ? 'Ajout…' : 'Ajouter'}
          </button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function DebtsPanel({ debts }: { debts: Debt[] }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const total = debts.reduce((sum, debt) => sum + Number(debt.balance), 0)
  const monthly = debts.reduce((sum, debt) => sum + Number(debt.minimum_payment ?? 0), 0)

  return (
    <>
      <section className="section-intro">
        <p>Visualisez le capital restant et les mensualités de vos dettes.</p>
        <button className="primary-button" type="button" onClick={() => setShowForm((current) => !current)}>
          <Icon name="plus" /> Ajouter une dette
        </button>
      </section>
      {showForm && (
        <DebtForm
          onCancel={() => setShowForm(false)}
          onSaved={async () => {
            await queryClient.invalidateQueries({ queryKey: ['debts'] })
            await queryClient.invalidateQueries({ queryKey: ['net-worth'] })
            setShowForm(false)
          }}
        />
      )}
      <Panel title="Dettes" subtitle={`Total restant : ${money(total)} · Mensualités : ${money(monthly)} / mois`}>
        {debts.length > 0 ? (
          <div className="debt-list">
            {debts.map((debt) => (
              <DebtRow debt={debt} key={debt.id} />
            ))}
          </div>
        ) : (
          <EmptyState icon="debt" text="Aucune dette enregistrée." />
        )}
      </Panel>
    </>
  )
}

function DebtRow({ debt }: { debt: Debt }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [remaining, setRemaining] = useState(debt.balance)
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['debts'] })
    await queryClient.invalidateQueries({ queryKey: ['net-worth'] })
  }
  const update = useMutation({
    mutationFn: () => apiPatch<Debt>(`/debts/${debt.id}`, { balance: remaining }),
    onSuccess: async () => {
      setEditing(false)
      await refresh()
    },
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/debts/${debt.id}`),
    onSuccess: refresh,
  })
  return (
    <article>
      <div className="debt-head">
        <span><i style={{ background: debt.color ?? '#ff6b70' }} /> <strong>{debt.name}</strong></span>
        {editing ? (
          <form className="debt-editor" onSubmit={(event) => {
            event.preventDefault()
            update.mutate()
          }}>
            <input aria-label="Capital restant" type="number" min="0" step="0.01" value={remaining} onChange={(event) => setRemaining(event.target.value)} />
            <button className="icon-action positive" type="submit"><Icon name="check" /></button>
            <button className="icon-action" type="button" onClick={() => setEditing(false)}><Icon name="close" /></button>
          </form>
        ) : (
          <strong className="negative">{money(debt.balance)}</strong>
        )}
      </div>
      <ProgressBar value={Number(debt.progress) * 100} color={debt.color ?? '#ff6b70'} />
      <div className="debt-meta">
        <span>{(Number(debt.progress) * 100).toLocaleString('fr-FR', { maximumFractionDigits: 0 })}% remboursé</span>
        <span>{money(debt.minimum_payment)} / mois</span>
        {debt.due_date && <span>Fin prévue {formatDate(debt.due_date)}</span>}
        <button className="icon-action" type="button" aria-label="Mettre à jour" onClick={() => setEditing(true)}><Icon name="edit" /></button>
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
      {(update.error || remove.error) && <p className="form-error">{errorMessage(update.error ?? remove.error)}</p>}
    </article>
  )
}

function DebtForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [initialAmount, setInitialAmount] = useState('')
  const [remainingAmount, setRemainingAmount] = useState('')
  const [monthlyPayment, setMonthlyPayment] = useState('')
  const [interestRate, setInterestRate] = useState('0')
  const [dueDate, setDueDate] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Debt>('/debts', {
      name,
      principal: initialAmount,
      balance: remainingAmount,
      minimum_payment: monthlyPayment,
      interest_rate: interestRate,
      due_date: dueDate || null,
      color: '#ff6b70',
    }),
    onSuccess: onSaved,
  })

  return (
    <Panel title="Nouvelle dette" subtitle="Renseignez uniquement les données nécessaires au suivi.">
      <form className="feature-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom">
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
        </Field>
        <Field label="Capital initial">
          <input type="number" min="0" step="0.01" value={initialAmount} onChange={(event) => setInitialAmount(event.target.value)} required />
        </Field>
        <Field label="Capital restant">
          <input type="number" min="0" step="0.01" value={remainingAmount} onChange={(event) => setRemainingAmount(event.target.value)} required />
        </Field>
        <Field label="Mensualité">
          <input type="number" min="0" step="0.01" value={monthlyPayment} onChange={(event) => setMonthlyPayment(event.target.value)} required />
        </Field>
        <Field label="Taux annuel (%)">
          <input type="number" min="0" step="0.01" value={interestRate} onChange={(event) => setInterestRate(event.target.value)} required />
        </Field>
        <Field label="Échéance">
          <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
        </Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? 'Ajout…' : 'Ajouter'}
          </button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
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

function holdingGainPercent(holding: Holding): number {
  return Number(holding.cost_basis) > 0
    ? (Number(holding.gain) / Number(holding.cost_basis)) * 100
    : 0
}

function formatQuantity(value: string): string {
  return Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 6 })
}
