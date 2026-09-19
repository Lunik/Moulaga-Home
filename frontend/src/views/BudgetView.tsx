import { FormEvent, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPatch, apiPost, queryString } from '../api/client'
import {
  AttachmentManager,
  AttachmentPicker,
  uploadOwnerAttachment,
} from '../AttachmentManager'
import {
  RecurringCashflowSankey,
} from '../RecurringCashflowSankey'
import type {
  Account,
  BudgetOverview,
  CashflowFlow,
  Category,
  RecurringForecastItem,
  RecurringSeries,
  RecurringType,
  SpendingNode,
} from '../api/types'
import type { BudgetTab, Route } from '../routing'
import {
  AmountDirectionToggle,
  DatePicker,
  EmptyState,
  Field,
  FormInput,
  FormSelect,
  Icon,
  MetricCard,
  Modal,
  Panel,
  ProgressBar,
  StatusBadge,
  directedAmount,
  errorMessage,
  formatDate,
  formatMonth,
  linkedEntityTargetId,
  localDateInputValue,
  monthBoundaryDate,
  monthInputValue,
  money,
  signedMoney,
  type AmountDirection,
  useLinkedEntityFocus,
} from '../ui'

const budgetTabs: Array<{
  id: BudgetTab
  label: string
  icon: Parameters<typeof Icon>[0]['name']
}> = [
  { id: 'overview', label: 'Aperçu', icon: 'grid' },
  { id: 'cashflow', label: 'Flux récurrents', icon: 'trend' },
  { id: 'recurring', label: 'Récurrents', icon: 'recurring' },
]

export function BudgetView({
  tab,
  focusId,
  accounts,
  categories,
  navigate,
  onRefresh,
}: {
  tab: BudgetTab
  focusId?: number
  accounts: Account[]
  categories: Category[]
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  return (
    <div className="view-stack">
      <nav className="module-tabs budget-tabs" aria-label="Budget et prévisions récurrentes">
        {budgetTabs.map((item) => (
          <button
            className={tab === item.id ? 'active' : ''}
            type="button"
            key={item.id}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => navigate({ name: 'budget', tab: item.id })}
          >
            <Icon name={item.icon} />
            <span className="budget-tab-label">{item.label}</span>
          </button>
        ))}
      </nav>

      {tab === 'overview' && (
        <BudgetOverviewPanel categories={categories} navigate={navigate} />
      )}
      {tab === 'cashflow' && <RecurringFlowPanel categories={categories} />}
      {tab === 'recurring' && (
        <RecurringPanel
          accounts={accounts}
          categories={categories}
          focusId={focusId}
          onRefresh={onRefresh}
        />
      )}
    </div>
  )
}

