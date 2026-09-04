import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  Sankey,
  Tooltip,
} from 'recharts'

import { apiDelete, apiGet, apiPatch, apiPost, queryString } from '../api/client'
import type {
  Account,
  AppSettings,
  BudgetOverview,
  CashflowFlow,
  CategorizationInboxItem,
  CategorizationRule,
  CategorizationSuggestion,
  Category,
  Envelope,
  MerchantIdentity,
  RecurringChange,
  RecurringForecastItem,
  RecurringSeries,
  SpendingNode,
  Transaction,
  TransactionCount,
} from '../api/types'
import type { BudgetTab, Route } from '../routing'
import {
  AmountDirectionToggle,
  EmptyState,
  Field,
  Icon,
  MerchantAvatar,
  Panel,
  ProgressBar,
  StatusBadge,
  chartTooltipStyle,
  directedAmount,
  errorMessage,
  formatDate,
  formatMonth,
  initials,
  localDateInputValue,
  money,
  signedMoney,
  type TransactionDirection,
} from '../ui'

const budgetTabs: Array<{ id: BudgetTab; label: string; icon: Parameters<typeof Icon>[0]['name'] }> = [
  { id: 'overview', label: 'Aperçu', icon: 'grid' },
  { id: 'cashflow', label: 'Cashflow', icon: 'trend' },
  { id: 'recurring', label: 'Récurrents', icon: 'recurring' },
  { id: 'envelopes', label: 'Enveloppes', icon: 'budget' },
  { id: 'categorize', label: 'À catégoriser', icon: 'sparkle' },
  { id: 'transactions', label: 'Transactions', icon: 'receipt' },
  { id: 'manage', label: 'Gérer', icon: 'rules' },
]

export function BudgetView({
  tab,
  accounts,
  categories,
  merchants,
  transactions,
  settings,
  navigate,
  onRefresh,
}: {
  tab: BudgetTab
  accounts: Account[]
  categories: Category[]
  merchants: MerchantIdentity[]
  transactions: Transaction[]
  settings?: AppSettings
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  return (
    <div className="view-stack">
      <nav className="module-tabs budget-tabs" aria-label="Budget et cashflow">
        {budgetTabs.map((item) => (
          <button
            className={tab === item.id ? 'active' : ''}
            type="button"
            key={item.id}
            onClick={() => navigate({ name: 'budget', tab: item.id })}
          >
            <Icon name={item.icon} />
            {item.label}
            {item.id === 'categorize' && (
              <span className="nav-count">{transactions.filter((transaction) => transaction.category_id === null).length}</span>
            )}
          </button>
        ))}
      </nav>

      {tab === 'overview' && <BudgetOverviewPanel navigate={navigate} />}
      {tab === 'cashflow' && <CashflowPanel categories={categories} />}
      {tab === 'recurring' && <RecurringPanel accounts={accounts} categories={categories} />}
      {tab === 'envelopes' && <EnvelopePanel categories={categories} onRefresh={onRefresh} />}
      {tab === 'categorize' && (
        <CategorizationPanel
          categories={categories}
          merchants={merchants}
          settings={settings}
          onRefresh={onRefresh}
        />
      )}
      {tab === 'transactions' && (
        <TransactionLedger accounts={accounts} categories={categories} onRefresh={onRefresh} />
      )}
      {tab === 'manage' && <ManageBudget categories={categories} onRefresh={onRefresh} />}
    </div>
  )
}

function BudgetOverviewPanel({
  navigate,
}: {
  navigate: (route: Route) => void
}) {
  const [anchorDate, setAnchorDate] = useState(localDateInputValue)
  const overview = useQuery({
    queryKey: ['budget-overview', anchorDate],
    queryFn: () => apiGet<BudgetOverview>(`/budget/overview${queryString({ on: anchorDate })}`),
  })
  const forecast = useQuery({
    queryKey: ['recurring-forecast', 1],
    queryFn: () => apiGet<RecurringForecastItem[]>('/recurring/forecast?months=1'),
  })
  const envelopes = useQuery({
    queryKey: ['budget-envelopes', anchorDate],
    queryFn: () => apiGet<Envelope[]>(`/budget/envelopes${queryString({ on: anchorDate })}`),
  })
  const topEnvelopes = [...(envelopes.data ?? [])]
    .sort((left, right) => envelopeReadRatio(right) - envelopeReadRatio(left))
    .slice(0, 5)

  return (
    <>
      <section className="period-toolbar">
        <p>Vue synthétique de votre cycle budgétaire.</p>
        <PeriodPicker value={anchorDate} onChange={setAnchorDate} />
      </section>
      {(overview.error || forecast.error || envelopes.error) && (
        <div className="error-banner">{errorMessage(overview.error ?? forecast.error ?? envelopes.error)}</div>
      )}
      <section className="metric-grid">
        <BudgetMetric label="Solde net du cycle" value={signedMoney(overview.data?.net ?? 0)} detail={`${money(overview.data?.income)} entrées · ${money(overview.data?.expenses)} sorties`} tone={Number(overview.data?.net ?? 0) >= 0 ? 'positive' : 'negative'} icon="trend" />
        <BudgetMetric
          label="Enveloppes"
          value={money(overview.data?.envelope_spent ?? Number(overview.data?.budget_total ?? 0) - Number(overview.data?.budget_remaining ?? 0))}
          detail={`sur ${money(overview.data?.budget_total)}`}
          icon="budget"
        />
        <BudgetMetric
          label="À venir"
          value={signedMoney(overview.data?.upcoming_recurring_amount ?? 0)}
          detail={`${overview.data?.upcoming_recurring_count ?? 0} échéance${overview.data?.upcoming_recurring_count === 1 ? '' : 's'}`}
          icon="calendar"
        />
        <BudgetMetric label="Épargne du cycle" value={money(overview.data?.savings_contributions)} detail="Contributions enregistrées" icon="wealth" />
      </section>

      {(overview.data?.uncategorized_count ?? 0) > 0 && (
        <button className="attention-card" type="button" onClick={() => navigate({ name: 'budget', tab: 'categorize' })}>
          <span><Icon name="sparkle" />{overview.data?.uncategorized_count} transaction{overview.data?.uncategorized_count === 1 ? '' : 's'} à catégoriser</span>
          <Icon name="arrow" />
        </button>
      )}

      <section className="dashboard-grid">
        <Panel title="Enveloppes les plus sollicitées" subtitle="Consommation sur le cycle">
          {topEnvelopes.length > 0 ? (
            <div className="envelope-summary-list">
              {topEnvelopes.map((category) => {
                const ratio = envelopeReadRatio(category)
                return (
                  <div key={category.category_id}>
                    <div><span><i style={{ background: category.color }} />{category.category_name}</span><strong>{Math.round(ratio)}%</strong></div>
                    <ProgressBar value={ratio} color={category.color} danger={ratio > 100} />
                  </div>
                )
              })}
            </div>
          ) : (
            <EmptyState icon="budget" text="Configurez une enveloppe pour suivre sa consommation." />
          )}
        </Panel>
        <Panel title="Prochaines échéances" subtitle="Mouvements récurrents attendus">
          <ForecastList items={(forecast.data ?? []).slice(0, 6)} />
        </Panel>
      </section>
    </>
  )
}

function CashflowPanel({ categories }: { categories: Category[] }) {
  const [anchorDate, setAnchorDate] = useState(localDateInputValue)
  const [period, setPeriod] = useState<'cycle' | 'year'>('cycle')
  const sourceFlows = useQuery({
    queryKey: ['budget-cashflow', anchorDate, period, 'source'],
    queryFn: () => apiGet<CashflowFlow[]>(`/budget/cashflow${queryString({ on: anchorDate, period, by: 'source' })}`),
  })
  const categoryFlows = useQuery({
    queryKey: ['budget-cashflow', anchorDate, period, 'category'],
    queryFn: () => apiGet<CashflowFlow[]>(`/budget/cashflow${queryString({ on: anchorDate, period, by: 'category' })}`),
  })
  const spending = useQuery({
    queryKey: ['budget-spending', anchorDate, period],
    queryFn: () => apiGet<SpendingNode[]>(`/budget/spending${queryString({ on: anchorDate, period })}`),
  })
  const sankeyData = useMemo(
    () => buildSankey(sourceFlows.data ?? [], categoryFlows.data ?? []),
    [categoryFlows.data, sourceFlows.data],
  )
  const income = (sourceFlows.data ?? []).reduce((total, flow) => total + Number(flow.inflow), 0)
  const expenses = (categoryFlows.data ?? []).reduce((total, flow) => total + Number(flow.outflow), 0)

  return (
    <>
      <section className="period-toolbar">
        <p>Visualisez comment circule votre argent.</p>
        <div className="period-actions">
          <PeriodPicker value={anchorDate} onChange={setAnchorDate} />
          <div className="segmented-control compact-segments">
            <button className={period === 'cycle' ? 'active' : ''} type="button" onClick={() => setPeriod('cycle')}>Cycle</button>
            <button className={period === 'year' ? 'active' : ''} type="button" onClick={() => setPeriod('year')}>Année</button>
          </div>
        </div>
      </section>
      {(sourceFlows.error || categoryFlows.error || spending.error) && (
        <div className="error-banner">{errorMessage(sourceFlows.error ?? categoryFlows.error ?? spending.error)}</div>
      )}
      <Panel title="Flux de la période" subtitle={`Entrées ${money(income)} · Sorties ${money(expenses)} · Solde ${signedMoney(income - expenses)}`}>
        <div className="sankey-mobile-summary">
          <span>{(sourceFlows.data ?? []).filter((flow) => Number(flow.inflow) > 0).map((flow) => flow.label).join(', ') || 'Sources'}</span>
          <Icon name="arrow" />
          <strong>Disponible</strong>
        </div>
        <div className="sankey-container">
          {sankeyData.links.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <Sankey
                data={sankeyData}
                link={{ stroke: '#615fff', strokeOpacity: 0.32 }}
                nodePadding={28}
                nodeWidth={12}
                node={CashflowSankeyNode}
                linkCurvature={0.52}
                iterations={32}
                margin={{ top: 20, right: 120, bottom: 20, left: 90 }}
              >
                <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
              </Sankey>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon="trend" text="Ajoutez des revenus et dépenses pour construire le flux." />
          )}
        </div>
      </Panel>
      <Panel title="Où part votre argent" subtitle="Catégories et sous-catégories">
        <SpendingTree categories={categories} nodes={spending.data ?? []} />
      </Panel>
    </>
  )
}

function RecurringPanel({ accounts, categories }: { accounts: Account[]; categories: Category[] }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const series = useQuery({
    queryKey: ['recurring-series'],
    queryFn: () => apiGet<RecurringSeries[]>('/recurring'),
  })
  const forecast = useQuery({
    queryKey: ['recurring-forecast', 3],
    queryFn: () => apiGet<RecurringForecastItem[]>('/recurring/forecast?months=3'),
  })
  const changes = useQuery({
    queryKey: ['recurring-changes'],
    queryFn: () => apiGet<RecurringChange[]>('/recurring/changes'),
  })
  const detect = useMutation({
    mutationFn: () => apiPost<{ created_series: number; created_changes: number }>('/recurring/detect'),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['recurring-series'] }),
        queryClient.invalidateQueries({ queryKey: ['recurring-changes'] }),
        queryClient.invalidateQueries({ queryKey: ['recurring-forecast'] }),
      ])
    },
  })
  const errors = [series.error, forecast.error, changes.error].filter(Boolean)

  return (
    <>
      <section className="section-intro">
        <p>Abonnements, revenus et prélèvements récurrents.</p>
        <div className="header-actions">
          <button className="secondary-button" type="button" onClick={() => detect.mutate()} disabled={detect.isPending}>
            <Icon name="refresh" />{detect.isPending ? 'Détection…' : 'Détecter'}
          </button>
          <button className="primary-button" type="button" onClick={() => setShowForm((current) => !current)}>
            <Icon name="plus" />Ajouter
          </button>
        </div>
      </section>
      {showForm && (
        <RecurringForm
          accounts={accounts}
          categories={categories}
          onCancel={() => setShowForm(false)}
          onSaved={async () => {
            await queryClient.invalidateQueries({ queryKey: ['recurring-series'] })
            await queryClient.invalidateQueries({ queryKey: ['recurring-forecast'] })
            setShowForm(false)
          }}
        />
      )}
      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}
      {detect.error && <div className="error-banner">{errorMessage(detect.error)}</div>}
      <RecurringChanges changes={changes.data ?? []} series={series.data ?? []} />
      <Panel title="Prochaines échéances" subtitle="Projection sur trois mois">
        <ForecastByMonth items={forecast.data ?? []} />
      </Panel>
      <Panel title="Séries récurrentes" subtitle={`${series.data?.length ?? 0} série${series.data?.length === 1 ? '' : 's'} configurée${series.data?.length === 1 ? '' : 's'}`}>
        {(series.data ?? []).length > 0 ? (
          <div className="recurring-list">
            {series.data?.map((item) => <RecurringRow item={item} key={item.id} />)}
          </div>
        ) : (
          <EmptyState icon="recurring" text="Ajoutez une série ou lancez la détection sur l'historique." />
        )}
      </Panel>
    </>
  )
}