function BudgetOverviewPanel({
  categories,
  navigate,
}: {
  categories: Category[]
  navigate: (route: Route) => void
}) {
  const [anchorDate, setAnchorDate] = useState(localDateInputValue)
  const overview = useQuery({
    queryKey: ['budget-overview', anchorDate],
    queryFn: () => apiGet<BudgetOverview>(`/budget/overview${queryString({ on: anchorDate })}`),
  })
  const forecast = useQuery({
    queryKey: ['recurring-forecast', 2],
    queryFn: () => apiGet<RecurringForecastItem[]>('/recurring/forecast?months=2'),
  })
  const spending = useQuery({
    queryKey: ['budget-spending', anchorDate, 'cycle'],
    queryFn: () => apiGet<SpendingNode[]>(
      `/budget/spending${queryString({ on: anchorDate, period: 'cycle' })}`,
    ),
  })
  const recurringExpenses = (spending.data ?? [])
    .filter((node) => node.category_id !== null && Number(node.amount) > 0)
  const maximumRecurringExpense = Math.max(
    ...recurringExpenses.map((node) => Number(node.amount)),
    0,
  )

  return (
    <>
      <section className="period-toolbar">
        <p>Votre budget est calculé à partir des séries récurrentes actives.</p>
        <PeriodPicker value={anchorDate} onChange={setAnchorDate} />
      </section>
      {(overview.error || forecast.error || spending.error) && (
        <div className="error-banner">
          {errorMessage(overview.error ?? forecast.error ?? spending.error)}
        </div>
      )}
      <section className="metric-grid">
        <MetricCard
          label="Solde récurrent du cycle"
          value={signedMoney(overview.data?.net ?? 0)}
          detail={`${money(overview.data?.income)} entrées · ${money(overview.data?.expenses)} sorties`}
          tone={Number(overview.data?.net ?? 0) >= 0 ? 'positive' : 'negative'}
          icon="trend"
        />
        <MetricCard
          label="Dépenses prévues"
          value={money(overview.data?.expenses)}
          detail="Dépenses récurrentes du cycle"
          icon="budget"
        />
        <MetricCard
          label="Épargne du cycle"
          value={money(overview.data?.savings_contributions)}
          detail="Contributions enregistrées"
          icon="wealth"
        />
      </section>

      <section className="dashboard-grid">
        <Panel
          title="Dépenses récurrentes"
          subtitle="Répartition prévisionnelle par catégorie"
          action={(
            <button
              className="secondary-button small-button"
              type="button"
              onClick={() => navigate({ name: 'budget', tab: 'cashflow' })}
            >
              Voir les flux récurrents <Icon name="arrow" />
            </button>
          )}
        >
          {recurringExpenses.length > 0 ? (
            <div className="recurring-expense-summary-list">
              {recurringExpenses.map((node) => (
                <div key={`${node.category_id}-${node.category_name}`}>
                  <div>
                    <span>
                      <i style={{ background: categoryColor(node.category_id, categories) }} />
                      {node.category_name}
                    </span>
                    <strong>{money(node.amount)}</strong>
                  </div>
                  <ProgressBar
                    value={(Number(node.amount) / maximumRecurringExpense) * 100}
                    color={categoryColor(node.category_id, categories)}
                  />
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="budget"
              text="Ajoutez des dépenses récurrentes pour afficher leur répartition par catégorie."
            />
          )}
        </Panel>
        <Panel
          title="Prochaines échéances"
          subtitle="Revenus et prélèvements planifiés"
          action={(
            <button
              className="secondary-button small-button"
              type="button"
              onClick={() => navigate({ name: 'budget', tab: 'recurring' })}
            >
              Gérer les récurrents <Icon name="arrow" />
            </button>
          )}
        >
          <ForecastList items={(forecast.data ?? []).slice(0, 6)} />
        </Panel>
      </section>
    </>
  )
}

function RecurringFlowPanel({ categories }: { categories: Category[] }) {
  const [anchorDate, setAnchorDate] = useState(localDateInputValue)
  const [period, setPeriod] = useState<'cycle' | 'year'>('cycle')
  const cashflowMonths = 1
  const sourceFlows = useQuery({
    queryKey: ['budget-cashflow', 'projection', cashflowMonths, 'source'],
    queryFn: () => apiGet<CashflowFlow[]>(
      `/budget/cashflow${queryString({ months: cashflowMonths, by: 'source' })}`,
    ),
  })
  const categoryFlows = useQuery({
    queryKey: ['budget-cashflow', 'projection', cashflowMonths, 'category'],
    queryFn: () => apiGet<CashflowFlow[]>(
      `/budget/cashflow${queryString({ months: cashflowMonths, by: 'category' })}`,
    ),
  })
  const spending = useQuery({
    queryKey: ['budget-spending', anchorDate, period],
    queryFn: () => apiGet<SpendingNode[]>(
      `/budget/spending${queryString({ on: anchorDate, period })}`,
    ),
  })
  const income = (sourceFlows.data ?? []).reduce(
    (total, flow) => total + Number(flow.inflow),
    0,
  )
  const expenses = (categoryFlows.data ?? []).reduce(
    (total, flow) => total + Number(flow.outflow),
    0,
  )

  return (
    <>
      {(sourceFlows.error || categoryFlows.error || spending.error) && (
        <div className="error-banner">
          {errorMessage(sourceFlows.error ?? categoryFlows.error ?? spending.error)}
        </div>
      )}
      <Panel
        title="Flux récurrents"
        subtitle={`Entrées ${money(income)} · Sorties ${money(expenses)} · Solde ${signedMoney(income - expenses)}`}
        className="cashflow-panel"
        action={<StatusBadge tone="primary">1 mois</StatusBadge>}
      >
        <RecurringCashflowSankey
          categories={categories}
          categoryFlows={categoryFlows.data ?? []}
          sourceFlows={sourceFlows.data ?? []}
        />
      </Panel>
      <section className="period-toolbar">
        <p>Affinez la répartition calendaire des dépenses récurrentes.</p>
        <div className="period-actions">
          <PeriodPicker mode={period} value={anchorDate} onChange={setAnchorDate} />
          <div className="segmented-control compact-segments">
            <button
              className={period === 'cycle' ? 'active' : ''}
              type="button"
              onClick={() => setPeriod('cycle')}
            >
              Cycle
            </button>
            <button
              className={period === 'year' ? 'active' : ''}
              type="button"
              onClick={() => setPeriod('year')}
            >
              Année
            </button>
          </div>
        </div>
      </section>
      <Panel title="Dépenses récurrentes" subtitle="Répartition prévisionnelle par catégorie">
        <SpendingTree categories={categories} nodes={spending.data ?? []} />
      </Panel>
    </>
  )
}

function RecurringPanel({
  accounts,
  categories,
  focusId,
  onRefresh,
}: {
  accounts: Account[]
  categories: Category[]
  focusId?: number
  onRefresh: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [showCategoryCreate, setShowCategoryCreate] = useState(false)
  const [editing, setEditing] = useState<RecurringSeries | null>(null)
  const [forecastOpen, setForecastOpen] = useState(false)
  const [accountFilter, setAccountFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const series = useQuery({
    queryKey: ['recurring-series'],
    queryFn: () => apiGet<RecurringSeries[]>('/recurring'),
  })
  const forecast = useQuery({
    queryKey: ['recurring-forecast', 3],
    queryFn: () => apiGet<RecurringForecastItem[]>('/recurring/forecast?months=3'),
  })
  const recurringSeries = series.data ?? []
  const seriesAccountIds = new Set(recurringSeries.map((item) => item.account_id))
  const seriesCategoryIds = new Set(recurringSeries.map((item) => item.category_id))
  const filterAccounts = accounts
    .filter((account) => seriesAccountIds.has(account.id))
    .sort((left, right) => left.name.localeCompare(right.name, 'fr'))
  const filterCategories = categories
    .filter((category) => seriesCategoryIds.has(category.id))
    .sort((left, right) => left.name.localeCompare(right.name, 'fr'))
  const filterTypes = [...new Set(recurringSeries.map((item) => item.recurring_type))]
    .sort((left, right) => (
      recurringTypeLabel(left, null).localeCompare(recurringTypeLabel(right, null), 'fr')
    ))
  const visibleSeries = recurringSeries.filter((item) => (
    (accountFilter === 'all' || item.account_id === Number(accountFilter))
    && (typeFilter === 'all' || item.recurring_type === typeFilter)
    && (
      categoryFilter === 'all'
      || (categoryFilter === 'none' ? item.category_id === null : item.category_id === Number(categoryFilter))
    )
  ))
  const filtersActive = accountFilter !== 'all' || typeFilter !== 'all' || categoryFilter !== 'all'
  useLinkedEntityFocus('recurring', focusId, (series.data?.length ?? 0) > 0)
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['recurring-series'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-forecast'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-cashflow'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-spending'] }),
      queryClient.invalidateQueries({ queryKey: ['overview'] }),
      queryClient.invalidateQueries({ queryKey: ['monthly-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
      onRefresh(),
    ])
  }

  return (
    <>
      <section className="section-intro">
        <p>Configurez manuellement les revenus et dépenses qui composent votre budget.</p>
        <div className="section-intro-actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => setShowCategoryCreate(true)}
          >
            <Icon name="plus" />Ajouter une catégorie
          </button>
          <button className="primary-button" type="button" onClick={() => setShowCreate(true)}>
            <Icon name="plus" />Ajouter une série
          </button>
        </div>
      </section>
      {(series.error || forecast.error) && (
        <div className="error-banner">{errorMessage(series.error ?? forecast.error)}</div>
      )}
      {(showCreate || editing) && (
        <RecurringSeriesModal
          accounts={accounts}
          categories={categories}
          item={editing ?? undefined}
          onClose={() => {
            setShowCreate(false)
            setEditing(null)
          }}
          onSaved={async () => {
            await refresh()
            setShowCreate(false)
            setEditing(null)
          }}
        />
      )}
      {showCategoryCreate && (
        <CategoryModal
          categories={categories}
          onClose={() => setShowCategoryCreate(false)}
          onSaved={async () => {
            await refresh()
            setShowCategoryCreate(false)
          }}
        />
      )}
      <Panel
        className={`forecast-drawer${forecastOpen ? '' : ' collapsed'}`}
        title="Prochaines échéances"
        subtitle="Projection sur trois mois"
        action={(
          <button
            aria-controls="recurring-forecast-drawer"
            aria-expanded={forecastOpen}
            aria-label={forecastOpen ? 'Masquer les prochaines échéances' : 'Afficher les prochaines échéances'}
            className="icon-action forecast-drawer-toggle"
            type="button"
            onClick={() => setForecastOpen((current) => !current)}
          >
            <Icon name="arrow" />
          </button>
        )}
      >
        {forecastOpen && (
          <div id="recurring-forecast-drawer">
            <ForecastByMonth items={forecast.data ?? []} />
          </div>
        )}
      </Panel>
      <Panel
        title="Séries récurrentes"
        subtitle={
          `${recurringSeries.length} série${recurringSeries.length === 1 ? '' : 's'} configurée${recurringSeries.length === 1 ? '' : 's'}`
          + (filtersActive ? ` · ${visibleSeries.length} affichée${visibleSeries.length === 1 ? '' : 's'}` : '')
        }
      >
        {recurringSeries.length > 0 ? (
          <>
            <div className="filter-row recurring-filters">
              <FormSelect
                aria-label="Filtrer les séries récurrentes par compte"
                value={accountFilter}
                onChange={(event) => setAccountFilter(event.target.value)}
              >
                <option value="all">Tous les comptes</option>
                {filterAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}{account.archived ? ' (archivé)' : ''}
                  </option>
                ))}
              </FormSelect>
              <FormSelect
                aria-label="Filtrer les séries récurrentes par type"
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value)}
              >
                <option value="all">Tous les types</option>
                {filterTypes.map((type) => (
                  <option key={type} value={type}>{recurringTypeLabel(type, null)}</option>
                ))}
              </FormSelect>
              <FormSelect
                aria-label="Filtrer les séries récurrentes par catégorie"
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
              >
                <option value="all">Toutes les catégories</option>
                {seriesCategoryIds.has(null) && <option value="none">Sans catégorie</option>}
                {filterCategories.map((category) => (
                  <option key={category.id} value={category.id}>{category.name}</option>
                ))}
              </FormSelect>
            </div>
            {visibleSeries.length > 0 ? (
              <div className="recurring-list">
                {visibleSeries.map((item) => (
                  <RecurringRow
                    account={accounts.find((account) => account.id === item.account_id)}
                    focused={item.id === focusId}
                    item={item}
                    key={item.id}
                    onEdit={() => setEditing(item)}
                    onSaved={refresh}
                  />
                ))}
              </div>
            ) : (
              <EmptyState icon="recurring" text="Aucune série ne correspond à ces filtres." />
            )}
          </>
        ) : (
          <EmptyState icon="recurring" text="Ajoutez une série pour construire votre budget." />
        )}
      </Panel>
    </>
  )
}

function RecurringRow({
  account,
  focused,
  item,
  onEdit,
  onSaved,
}: {
  account?: Account
  focused: boolean
  item: RecurringSeries
  onEdit: () => void
  onSaved: () => Promise<void>
}) {
  const accountArchived = account?.archived ?? false
  const accountShared = (account?.owner_profile_ids?.length ?? 0) > 1
  const profileAmount = item.profile_share ?? item.amount
  const totalAmount = item.total_amount ?? item.amount
  const [showAttachments, setShowAttachments] = useState(false)
  const update = useMutation({
    mutationFn: (status: RecurringSeries['status']) =>
      apiPatch<RecurringSeries>(`/recurring/${item.id}`, { status }),
    onSuccess: onSaved,
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/recurring/${item.id}`),
    onSuccess: onSaved,
  })

  return (
    <article
      className={focused ? 'linked-entity-target' : undefined}
      id={linkedEntityTargetId('recurring', item.id)}
      tabIndex={focused ? -1 : undefined}
    >
      <span className="recurring-copy">
        <span>
          <strong>{item.label}</strong>
          <StatusBadge tone={statusTone(item.status)}>{statusLabel(item.status)}</StatusBadge>
          <StatusBadge>{recurringTypeLabel(item.recurring_type, item.custom_type)}</StatusBadge>
          {item.amount_type === 'variable' && <StatusBadge>Estimation</StatusBadge>}
        </span>
        <small>
          {item.account_name} · {item.category_name ?? 'Sans catégorie'} ·{' '}
          {frequencyLabel(item.frequency)}
        </small>
        <small>Prochaine échéance le {formatDate(item.next_due)}</small>
      </span>
      <span className="recurring-amount-summary">
        {accountShared && <small>Votre part</small>}
        <strong className={Number(profileAmount ?? 0) >= 0 ? 'positive' : 'negative'}>
          {signedMoney(profileAmount ?? 0)}
        </strong>
        {accountShared && <small>Total : {signedMoney(totalAmount ?? 0)}</small>}
      </span>
      <div className="row-actions">
        {(!accountArchived || item.attachment_count > 0) && (
          <button
            className="icon-action attachment-button"
            type="button"
            aria-label={`Pièces jointes${item.attachment_count > 0 ? ` (${item.attachment_count})` : ''}`}
            aria-expanded={showAttachments}
            onClick={() => setShowAttachments((current) => !current)}
          >
            <Icon name="attachment" />
            {item.attachment_count > 0 && (
              <span className="attachment-count-badge">{item.attachment_count}</span>
            )}
          </button>
        )}
        {!accountArchived && (
          <>
            <button className="icon-action" type="button" aria-label="Modifier" onClick={onEdit}>
              <Icon name="edit" />
            </button>
            <button
              className="icon-action"
              type="button"
              aria-label={item.status === 'active' ? 'Mettre en pause' : 'Réactiver'}
              onClick={() => update.mutate(item.status === 'active' ? 'paused' : 'active')}
            >
              <Icon name={item.status === 'active' ? 'close' : 'check'} />
            </button>
            <button
              className="icon-action destructive-button"
              type="button"
              aria-label="Supprimer"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm('Supprimer cette série récurrente ?')) remove.mutate()
              }}
            >
              <Icon name="trash" />
            </button>
          </>
        )}
      </div>
      {(update.error || remove.error) && (
        <span className="form-error row-error">{errorMessage(update.error ?? remove.error)}</span>
      )}
      {showAttachments && (
        <div className="entity-attachment-panel">
          <AttachmentManager
            owner={{ kind: 'recurring', seriesId: item.id }}
            readOnly={accountArchived}
          />
        </div>
      )}
    </article>
  )
}

function RecurringSeriesModal({
  accounts,
  categories,
  item,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  categories: Category[]
  item?: RecurringSeries
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const selectableAccounts = accounts.filter(
    (account) => !account.archived || account.id === item?.account_id,
  )
  const [label, setLabel] = useState(item?.label ?? '')
  const [accountId, setAccountId] = useState(String(item?.account_id ?? selectableAccounts[0]?.id ?? ''))
  const [categoryId, setCategoryId] = useState(String(item?.category_id ?? ''))
  const itemTotalAmount = item?.total_amount ?? item?.amount
  const [direction, setDirection] = useState<AmountDirection>(
    item && Number(itemTotalAmount ?? 0) >= 0 ? 'deposit' : 'withdrawal',
  )
  const [amount, setAmount] = useState(
    itemTotalAmount ? String(Math.abs(Number(itemTotalAmount))) : '',
  )
  const [frequency, setFrequency] = useState<RecurringSeries['frequency']>(item?.frequency ?? 'monthly')
  const [nextDue, setNextDue] = useState(
    monthInputValue(item?.next_due ?? localDateInputValue()),
  )
  const [variable, setVariable] = useState(item?.amount_type === 'variable')
  const [recurringType, setRecurringType] = useState<RecurringType>(
    item?.recurring_type ?? 'subscription',
  )
  const [customType, setCustomType] = useState(item?.custom_type ?? '')
  const [insuranceRate, setInsuranceRate] = useState(item?.credit_insurance_rate ?? '')
  const [attachment, setAttachment] = useState<File | null>(null)
  const createdItemId = useRef<number | null>(null)
  const selectedAccount = selectableAccounts.find((account) => account.id === Number(accountId))
  const sharedProfileCount = selectedAccount?.owner_profile_ids?.length ?? 1
  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        label,
        account_id: Number(accountId),
        category_id: categoryId ? Number(categoryId) : null,
        amount: directedAmount(amount, direction),
        frequency,
        next_due: monthBoundaryDate(nextDue),
        amount_type: variable ? 'variable' : 'fixed',
        status: item?.status ?? 'active',
        recurring_type: recurringType,
        custom_type: recurringType === 'other' ? customType : null,
        credit_insurance_rate: recurringType === 'credit_insurance'
          ? insuranceRate || null
          : null,
      }
      const existingId = item?.id ?? createdItemId.current
      const savedItem = await (existingId
        ? apiPatch<RecurringSeries>(`/recurring/${existingId}`, payload)
        : apiPost<RecurringSeries>('/recurring', payload))
      createdItemId.current = savedItem.id
      if (!item && attachment) {
        await uploadOwnerAttachment({ kind: 'recurring', seriesId: savedItem.id }, attachment)
      }
      return savedItem
    },
    onSuccess: onSaved,
  })
  const formId = item ? `recurring-edit-${item.id}` : 'recurring-create'

  return (
    <Modal
      title={item ? 'Modifier la série' : 'Nouvelle série récurrente'}
      description="Cette série alimentera directement les indicateurs et graphiques budgétaires."
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button
            className="primary-button"
            type="submit"
            form={formId}
            disabled={mutation.isPending || !accountId}
          >
            {mutation.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </>
      )}
    >
      <form
        className="modal-form"
        id={formId}
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <AmountDirectionToggle value={direction} onChange={setDirection} />
        <Field label="Nom">
          <FormInput value={label} onChange={(event) => setLabel(event.target.value)} required />
        </Field>
        <Field label="Type">
          <FormSelect
            value={recurringType}
            onChange={(event) => setRecurringType(event.target.value as RecurringType)}
          >
            <option value="subscription">Abonnement</option>
            <option value="rent">Loyer</option>
            <option value="energy">Énergie</option>
            <option value="telecom">Télécom</option>
            <option value="auto_insurance">Assurance auto</option>
            <option value="home_insurance">Assurance habitation</option>
            <option value="health_insurance">Assurance santé</option>
            <option value="credit_insurance">Assurance crédit</option>
            <option value="loan_payment">Remboursement de crédit</option>
            <option value="tax">Impôt ou taxe</option>
            <option value="salary">Salaire ou revenu</option>
            <option value="transfer">Virement entre comptes</option>
            <option value="other">Autre</option>
            {item?.recurring_type === 'uncategorized' && (
              <option value="uncategorized">Non classé</option>
            )}
          </FormSelect>
        </Field>
        {recurringType === 'other' && (
          <Field label="Type personnalisé">
            <FormInput value={customType} onChange={(event) => setCustomType(event.target.value)} required />
          </Field>
        )}
        {recurringType === 'credit_insurance' && (
          <Field label="Taux d’assurance (%)">
            <FormInput
              type="number"
              min="0"
              max="100"
              step="0.001"
              value={insuranceRate}
              onChange={(event) => setInsuranceRate(event.target.value)}
            />
          </Field>
        )}
        <Field label="Compte">
          <FormSelect value={accountId} onChange={(event) => setAccountId(event.target.value)} required>
            {selectableAccounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Catégorie">
          <FormSelect value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Sans catégorie</option>
            {categories.filter((category) => !category.archived).map((category) => (
              <option key={category.id} value={category.id}>{category.name}</option>
            ))}
          </FormSelect>
        </Field>
        <Field
          label={variable ? 'Montant total estimé' : 'Montant total'}
          hint={sharedProfileCount > 1
            ? `Votre part sera calculée automatiquement entre les ${sharedProfileCount} profils du compte.`
            : undefined}
        >
          <FormInput
            type="number"
            min="0.01"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            required
          />
        </Field>
        <Field label="Fréquence">
          <FormSelect
            value={frequency}
            onChange={(event) => setFrequency(event.target.value as RecurringSeries['frequency'])}
          >
            <option value="weekly">Hebdomadaire</option>
            <option value="monthly">Mensuelle</option>
            <option value="quarterly">Trimestrielle</option>
            <option value="yearly">Annuelle</option>
          </FormSelect>
        </Field>
        <Field label="Mois de la prochaine échéance">
          <DatePicker
            value={nextDue}
            onChange={(event) => setNextDue(event.target.value)}
            required
          />
        </Field>
        <label className="toggle-row recurring-variable-toggle">
          <span>
            <strong>Montant variable</strong>
            <small>Utiliser ce montant comme estimation budgétaire.</small>
          </span>
          <FormInput
            type="checkbox"
            checked={variable}
            onChange={(event) => setVariable(event.target.checked)}
          />
          <span className="toggle-visual" aria-hidden="true"><Icon name="check" /></span>
        </label>
        <div className="modal-attachment-field">
          {item ? (
            <AttachmentManager
              owner={{ kind: 'recurring', seriesId: item.id }}
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

function CategoryModal({
  categories,
  onClose,
  onSaved,
}: {
  categories: Category[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Category['kind']>('expense')
  const [color, setColor] = useState('#615fff')
  const [budget, setBudget] = useState('')
  const [parentId, setParentId] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Category>('/categories', {
      name,
      kind,
      color,
      monthly_budget: kind === 'expense' && budget !== '' ? budget : null,
      parent_id: parentId ? Number(parentId) : null,
    }),
    onSuccess: onSaved,
  })
  const parents = categories.filter(
    (candidate) =>
      !candidate.archived
      && candidate.kind === kind
      && candidate.parent_id === null,
  )
  const formId = 'category-create'

  return (
    <Modal
      title="Nouvelle catégorie"
      description="Cette catégorie permet d’organiser les séries récurrentes."
      onClose={onClose}
      actions={(
        <>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending}>
            Enregistrer
          </button>
        </>
      )}
    >
      <form
        className="modal-form"
        id={formId}
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <Field label="Nom">
          <FormInput value={name} onChange={(event) => setName(event.target.value)} required />
        </Field>
        <Field label="Type">
          <FormSelect value={kind} onChange={(event) => setKind(event.target.value as Category['kind'])}>
            <option value="expense">Dépense</option>
            <option value="income">Revenu</option>
          </FormSelect>
        </Field>
        <Field label="Couleur">
          <FormInput type="color" value={color} onChange={(event) => setColor(event.target.value)} />
        </Field>
        <Field label="Catégorie parente">
          <FormSelect value={parentId} onChange={(event) => setParentId(event.target.value)}>
            <option value="">Aucune</option>
            {parents.map((parent) => (
              <option key={parent.id} value={parent.id}>{parent.name}</option>
            ))}
          </FormSelect>
        </Field>
        {kind === 'expense' && (
          <Field label="Plafond mensuel">
            <FormInput
              type="number"
              min="0"
              step="0.01"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              placeholder="Sans plafond"
            />
          </Field>
        )}
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function SpendingTree({
  categories,
  nodes,
}: {
  categories: Category[]
  nodes: SpendingNode[]
}) {
  const flattened = flattenSpending(nodes)
  const maximum = Math.max(...flattened.map((node) => Number(node.amount)), 0)
  if (flattened.length === 0 || maximum === 0) {
    return <EmptyState icon="budget" text="Aucune dépense récurrente sur cette période." />
  }
  return (
    <div className="spending-tree">
      {nodes.filter((node) => Number(node.amount) > 0).map((node) => (
        <SpendingNodeRow
          categories={categories}
          key={`${node.category_id}-${node.category_name}`}
          maximum={maximum}
          node={node}
        />
      ))}
    </div>
  )
}

function SpendingNodeRow({
  categories,
  maximum,
  node,
}: {
  categories: Category[]
  maximum: number
  node: SpendingNode
}) {
  const children = (node.children ?? []).filter((child) => Number(child.amount) > 0)
  return (
    <div className="spending-node">
      <div className="spending-label">
        <span>
          <strong>{node.category_name}</strong>
          <small>{node.occurrence_count} échéance{node.occurrence_count === 1 ? '' : 's'}</small>
        </span>
        <strong>{money(node.amount)}</strong>
      </div>
      <ProgressBar
        value={(Number(node.amount) / maximum) * 100}
        color={categoryColor(node.category_id, categories)}
      />
      {children.length > 0 && (
        <div className="spending-children">
          {children.map((child) => (
            <SpendingNodeRow
              categories={categories}
              key={`${child.category_id}-${child.category_name}`}
              maximum={maximum}
              node={child}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function flattenSpending(nodes: SpendingNode[]): SpendingNode[] {
  return nodes.flatMap((node) => [node, ...flattenSpending(node.children ?? [])])
}

function ForecastByMonth({ items }: { items: RecurringForecastItem[] }) {
  const groups = Object.entries(
    items.reduce<Record<string, RecurringForecastItem[]>>((result, item) => {
      const month = item.due_date.slice(0, 7)
      result[month] = [...(result[month] ?? []), item]
      return result
    }, {}),
  ).sort(([left], [right]) => left.localeCompare(right))
  if (groups.length === 0) {
    return <EmptyState icon="calendar" text="Aucune échéance prévue." />
  }
  return (
    <div className="forecast-groups">
      {groups.map(([month, entries]) => (
        <div key={month}>
          <strong>{formatMonth(month)}</strong>
          <ForecastList items={entries} />
        </div>
      ))}
    </div>
  )
}

function ForecastList({ items }: { items: RecurringForecastItem[] }) {
  if (items.length === 0) return <EmptyState icon="calendar" text="Aucune échéance prévue." />
  return (
    <div className="forecast-list">
      {items.map((item) => (
        <div key={`${item.series_id}-${item.due_date}`}>
          <span className="forecast-item-copy">
            <strong>{item.label}</strong>
            <small>{formatDate(item.due_date)} · {item.category_name ?? item.account_name}</small>
          </span>
          <strong className={Number(item.amount) >= 0 ? 'positive' : 'negative'}>
            {signedMoney(item.amount)}
          </strong>
        </div>
      ))}
    </div>
  )
}

type PeriodPickerMode = 'cycle' | 'year'

function PeriodPicker({
  value,
  onChange,
  mode = 'cycle',
}: {
  value: string
  onChange: (value: string) => void
  mode?: PeriodPickerMode
}) {
  const date = new Date(`${value}T12:00:00`)
  const label = mode === 'year'
    ? String(date.getFullYear())
    : date.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })
  return (
    <div className="period-picker">
      <button
        className="icon-action"
        type="button"
        aria-label="Période précédente"
        onClick={() => onChange(shiftPeriodDate(value, -1, mode))}
      >
        <Icon name="back" />
      </button>
      <strong>{label}</strong>
      <button
        className="icon-action"
        type="button"
        aria-label="Période suivante"
        onClick={() => onChange(shiftPeriodDate(value, 1, mode))}
      >
        <Icon name="arrow" />
      </button>
    </div>
  )
}

function shiftPeriodDate(value: string, delta: number, mode: PeriodPickerMode): string {
  const date = new Date(`${value}T12:00:00`)
  if (mode === 'year') date.setFullYear(date.getFullYear() + delta)
  else date.setMonth(date.getMonth() + delta)
  const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return adjusted.toISOString().slice(0, 10)
}

function categoryColor(categoryId: number | null, categories: Category[]): string {
  return categories.find((category) => category.id === categoryId)?.color ?? '#85858c'
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
  return {
    weekly: 'Hebdomadaire',
    monthly: 'Mensuel',
    quarterly: 'Trimestriel',
    yearly: 'Annuel',
  }[frequency]
}

function recurringTypeLabel(type: RecurringType, customType: string | null): string {
  const labels: Record<Exclude<RecurringType, 'other'>, string> = {
    uncategorized: 'Non classé',
    subscription: 'Abonnement',
    rent: 'Loyer',
    energy: 'Énergie',
    telecom: 'Télécom',
    auto_insurance: 'Assurance auto',
    home_insurance: 'Assurance habitation',
    health_insurance: 'Assurance santé',
    credit_insurance: 'Assurance crédit',
    loan_payment: 'Remboursement de crédit',
    tax: 'Impôt ou taxe',
    salary: 'Salaire ou revenu',
    transfer: 'Virement entre comptes',
  }
  return type === 'other' ? customType || 'Autre' : labels[type]
}