function RecurringChanges({ changes, series }: { changes: RecurringChange[]; series: RecurringSeries[] }) {
  const queryClient = useQueryClient()
  const pending = changes.filter((change) => change.status === 'pending')
  const action = useMutation({
    mutationFn: ({ id, status }: { id: number; status: 'accepted' | 'rejected' }) =>
      apiPost<RecurringChange>(`/recurring/changes/${id}/action${queryString({ action: status === 'accepted' ? 'accept' : 'reject' })}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['recurring-changes'] })
      await queryClient.invalidateQueries({ queryKey: ['recurring-series'] })
    },
  })
  if (pending.length === 0) return null
  return (
    <Panel title="Ce qui a changé" subtitle="Chaque changement nécessite une décision explicite.">
      <div className="change-list">
        {pending.map((change) => (
          <article key={change.id}>
            <span className="transaction-avatar">{initials(change.series_label ?? series.find((item) => item.id === change.series_id)?.label ?? 'Série')}</span>
            <span>
              <strong>{change.series_label ?? series.find((item) => item.id === change.series_id)?.label ?? `Série ${change.series_id}`}</strong>
              <small>
                {change.change_type === 'amount' ? 'Nouveau montant détecté' : 'Nouvelle échéance détectée'}
                {change.detected_amount !== null && ` : ${money(change.detected_amount)}`}
                {change.detected_next_due && ` · ${formatDate(change.detected_next_due)}`}
              </small>
              {change.note && <small>{change.note}</small>}
            </span>
            <div>
              <button className="icon-action positive" type="button" aria-label="Accepter" onClick={() => action.mutate({ id: change.id, status: 'accepted' })}><Icon name="check" /></button>
              <button className="icon-action" type="button" aria-label="Refuser" onClick={() => action.mutate({ id: change.id, status: 'rejected' })}><Icon name="close" /></button>
            </div>
          </article>
        ))}
      </div>
      {action.error && <p className="form-error">{errorMessage(action.error)}</p>}
    </Panel>
  )
}

function RecurringRow({ item }: { item: RecurringSeries }) {
  const queryClient = useQueryClient()
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['recurring-series'] })
    await queryClient.invalidateQueries({ queryKey: ['recurring-forecast'] })
  }
  const update = useMutation({
    mutationFn: (status: RecurringSeries['status']) =>
      apiPatch<RecurringSeries>(`/recurring/${item.id}`, { status }),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/recurring/${item.id}`),
    onSuccess: refresh,
  })
  return (
    <article>
      <span className="transaction-avatar">{initials(item.label)}</span>
      <span className="recurring-copy">
        <span>
          <strong>{item.label}</strong>
          <StatusBadge tone={statusTone(item.status)}>{statusLabel(item.status)}</StatusBadge>
          {item.amount_type === 'variable' && <StatusBadge>Montant variable</StatusBadge>}
        </span>
        <small>{frequencyLabel(item.frequency)} · prochaine le {formatDate(item.next_due)}</small>
        <small>Détection locale · {Math.round(item.confidence * 100)}% de confiance</small>
      </span>
      <strong className={Number(item.amount ?? 0) >= 0 ? 'positive' : ''}>{signedMoney(item.amount ?? 0)}</strong>
      <div className="row-actions">
        {item.status === 'paused' && (
          <button className="icon-action positive" type="button" aria-label="Réactiver" onClick={() => update.mutate('active')}><Icon name="check" /></button>
        )}
        {item.status === 'active' && (
          <button className="icon-action" type="button" aria-label="Mettre en pause" onClick={() => update.mutate('paused')}><Icon name="close" /></button>
        )}
      </div>
      <button
        className="icon-action"
        type="button"
        aria-label="Supprimer"
        onClick={() => {
          if (window.confirm('Supprimer cette série récurrente ?')) remove.mutate()
        }}
        disabled={remove.isPending}
      >
        <Icon name="trash" />
      </button>
      {(update.error || remove.error) && <span className="form-error row-error">{errorMessage(update.error ?? remove.error)}</span>}
    </article>
  )
}

function RecurringForm({
  accounts,
  categories,
  onCancel,
  onSaved,
}: {
  accounts: Account[]
  categories: Category[]
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const [name, setName] = useState('')
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [amount, setAmount] = useState('')
  const [frequency, setFrequency] = useState<RecurringSeries['frequency']>('monthly')
  const [nextDueDate, setNextDueDate] = useState(localDateInputValue)
  const [variable, setVariable] = useState(false)
  const mutation = useMutation({
    mutationFn: () => apiPost<RecurringSeries>('/recurring', {
      label: name,
      account_id: Number(accountId || accounts[0]?.id),
      category_id: categoryId ? Number(categoryId) : null,
      amount,
      frequency,
      next_due: nextDueDate,
      amount_type: variable ? 'variable' : 'fixed',
      status: 'active',
      confidence: 1,
    }),
    onSuccess: onSaved,
  })
  return (
    <Panel title="Nouvelle série récurrente">
      <form className="feature-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom"><input value={name} onChange={(event) => setName(event.target.value)} required /></Field>
        <Field label="Compte">
          <select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </select>
        </Field>
        <Field label="Catégorie">
          <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Sans catégorie</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </Field>
        <Field label="Montant"><input type="number" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></Field>
        <Field label="Fréquence">
          <select value={frequency} onChange={(event) => setFrequency(event.target.value as RecurringSeries['frequency'])}>
            <option value="weekly">Hebdomadaire</option>
            <option value="monthly">Mensuelle</option>
            <option value="quarterly">Trimestrielle</option>
            <option value="yearly">Annuelle</option>
          </select>
        </Field>
        <Field label="Prochaine échéance"><input type="date" value={nextDueDate} onChange={(event) => setNextDueDate(event.target.value)} required /></Field>
        <label className="checkbox-field"><input type="checkbox" checked={variable} onChange={(event) => setVariable(event.target.checked)} />Montant variable</label>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending || accounts.length === 0}>Créer</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function EnvelopePanel({ categories, onRefresh }: { categories: Category[]; onRefresh: () => Promise<void> }) {
  const envelopes = useQuery({
    queryKey: ['budget-envelopes', 'current'],
    queryFn: () => apiGet<Envelope[]>('/budget/envelopes'),
  })
  const expenses = categories.filter((category) => category.kind === 'expense' && !category.archived)
  const totalBudget = expenses.reduce((sum, category) => sum + Number(category.monthly_budget ?? 0), 0)
  const totalSpent = (envelopes.data ?? []).reduce((sum, envelope) => sum + Number(envelope.spent), 0)
  return (
    <>
      <section className="section-intro"><p>Un plafond mensuel par catégorie de dépense.</p></section>
      {envelopes.error && <div className="error-banner">{errorMessage(envelopes.error)}</div>}
      <section className="metric-grid budget-summary">
        <BudgetMetric label="Budget mensuel" value={money(totalBudget)} icon="budget" />
        <BudgetMetric label="Dépensé" value={money(totalSpent)} icon="receipt" tone="negative" />
        <BudgetMetric label="Disponible" value={money(totalBudget - totalSpent)} icon="trend" tone={totalBudget >= totalSpent ? 'positive' : 'negative'} />
      </section>
      <section className="budget-list">
        {expenses.map((category) => (
          <EnvelopeCard
            category={category}
            key={category.id}
            onSaved={async () => {
              await envelopes.refetch()
              await onRefresh()
            }}
            spent={(envelopes.data ?? []).find((envelope) => envelope.category_id === category.id)?.spent}
          />
        ))}
      </section>
    </>
  )
}

function EnvelopeCard({
  category,
  onSaved,
  spent: spentValue,
}: {
  category: Category
  onSaved: () => Promise<void>
  spent?: string
}) {
  const [editing, setEditing] = useState(false)
  const [budget, setBudget] = useState(category.monthly_budget ?? '')
  const spent = Number(spentValue ?? 0)
  const limit = Number(category.monthly_budget ?? 0)
  const ratio = limit > 0 ? (spent / limit) * 100 : 0
  const update = useMutation({
    mutationFn: () => apiPatch<Category>(`/categories/${category.id}/budget`, { monthly_budget: budget || null }),
    onSuccess: async () => {
      setEditing(false)
      await onSaved()
    },
  })
  return (
    <article className="budget-card">
      <div className="budget-card-top">
        <div>
          <h2><i style={{ background: category.color }} />{category.name}</h2>
          <p>{category.monthly_budget === null ? 'Aucun plafond' : `${money(spent)} / ${money(limit)}`}</p>
        </div>
        {editing ? (
          <form className="budget-editor" onSubmit={(event) => {
            event.preventDefault()
            update.mutate()
          }}>
            <input type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} autoFocus />
            <button className="primary-button small-button" type="submit">Enregistrer</button>
            <button className="text-button" type="button" onClick={() => setEditing(false)}>Annuler</button>
          </form>
        ) : (
          <button className="secondary-button small-button" type="button" onClick={() => setEditing(true)}>
            <Icon name="edit" />{category.monthly_budget === null ? 'Configurer' : 'Modifier'}
          </button>
        )}
      </div>
      <ProgressBar value={ratio} color={category.color} danger={ratio > 100} />
      <div className="budget-card-bottom">
        <span>{Math.round(ratio)}% consommé</span>
        {category.monthly_budget !== null && <strong className={limit - spent < 0 ? 'negative' : ''}>{limit - spent >= 0 ? `${money(limit - spent)} disponibles` : `${money(spent - limit)} dépassés`}</strong>}
      </div>
      {update.error && <p className="form-error">{errorMessage(update.error)}</p>}
    </article>
  )
}

function CategorizationPanel({
  categories,
  merchants,
  settings,
  onRefresh,
}: {
  categories: Category[]
  merchants: MerchantIdentity[]
  settings?: AppSettings
  onRefresh: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const [suggestionByTransaction, setSuggestionByTransaction] = useState<Record<number, CategorizationSuggestion>>({})
  const inbox = useQuery({
    queryKey: ['categorization-inbox'],
    queryFn: () => apiGet<CategorizationInboxItem[]>('/categorization/inbox'),
  })
  const rules = useQuery({
    queryKey: ['categorization-rules'],
    queryFn: () => apiGet<CategorizationRule[]>('/rules'),
  })
  const applyRules = useMutation({
    mutationFn: () => apiPost<{ updated: number; scanned: number }>('/rules/apply'),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['categorization-inbox'] })
      await onRefresh()
    },
  })
  const suggestions = useMutation({
    mutationFn: () => Promise.all(
      (inbox.data ?? []).map((item) =>
        apiPost<CategorizationSuggestion>(`/categorization/suggest/${item.transaction_id}`),
      ),
    ),
    onSuccess: async (results) => {
      setSuggestionByTransaction(
        Object.fromEntries(results.map((result) => [result.transaction_id, result])),
      )
      await queryClient.invalidateQueries({ queryKey: ['categorization-inbox'] })
      await onRefresh()
    },
  })
  return (
    <>
      <section className="section-intro">
        <p>Affectez une catégorie aux transactions non classées.</p>
        <div className="header-actions">
          {settings?.private_categorization_enabled && (
            <button className="primary-button" type="button" onClick={() => suggestions.mutate()} disabled={suggestions.isPending}>
              <Icon name="sparkle" />Suggestions locales
            </button>
          )}
          <button className="secondary-button" type="button" onClick={() => applyRules.mutate()} disabled={applyRules.isPending}>
            <Icon name="rules" />Appliquer les règles
          </button>
        </div>
      </section>
      {(inbox.error || rules.error || applyRules.error || suggestions.error) && (
        <div className="error-banner">{errorMessage(inbox.error ?? rules.error ?? applyRules.error ?? suggestions.error)}</div>
      )}
      {(inbox.data ?? []).length > 0 ? (
        <div className="categorization-list">
          {inbox.data?.map((item) => (
            <CategorizationCard
              categories={categories.filter((category) => !category.archived)}
              item={item}
              key={item.transaction_id}
              merchants={merchants}
              suggestion={suggestionByTransaction[item.transaction_id]}
              onSaved={async () => {
                await queryClient.invalidateQueries({ queryKey: ['categorization-inbox'] })
                await onRefresh()
              }}
            />
          ))}
        </div>
      ) : (
        <EmptyState icon="check" title="Tout est classé" text="Aucune transaction n'attend de catégorie." />
      )}
      <RulesPanel categories={categories} rules={rules.data ?? []} />
    </>
  )
}

function CategorizationCard({
  categories,
  item,
  merchants,
  suggestion,
  onSaved,
}: {
  categories: Category[]
  item: CategorizationInboxItem
  merchants: MerchantIdentity[]
  suggestion?: CategorizationSuggestion
  onSaved: () => Promise<void>
}) {
  const [categoryId, setCategoryId] = useState(String(suggestion?.category_id ?? ''))
  const [createRule, setCreateRule] = useState(false)
  useEffect(() => {
    if (suggestion?.category_id) setCategoryId(String(suggestion.category_id))
  }, [suggestion?.category_id])
  const assign = useMutation({
    mutationFn: async () => {
      const transaction = await apiPatch<Transaction>(`/transactions/${item.transaction_id}`, { category_id: Number(categoryId) })
      if (createRule) {
        await apiPost<CategorizationRule>('/rules', {
          name: 'Règle de bénéficiaire',
          match_type: 'beneficiary',
          pattern: item.description,
          category_id: Number(categoryId),
          priority: 100,
          enabled: true,
        })
      }
      return transaction
    },
    onSuccess: onSaved,
  })
  return (
    <article>
      <div className="categorization-head">
        <MerchantAvatar description={item.description} identities={merchants} />
        <span>
          <strong>{item.description}</strong>
          <small>{formatDate(item.booked_at)}</small>
          {suggestion?.category_id && (
            <StatusBadge tone="primary">Suggestion : {suggestion.category_name} · {Math.round(suggestion.confidence * 100)}%</StatusBadge>
          )}
        </span>
        <strong className={Number(item.amount) >= 0 ? 'positive' : ''}>{signedMoney(item.amount)}</strong>
      </div>
      <div className="categorization-actions">
        <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
          <option value="">Choisir une catégorie</option>
          {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
        </select>
        <label><input type="checkbox" checked={createRule} onChange={(event) => setCreateRule(event.target.checked)} />Créer une règle pour ce libellé</label>
        <button className="primary-button" type="button" disabled={!categoryId || assign.isPending} onClick={() => assign.mutate()}>Affecter</button>
      </div>
      {assign.error && <p className="form-error">{errorMessage(assign.error)}</p>}
    </article>
  )
}

function RulesPanel({ categories, rules }: { categories: Category[]; rules: CategorizationRule[] }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  return (
    <Panel
      title="Règles de catégorisation"
      subtitle="Les règles déterministes sont toujours appliquées avant les suggestions locales."
      action={<button className="secondary-button small-button" type="button" onClick={() => setShowForm((current) => !current)}><Icon name="plus" />Nouvelle règle</button>}
    >
      {showForm && (
        <RuleForm
          categories={categories}
          onCancel={() => setShowForm(false)}
          onSaved={async () => {
            await queryClient.invalidateQueries({ queryKey: ['categorization-rules'] })
            setShowForm(false)
          }}
        />
      )}
      {rules.length > 0 ? (
        <div className="rule-list">
          {rules.map((rule) => (
            <RuleRow
              categoryName={categories.find((category) => category.id === rule.category_id)?.name ?? 'Catégorie supprimée'}
              key={rule.id}
              rule={rule}
            />
          ))}
        </div>
      ) : (
        <EmptyState icon="rules" text="Aucune règle configurée." />
      )}
    </Panel>
  )
}

function RuleForm({ categories, onCancel, onSaved }: { categories: Category[]; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [matchType, setMatchType] = useState<CategorizationRule['match_type']>('beneficiary')
  const [pattern, setPattern] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<CategorizationRule>('/rules', {
      name: pattern,
      match_type: matchType,
      pattern,
      category_id: Number(categoryId),
      priority: 100,
      enabled: true,
    }),
    onSuccess: onSaved,
  })
  return (
    <form className="compact-feature-form rule-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <select value={matchType} onChange={(event) => setMatchType(event.target.value as CategorizationRule['match_type'])}>
        <option value="beneficiary">Bénéficiaire exact</option>
        <option value="keyword">Mot-clé</option>
      </select>
      <input value={pattern} onChange={(event) => setPattern(event.target.value)} placeholder="Valeur à reconnaître" required />
      <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)} required>
        <option value="">Catégorie cible</option>
        {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
      </select>
      <button className="primary-button small-button" type="submit">Créer</button>
      <button className="text-button" type="button" onClick={onCancel}>Annuler</button>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </form>
  )
}

function RuleRow({ categoryName, rule }: { categoryName: string; rule: CategorizationRule }) {
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => apiDelete(`/rules/${rule.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['categorization-rules'] }),
  })
  return (
    <div>
      <StatusBadge>{rule.match_type === 'beneficiary' ? 'Bénéficiaire' : 'Mot-clé'}</StatusBadge>
      <strong>{rule.pattern}</strong>
      <Icon name="arrow" />
      <span>{categoryName}</span>
      <span className="row-actions">
        <button className="icon-action" type="button" aria-label="Supprimer" onClick={() => remove.mutate()}><Icon name="trash" /></button>
        {remove.error && <span className="form-error">{errorMessage(remove.error)}</span>}
      </span>
    </div>
  )
}

function TransactionLedger({
  accounts,
  categories,
  onRefresh,
}: {
  accounts: Account[]
  categories: Category[]
  onRefresh: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const pageSize = 100
  const [showForm, setShowForm] = useState(false)
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [categoryFilter, search])
  const filters = {
    search: search.trim(),
    category_id: categoryFilter !== 'all' && categoryFilter !== 'none' ? categoryFilter : undefined,
    uncategorized: categoryFilter === 'none' ? true : undefined,
  }
  const pageQuery = useQuery({
    queryKey: ['transaction-ledger', page, filters.search, filters.category_id, filters.uncategorized],
    queryFn: () => apiGet<Transaction[]>(`/transactions${queryString({
      ...filters,
      limit: pageSize,
      offset: page * pageSize,
    })}`),
  })
  const countQuery = useQuery({
    queryKey: ['transaction-count', filters.search, filters.category_id, filters.uncategorized],
    queryFn: () => apiGet<TransactionCount>(`/transactions/count${queryString(filters)}`),
  })
  const filtered = pageQuery.data ?? []
  const total = countQuery.data?.count ?? 0
  const refreshLedger = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['transaction-ledger'] }),
      queryClient.invalidateQueries({ queryKey: ['transaction-count'] }),
      onRefresh(),
    ])
  }
  return (
    <>
      <section className="section-intro">
        <p>Registre complet de tous les mouvements persistants.</p>
        <button className="primary-button" type="button" onClick={() => setShowForm((current) => !current)}><Icon name="plus" />Ajouter une transaction</button>
      </section>
      {showForm && <TransactionForm accounts={accounts} categories={categories} onCancel={() => setShowForm(false)} onSaved={async () => { await refreshLedger(); setShowForm(false) }} />}
      {(pageQuery.error || countQuery.error) && <div className="error-banner">{errorMessage(pageQuery.error ?? countQuery.error)}</div>}
      <Panel title="Transactions" subtitle={`${total} résultat${total === 1 ? '' : 's'}`}>
        <div className="transaction-toolbar">
          <label className="search-field"><Icon name="search" /><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un libellé ou une note" /></label>
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
            <option value="all">Toutes les catégories</option>
            <option value="none">Sans catégorie</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </div>
        <div className="data-table-wrap">
          <table className="transaction-table">
            <thead><tr><th>Date</th><th>Libellé</th><th>Compte</th><th>Catégorie</th><th className="amount-column">Montant</th><th /></tr></thead>
            <tbody>
              {filtered.map((transaction) => <TransactionRow categories={categories} key={transaction.id} transaction={transaction} onSaved={refreshLedger} />)}
            </tbody>
          </table>
          {filtered.length === 0 && <EmptyState icon="receipt" text="Aucune transaction pour ces filtres." />}
        </div>
        {total > pageSize && (
          <div className="pagination">
            <button className="secondary-button small-button" type="button" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>
              <Icon name="back" />Précédent
            </button>
            <span>Page {page + 1} sur {Math.ceil(total / pageSize)}</span>
            <button className="secondary-button small-button" type="button" disabled={(page + 1) * pageSize >= total} onClick={() => setPage((current) => current + 1)}>
              Suivant<Icon name="arrow" />
            </button>
          </div>
        )}
      </Panel>
    </>
  )
}

function TransactionRow({ categories, transaction, onSaved }: { categories: Category[]; transaction: Transaction; onSaved: () => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [description, setDescription] = useState(transaction.description)
  const [categoryId, setCategoryId] = useState(String(transaction.category_id ?? ''))
  const update = useMutation({
    mutationFn: () => apiPatch<Transaction>(`/transactions/${transaction.id}`, { description, category_id: categoryId ? Number(categoryId) : null }),
    onSuccess: async () => { setEditing(false); await onSaved() },
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/transactions/${transaction.id}`),
    onSuccess: onSaved,
  })
  if (editing) {
    return (
      <tr>
        <td data-label="Date">{formatDate(transaction.booked_at)}</td>
        <td data-label="Libellé"><input value={description} onChange={(event) => setDescription(event.target.value)} /></td>
        <td data-label="Compte">{transaction.account_name}</td>
        <td data-label="Catégorie"><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">Sans catégorie</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></td>
        <td data-label="Montant" className="amount-column">{signedMoney(transaction.amount)}</td>
        <td data-label="Actions">
          <button className="icon-action positive" type="button" onClick={() => update.mutate()}><Icon name="check" /></button>
          <button className="icon-action" type="button" onClick={() => setEditing(false)}><Icon name="close" /></button>
          {update.error && <span className="form-error">{errorMessage(update.error)}</span>}
        </td>
      </tr>
    )
  }
  return (
    <tr>
      <td data-label="Date">{formatDate(transaction.booked_at)}</td>
      <td data-label="Libellé"><strong>{transaction.description}</strong>{transaction.notes && <small>{transaction.notes}</small>}</td>
      <td data-label="Compte">{transaction.account_name}</td>
      <td data-label="Catégorie">{transaction.category_name ?? 'Sans catégorie'}</td>
      <td data-label="Montant" className={`amount-column ${Number(transaction.amount) >= 0 ? 'positive' : 'negative'}`}>{signedMoney(transaction.amount)}</td>
      <td data-label="Actions" className="row-actions">
        <button className="icon-action" type="button" aria-label="Modifier" onClick={() => setEditing(true)}><Icon name="edit" /></button>
        <button
          className="icon-action"
          type="button"
          aria-label="Supprimer"
          onClick={() => {
            if (window.confirm('Supprimer définitivement cette transaction ?')) remove.mutate()
          }}
        >
          <Icon name="trash" />
        </button>
        {remove.error && <span className="form-error">{errorMessage(remove.error)}</span>}
      </td>
    </tr>
  )
}

function TransactionForm({ accounts, categories, onCancel, onSaved }: { accounts: Account[]; categories: Category[]; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [date, setDate] = useState(localDateInputValue)
  const [description, setDescription] = useState('')
  const [direction, setDirection] = useState<TransactionDirection>('withdrawal')
  const [amount, setAmount] = useState('')
  const [accountId, setAccountId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [notes, setNotes] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Transaction>('/transactions', { booked_at: date, description, amount: directedAmount(amount, direction), account_id: Number(accountId || accounts[0]?.id), category_id: categoryId ? Number(categoryId) : null, notes: notes || null }),
    onSuccess: onSaved,
  })
  return (
    <Panel title="Nouvelle transaction" subtitle="Choisissez un dépôt ou un retrait, puis saisissez un montant positif.">
      <AmountDirectionToggle value={direction} onChange={setDirection} />
      <form className="feature-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
        <Field label="Date"><input type="date" value={date} onChange={(event) => setDate(event.target.value)} required /></Field>
        <Field label="Libellé"><input value={description} onChange={(event) => setDescription(event.target.value)} required /></Field>
        <Field label="Montant"><input type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></Field>
        <Field label="Compte"><select value={accountId} onChange={(event) => setAccountId(event.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></Field>
        <Field label="Catégorie"><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">Sans catégorie</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></Field>
        <Field label="Note"><input value={notes} onChange={(event) => setNotes(event.target.value)} /></Field>
        <div className="form-buttons"><button className="secondary-button" type="button" onClick={onCancel}>Annuler</button><button className="primary-button" type="submit" disabled={accounts.length === 0}>Enregistrer</button></div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function ManageBudget({ categories, onRefresh }: { categories: Category[]; onRefresh: () => Promise<void> }) {
  const [showForm, setShowForm] = useState(false)
  const parents = categories.filter((category) => category.parent_id === null || category.parent_id === undefined)
  return (
    <>
      <section className="section-intro"><p>Catégories, sous-catégories et règles métier.</p><button className="primary-button" type="button" onClick={() => setShowForm((current) => !current)}><Icon name="plus" />Ajouter une catégorie</button></section>
      {showForm && <CategoryForm parents={parents} onCancel={() => setShowForm(false)} onSaved={async () => { await onRefresh(); setShowForm(false) }} />}
      <Panel title="Catégories" subtitle="Renommez, recolorez ou archivez vos catégories.">
        <div className="category-tree-list">
          {parents.map((category) => (
            <CategoryTreeRow category={category} children={categories.filter((child) => child.parent_id === category.id)} key={category.id} onSaved={onRefresh} />
          ))}
        </div>
      </Panel>
    </>
  )
}

function CategoryTreeRow({ category, children, onSaved }: { category: Category; children: Category[]; onSaved: () => Promise<void> }) {
  return (
    <div className={`category-tree-group ${category.archived ? 'archived' : ''}`}>
      <EditableCategoryRow category={category} onSaved={onSaved} />
      {children.map((child) => <EditableCategoryRow category={child} child key={child.id} onSaved={onSaved} />)}
    </div>
  )
}

function EditableCategoryRow({
  category,
  child = false,
  onSaved,
}: {
  category: Category
  child?: boolean
  onSaved: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(category.name)
  const [color, setColor] = useState(category.color)
  const update = useMutation({
    mutationFn: (payload: Partial<Category>) => apiPatch<Category>(`/categories/${category.id}`, payload),
    onSuccess: async () => {
      setEditing(false)
      await onSaved()
    },
  })
  if (editing) {
    return (
      <form className={`category-tree-row editing ${child ? 'child' : ''}`} onSubmit={(event) => {
        event.preventDefault()
        update.mutate({ name, color })
      }}>
        {child && <Icon name="arrow" />}
        <input className="color-input" type="color" aria-label="Couleur" value={color} onChange={(event) => setColor(event.target.value)} />
        <input value={name} onChange={(event) => setName(event.target.value)} required />
        <button className="icon-action positive" type="submit" aria-label="Enregistrer"><Icon name="check" /></button>
        <button className="icon-action" type="button" aria-label="Annuler" onClick={() => setEditing(false)}><Icon name="close" /></button>
      </form>
    )
  }
  return (
    <div className={`category-tree-row ${child ? 'child' : ''}`}>
      {child && <Icon name="arrow" />}
      <i style={{ background: category.color }} />
      <strong>{category.name}</strong>
      {child
        ? <small>Sous-catégorie</small>
        : <StatusBadge tone={category.kind === 'income' ? 'positive' : 'neutral'}>{category.kind === 'income' ? 'Revenu' : 'Dépense'}</StatusBadge>}
      {!child && category.is_default && <small>Par défaut</small>}
      <div className="row-actions">
        <button className="icon-action" type="button" aria-label="Modifier" onClick={() => setEditing(true)}><Icon name="edit" /></button>
        <button className="icon-action" type="button" aria-label={category.archived ? 'Restaurer' : 'Archiver'} onClick={() => update.mutate({ archived: !category.archived })}><Icon name={category.archived ? 'refresh' : 'trash'} /></button>
        {update.error && <span className="form-error">{errorMessage(update.error)}</span>}
      </div>
    </div>
  )
}

function CategoryForm({ parents, onCancel, onSaved }: { parents: Category[]; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState<'income' | 'expense'>('expense')
  const [color, setColor] = useState('#615fff')
  const [parentId, setParentId] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Category>('/categories', { name, kind, color, monthly_budget: null, parent_id: parentId ? Number(parentId) : null }),
    onSuccess: onSaved,
  })
  return (
    <Panel title="Nouvelle catégorie">
      <form className="inline-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
        <Field label="Nom"><input value={name} onChange={(event) => setName(event.target.value)} required /></Field>
        <Field label="Type"><select value={kind} onChange={(event) => setKind(event.target.value as 'income' | 'expense')}><option value="expense">Dépense</option><option value="income">Revenu</option></select></Field>
        <Field label="Parent"><select value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">Catégorie principale</option>{parents.filter((parent) => parent.kind === kind).map((parent) => <option key={parent.id} value={parent.id}>{parent.name}</option>)}</select></Field>
        <Field label="Couleur"><input className="color-input" type="color" value={color} onChange={(event) => setColor(event.target.value)} /></Field>
        <div className="form-buttons"><button className="secondary-button" type="button" onClick={onCancel}>Annuler</button><button className="primary-button" type="submit">Créer</button></div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function SpendingTree({ categories, nodes }: { categories: Category[]; nodes: SpendingNode[] }) {
  const maximum = Math.max(...nodes.map((node) => Number(node.amount)), 0)
  if (nodes.length === 0) return <EmptyState icon="budget" text="Aucune dépense sur cette période." />
  return (
    <div className="spending-tree">
      {nodes.map((node) => (
        <div className="spending-node" key={node.category_id ?? 'none'}>
          <SpendingLine color={categoryColor(node.category_id, categories)} node={node} maximum={maximum} />
          {(node.children ?? []).map((child) => (
            <div className="spending-child" key={child.category_id ?? child.category_name}>
              <SpendingLine color={categoryColor(child.category_id, categories)} node={child} maximum={Number(node.amount)} />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function SpendingLine({ color, node, maximum }: { color: string; node: SpendingNode; maximum: number }) {
  return (
    <div>
      <div className="spending-label"><span><i style={{ background: color }} /><strong>{node.category_name}</strong><small>{node.transaction_count} transaction{node.transaction_count === 1 ? '' : 's'}</small></span><strong>{money(node.amount)}</strong></div>
      <ProgressBar value={maximum > 0 ? (Number(node.amount) / maximum) * 100 : 0} color={color} />
    </div>
  )
}

function ForecastByMonth({ items }: { items: RecurringForecastItem[] }) {
  const groups = Object.entries(
    items.reduce<Record<string, RecurringForecastItem[]>>((result, item) => {
      const month = item.due_date.slice(0, 7)
      result[month] = [...(result[month] ?? []), item]
      return result
    }, {}),
  ).sort(([left], [right]) => left.localeCompare(right))
  if (groups.length === 0) return <EmptyState icon="calendar" text="Aucune échéance prévue." />
  return (
    <div className="forecast-groups">
      {groups.map(([month, monthItems]) => (
        <section key={month}>
          <h3>{formatMonth(month)}</h3>
          {monthItems.map((item) => (
            <div key={`${item.series_id}-${item.due_date}`}>
              <time>{new Date(`${item.due_date}T12:00:00`).getDate()}</time>
              <i style={{ background: item.color ?? '#615fff' }} />
              <span>{item.label}</span>
              <strong className={Number(item.amount) >= 0 ? 'positive' : ''}>{signedMoney(item.amount)}</strong>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}

function ForecastList({ items }: { items: RecurringForecastItem[] }) {
  if (items.length === 0) return <EmptyState icon="calendar" text="Aucune échéance prévue." />
  return (
    <div className="data-list">
      {items.map((item) => (
        <div key={`${item.series_id}-${item.due_date}`}>
          <span className="data-list-icon"><Icon name="calendar" /></span>
          <span><strong>{item.label}</strong><small>{formatDate(item.due_date)}</small></span>
          <strong className={Number(item.amount) >= 0 ? 'positive' : ''}>{signedMoney(item.amount)}</strong>
        </div>
      ))}
    </div>
  )
}

function BudgetMetric({ label, value, detail, icon, tone }: { label: string; value: string; detail?: string; icon: Parameters<typeof Icon>[0]['name']; tone?: 'positive' | 'negative' }) {
  return (
    <article className="metric-card"><span className="metric-icon"><Icon name={icon} /></span><div><p>{label}</p><strong className={tone}>{value}</strong>{detail && <small>{detail}</small>}</div></article>
  )
}

function PeriodPicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const shiftMonth = (delta: number) => {
    const current = new Date(`${value}T12:00:00`)
    current.setMonth(current.getMonth() + delta)
    const adjusted = new Date(current.getTime() - current.getTimezoneOffset() * 60_000)
    onChange(adjusted.toISOString().slice(0, 10))
  }
  return (
    <div className="period-picker">
      <button type="button" aria-label="Période précédente" onClick={() => shiftMonth(-1)}><Icon name="back" /></button>
      <strong>{formatMonth(value.slice(0, 7))}</strong>
      <button type="button" aria-label="Période suivante" onClick={() => shiftMonth(1)}><Icon name="arrow" /></button>
    </div>
  )
}

function buildSankey(sourceFlows: CashflowFlow[], categoryFlows: CashflowFlow[]) {
  const sources = sourceFlows
    .filter((flow) => Number(flow.inflow) > 0)
    .map((flow) => ({ name: flow.label, amount: Number(flow.inflow) }))
  const destinations = categoryFlows
    .filter((flow) => Number(flow.outflow) > 0)
    .map((flow) => ({ name: flow.label, amount: Number(flow.outflow) }))
  if (sources.length === 0 || destinations.length === 0) return { nodes: [], links: [] }
  const flowColors = ['#615fff', '#16c79a', '#f7b500', '#ec4899', '#1da9e8', '#f97316', '#8758f6']
  const nodes = [
    ...sources.map((node) => ({ name: node.name, color: '#16c79a', role: 'source' })),
    { name: 'Disponible', color: '#10a37f', role: 'hub' },
    ...destinations.map((node, index) => ({
      name: node.name,
      color: flowColors[index % flowColors.length],
      role: 'destination',
    })),
  ]
  const hubIndex = sources.length
  const links = [
    ...sources.map((node, index) => ({ source: index, target: hubIndex, value: node.amount })),
    ...destinations.map((node, index) => ({ source: hubIndex, target: hubIndex + 1 + index, value: node.amount })),
  ]
  return { nodes, links }
}

interface CashflowSankeyNodeProps {
  x: number
  y: number
  width: number
  height: number
  payload: { name: string; color: string; role: 'source' | 'hub' | 'destination' }
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
      <rect x={x} y={y} width={width} height={Math.max(height, 3)} rx={3} fill={payload.color} />
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

function categoryColor(categoryId: number | null, categories: Category[]): string {
  return categories.find((category) => category.id === categoryId)?.color ?? '#85858c'
}

function envelopeReadRatio(envelope: Envelope): number {
  return Number(envelope.budget) > 0
    ? (Number(envelope.spent) / Number(envelope.budget)) * 100
    : 0
}

function statusTone(status: RecurringSeries['status']): 'neutral' | 'positive' | 'warning' {
  if (status === 'active') return 'positive'
  if (status === 'paused') return 'warning'
  return 'neutral'
}

function statusLabel(status: RecurringSeries['status']): string {
  return { active: 'Actif', paused: 'En pause', ended: 'Terminé' }[status]
}

function frequencyLabel(frequency: RecurringSeries['frequency']): string {
  return { weekly: 'Hebdomadaire', monthly: 'Mensuel', quarterly: 'Trimestriel', yearly: 'Annuel' }[frequency]
}
