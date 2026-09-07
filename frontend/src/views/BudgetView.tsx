import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  Sankey,
  Tooltip,
} from 'recharts'

import { apiDelete, apiGet, apiPatch, apiPost, apiUpload, queryString } from '../api/client'
import { AttachmentManager } from '../AttachmentManager'
import { useOnlineStatus } from '../pwa'
import type {
  Account,
  AppSettings,
  BudgetOverview,
  CashflowFlow,
  CategorizationInboxItem,
  CategorizationRule,
  CategorizationSuggestion,
  Category,
  CategoryRemovalResult,
  Envelope,
  MerchantIdentity,
  RecurringChange,
  RecurringDetectionProposal,
  RecurringDetectionResult,
  RecurringForecastItem,
  RecurringSeries,
  SpendingNode,
  Transaction,
  TransactionCount,
} from '../api/types'
import type { BudgetTab, Route } from '../routing'
import {
  AmountDirectionToggle,
  CategorizationSummary,
  EmptyState,
  Field,
  FormInput,
  FormSelect,
  FormTextarea,
  Icon,
  MerchantAvatar,
  MetricCard,
  Modal,
  Panel,
  ProgressBar,
  StatusBadge,
  directedAmount,
  errorMessage,
  formatDate,
  formatMonth,
  initials,
  localDateInputValue,
  money,
  shortMonth,
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
  const isOnline = useOnlineStatus()
  const archivedAccountIds = new Set(accounts.filter((account) => account.archived).map((account) => account.id))
  const uncategorizedCount = isOnline ? transactions.filter(
    (transaction) =>
      transaction.category_id === null &&
      transaction.transfer_group === null &&
      !archivedAccountIds.has(transaction.account_id),
  ).length : 0

  return (
    <div className="view-stack">
      <nav className="module-tabs budget-tabs" aria-label="Budget et cashflow">
        {budgetTabs.map((item) => (
          <button
            className={tab === item.id ? 'active' : ''}
            type="button"
            key={item.id}
            aria-current={tab === item.id ? 'page' : undefined}
            aria-label={item.id === 'categorize' ? `${item.label} (${uncategorizedCount})` : item.label}
            title={item.label}
            onClick={() => navigate({ name: 'budget', tab: item.id })}
          >
            <Icon name={item.icon} />
            <span className="budget-tab-label">{item.label}</span>
            {item.id === 'categorize' && uncategorizedCount > 0 && (
              <span className="nav-count">{uncategorizedCount}</span>
            )}
          </button>
        ))}
      </nav>

      {tab === 'overview' && <BudgetOverviewPanel navigate={navigate} />}
      {tab === 'cashflow' && <CashflowPanel categories={categories} />}
      {tab === 'recurring' && <RecurringPanel accounts={accounts} categories={categories} />}
      {tab === 'envelopes' && <EnvelopesPanel categories={categories} onRefresh={onRefresh} />}
      {tab === 'categorize' && (
        isOnline ? (
          <CategorizationPanel
            categories={categories}
            merchants={merchants}
            settings={settings}
            onRefresh={onRefresh}
          />
        ) : <OfflineTransactionPanel />
      )}
      {tab === 'transactions' && (
        isOnline
          ? <TransactionLedger accounts={accounts} categories={categories} onRefresh={onRefresh} />
          : <OfflineTransactionPanel />
      )}
    </div>
  )
}

function OfflineTransactionPanel() {
  return (
    <Panel title="Transactions" subtitle="Registre disponible avec une connexion à l'instance">
      <EmptyState
        icon="receipt"
        title="Liste non conservée hors ligne"
        text="Les tuiles budgétaires, enveloppes et graphiques de cashflow restent disponibles."
      />
    </Panel>
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
    .filter((envelope) => envelope.budget !== null)
    .sort((left, right) => envelopeReadRatio(right) - envelopeReadRatio(left))
    .slice(0, 5)

  return (
    <>
      <section className="period-toolbar">
        <p>Vue synthétique de votre mois budgétaire.</p>
        <PeriodPicker value={anchorDate} onChange={setAnchorDate} />
      </section>
      {(overview.error || forecast.error || envelopes.error) && (
        <div className="error-banner">{errorMessage(overview.error ?? forecast.error ?? envelopes.error)}</div>
      )}
      <section className="metric-grid">
        <MetricCard label="Solde net du mois" value={signedMoney(overview.data?.net ?? 0)} detail={`${money(overview.data?.income)} entrées · ${money(overview.data?.expenses)} sorties`} tone={Number(overview.data?.net ?? 0) >= 0 ? 'positive' : 'negative'} icon="trend" />
        <MetricCard
          label="Enveloppes"
          value={money(overview.data?.envelope_spent ?? Number(overview.data?.budget_total ?? 0) - Number(overview.data?.budget_remaining ?? 0))}
          detail={`sur ${money(overview.data?.budget_total)}`}
          icon="budget"
        />
        <MetricCard
          label="À venir"
          value={signedMoney(overview.data?.upcoming_recurring_amount ?? 0)}
          detail={`${overview.data?.upcoming_recurring_count ?? 0} échéance${overview.data?.upcoming_recurring_count === 1 ? '' : 's'}`}
          icon="calendar"
        />
        <MetricCard label="Épargne du mois" value={money(overview.data?.savings_contributions)} detail="Contributions enregistrées" icon="wealth" />
      </section>

      {(overview.data?.uncategorized_count ?? 0) > 0 && (
        <CategorizationSummary
          detail={`${overview.data?.uncategorized_count ?? 0} mouvement${overview.data?.uncategorized_count === 1 ? '' : 's'} sans catégorie ce mois-ci`}
          onCategorize={() => navigate({ name: 'budget', tab: 'categorize' })}
        />
      )}

      <section className="dashboard-grid">
        <Panel title="Enveloppes les plus sollicitées" subtitle="Consommation du mois">
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
            <EmptyState icon="budget" text="Ajoutez un plafond à une enveloppe pour comparer dépenses et budget." />
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
    () => buildSankey(sourceFlows.data ?? [], categoryFlows.data ?? [], categories),
    [categories, categoryFlows.data, sourceFlows.data],
  )
  const income = (sourceFlows.data ?? []).reduce((total, flow) => total + Number(flow.inflow), 0)
  const expenses = (categoryFlows.data ?? []).reduce((total, flow) => total + Number(flow.outflow), 0)

  return (
    <>
      <section className="period-toolbar">
        <p>Visualisez comment circule votre argent.</p>
        <div className="period-actions">
          <PeriodPicker mode={period} value={anchorDate} onChange={setAnchorDate} />
          <div className="segmented-control compact-segments">
            <button className={period === 'cycle' ? 'active' : ''} type="button" onClick={() => setPeriod('cycle')}>Mois</button>
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
                link={CashflowSankeyLink}
                nodePadding={28}
                nodeWidth={12}
                node={CashflowSankeyNode}
                linkCurvature={0.52}
                iterations={32}
                margin={{ top: 20, right: 120, bottom: 20, left: 90 }}
              >
                <Tooltip content={<CashflowTooltip />} />
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
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [seriesToEdit, setSeriesToEdit] = useState<RecurringSeries | null>(null)
  const [showDetectionModal, setShowDetectionModal] = useState(false)
  const [detectionProposals, setDetectionProposals] = useState<RecurringDetectionProposal[]>([])
  const [selectedProposalKeys, setSelectedProposalKeys] = useState<string[]>([])
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
  const refreshRecurring = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['recurring-series'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-changes'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-forecast'] }),
      queryClient.invalidateQueries({ queryKey: ['budget-overview'] }),
    ])
  }
  const previewDetection = useMutation({
    mutationFn: () => apiGet<RecurringDetectionProposal[]>('/recurring/detect'),
    onSuccess: (proposals) => {
      setDetectionProposals(proposals)
      setSelectedProposalKeys(proposals.map((proposal) => proposal.proposal_key))
      setShowDetectionModal(true)
    },
  })
  const confirmDetection = useMutation({
    mutationFn: (proposalKeys: string[]) =>
      apiPost<RecurringDetectionResult>('/recurring/detect', { proposal_keys: proposalKeys }),
    onSuccess: async () => {
      await refreshRecurring()
      setShowDetectionModal(false)
    },
  })
  const errors = [series.error, forecast.error, changes.error].filter(Boolean)

  return (
    <>
      <section className="section-intro">
        <p>Abonnements, revenus et prélèvements récurrents.</p>
        <div className="header-actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              confirmDetection.reset()
              previewDetection.mutate()
            }}
            disabled={previewDetection.isPending}
          >
            <Icon name="refresh" />{previewDetection.isPending ? 'Détection…' : 'Détecter'}
          </button>
          <button className="primary-button" type="button" onClick={() => setShowCreateModal(true)}>
            <Icon name="plus" />Ajouter une série
          </button>
        </div>
      </section>
      {showCreateModal && (
        <RecurringSeriesModal
          accounts={accounts}
          categories={categories}
          onClose={() => setShowCreateModal(false)}
          onSaved={async () => {
            await refreshRecurring()
            setShowCreateModal(false)
          }}
        />
      )}
      {seriesToEdit && (
        <RecurringSeriesModal
          accounts={accounts}
          categories={categories}
          item={seriesToEdit}
          key={seriesToEdit.id}
          onClose={() => setSeriesToEdit(null)}
          onSaved={async () => {
            await refreshRecurring()
            setSeriesToEdit(null)
          }}
        />
      )}
      {showDetectionModal && (
        <RecurringDetectionModal
          error={confirmDetection.error}
          isPending={confirmDetection.isPending}
          proposals={detectionProposals}
          selectedKeys={selectedProposalKeys}
          onClose={() => {
            confirmDetection.reset()
            setShowDetectionModal(false)
          }}
          onConfirm={() => confirmDetection.mutate(selectedProposalKeys)}
          onToggle={(proposalKey) => {
            setSelectedProposalKeys((current) => (
              current.includes(proposalKey)
                ? current.filter((key) => key !== proposalKey)
                : [...current, proposalKey]
            ))
          }}
        />
      )}
      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}
      {previewDetection.error && <div className="error-banner">{errorMessage(previewDetection.error)}</div>}
      <RecurringChanges changes={changes.data ?? []} series={series.data ?? []} onSaved={refreshRecurring} />
      <Panel title="Prochaines échéances" subtitle="Projection sur trois mois">
        <ForecastByMonth items={forecast.data ?? []} />
      </Panel>
      <Panel title="Séries récurrentes" subtitle={`${series.data?.length ?? 0} série${series.data?.length === 1 ? '' : 's'} configurée${series.data?.length === 1 ? '' : 's'}`}>
        {(series.data ?? []).length > 0 ? (
          <div className="recurring-list">
            {series.data?.map((item) => (
              <RecurringRow
                item={item}
                key={item.id}
                onEdit={() => setSeriesToEdit(item)}
                onSaved={refreshRecurring}
              />
            ))}
          </div>
        ) : (
          <EmptyState icon="recurring" text="Ajoutez une série ou lancez la détection sur l'historique." />
        )}
      </Panel>
    </>
  )
}

function RecurringChanges({
  changes,
  series,
  onSaved,
}: {
  changes: RecurringChange[]
  series: RecurringSeries[]
  onSaved: () => Promise<void>
}) {
  const pending = changes.filter((change) => change.status === 'pending')
  const action = useMutation({
    mutationFn: ({ id, status }: { id: number; status: 'accepted' | 'rejected' }) =>
      apiPost<RecurringChange>(`/recurring/changes/${id}/action${queryString({ action: status === 'accepted' ? 'accept' : 'reject' })}`),
    onSuccess: onSaved,
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

function RecurringRow({
  item,
  onEdit,
  onSaved,
}: {
  item: RecurringSeries
  onEdit: () => void
  onSaved: () => Promise<void>
}) {
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
        <button className="icon-action" type="button" aria-label="Modifier" onClick={onEdit}>
          <Icon name="edit" />
        </button>
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
  const selectableAccounts = accounts.filter((account) => !account.archived || account.id === item?.account_id)
  const [name, setName] = useState(item?.label ?? '')
  const [accountId, setAccountId] = useState(String(item?.account_id ?? selectableAccounts[0]?.id ?? ''))
  const [categoryId, setCategoryId] = useState(String(item?.category_id ?? ''))
  const [direction, setDirection] = useState<TransactionDirection>(
    Number(item?.amount ?? 0) >= 0 ? 'deposit' : 'withdrawal',
  )
  const [amount, setAmount] = useState(item?.amount ? String(Math.abs(Number(item.amount))) : '')
  const [frequency, setFrequency] = useState<RecurringSeries['frequency']>(item?.frequency ?? 'monthly')
  const [nextDueDate, setNextDueDate] = useState(item?.next_due ?? localDateInputValue())
  const [variable, setVariable] = useState(item?.amount_type === 'variable')
  const [status, setStatus] = useState<RecurringSeries['status']>(item?.status ?? 'active')
  const selectedAccountId = accountId || String(selectableAccounts[0]?.id ?? '')
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        label: name,
        account_id: Number(selectedAccountId),
        category_id: categoryId ? Number(categoryId) : null,
        amount: directedAmount(amount, direction),
        frequency,
        next_due: nextDueDate,
        amount_type: variable ? 'variable' : 'fixed',
        status,
      }
      return item
        ? apiPatch<RecurringSeries>(`/recurring/${item.id}`, payload)
        : apiPost<RecurringSeries>('/recurring', {
          ...payload,
          confidence: 1,
        })
    },
    onSuccess: onSaved,
  })
  const formId = item ? `recurring-series-edit-${item.id}` : 'recurring-series-create'
  return (
    <Modal
      title={item ? 'Modifier la série récurrente' : 'Nouvelle série récurrente'}
      description={item ? 'Mettez à jour les paramètres de cette série.' : 'Ajoutez une échéance répétée à votre prévision.'}
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending || !selectedAccountId}>
            {mutation.isPending ? 'Enregistrement…' : item ? 'Enregistrer' : 'Créer la série'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <AmountDirectionToggle value={direction} onChange={setDirection} />
        <Field label="Nom"><FormInput value={name} onChange={(event) => setName(event.target.value)} required /></Field>
        <Field label="Compte">
          <FormSelect value={selectedAccountId} onChange={(event) => setAccountId(event.target.value)} required>
            {selectableAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </FormSelect>
        </Field>
        <Field label="Catégorie">
          <FormSelect value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Sans catégorie</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </FormSelect>
        </Field>
        <Field label={variable ? 'Montant estimé' : 'Montant'}>
          <FormInput type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        </Field>
        <Field label="Fréquence">
          <FormSelect value={frequency} onChange={(event) => setFrequency(event.target.value as RecurringSeries['frequency'])}>
            <option value="weekly">Hebdomadaire</option>
            <option value="monthly">Mensuelle</option>
            <option value="quarterly">Trimestrielle</option>
            <option value="yearly">Annuelle</option>
          </FormSelect>
        </Field>
        <Field label="Prochaine échéance"><FormInput type="date" value={nextDueDate} onChange={(event) => setNextDueDate(event.target.value)} required /></Field>
        {item && (
          <Field label="Statut">
            <FormSelect value={status} onChange={(event) => setStatus(event.target.value as RecurringSeries['status'])}>
              <option value="active">Active</option>
              <option value="paused">En pause</option>
              <option value="ended">Terminée</option>
            </FormSelect>
          </Field>
        )}
        <label className="toggle-row recurring-variable-toggle">
          <span>
            <strong>Montant variable</strong>
            <small>Utiliser ce montant comme estimation lorsque les prélèvements fluctuent.</small>
          </span>
          <FormInput type="checkbox" checked={variable} onChange={(event) => setVariable(event.target.checked)} />
          <span className="toggle-visual" aria-hidden="true"><Icon name="check" /></span>
        </label>
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function RecurringDetectionModal({
  proposals,
  selectedKeys,
  isPending,
  error,
  onClose,
  onConfirm,
  onToggle,
}: {
  proposals: RecurringDetectionProposal[]
  selectedKeys: string[]
  isPending: boolean
  error: Error | null
  onClose: () => void
  onConfirm: () => void
  onToggle: (proposalKey: string) => void
}) {
  return (
    <Modal
      title="Séries détectées"
      description="Sélectionnez les propositions à ajouter. Rien n'est enregistré avant votre validation."
      onClose={onClose}
      actions={(
        <>
          {proposals.length > 0 && (
            <button className="primary-button" type="button" disabled={isPending || selectedKeys.length === 0} onClick={onConfirm}>
              {isPending ? 'Validation…' : `Valider la sélection (${selectedKeys.length})`}
            </button>
          )}
          <button className="text-button" type="button" onClick={onClose}>
            {proposals.length > 0 ? 'Annuler' : 'Fermer'}
          </button>
        </>
      )}
    >
      {proposals.length > 0 ? (
        <div className="detection-proposal-list">
          {proposals.map((proposal) => {
            const selected = selectedKeys.includes(proposal.proposal_key)
            return (
              <label className={`detection-proposal${selected ? ' selected' : ''}`} key={proposal.proposal_key}>
                <FormInput
                  type="checkbox"
                  checked={selected}
                  disabled={isPending}
                  aria-label={`Sélectionner ${proposal.label}`}
                  onChange={() => onToggle(proposal.proposal_key)}
                />
                <span className="detection-check" aria-hidden="true"><Icon name="check" /></span>
                <span className="transaction-avatar">{initials(proposal.label)}</span>
                <span className="recurring-copy">
                  <span>
                    <strong>{proposal.label}</strong>
                    <StatusBadge tone={proposal.kind === 'series' ? 'positive' : 'warning'}>
                      {proposal.kind === 'series' ? 'Nouvelle série' : 'Changement détecté'}
                    </StatusBadge>
                    {proposal.amount_type === 'variable' && <StatusBadge>Variable</StatusBadge>}
                  </span>
                  <small>{proposal.account_name} · {proposal.category_name ?? 'Sans catégorie'}</small>
                  <small>{frequencyLabel(proposal.frequency)} · prochaine le {formatDate(proposal.next_due)} · {Math.round(proposal.confidence * 100)}% de confiance</small>
                </span>
                <strong className={Number(proposal.amount) >= 0 ? 'positive' : ''}>{signedMoney(proposal.amount)}</strong>
              </label>
            )
          })}
        </div>
      ) : (
        <EmptyState icon="check" title="Aucune nouvelle série" text="L'historique ne contient pas de nouvelle récurrence à proposer." />
      )}
      {error && <p className="form-error">{errorMessage(error)}</p>}
    </Modal>
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
              <Icon name="sparkle" />{suggestions.isPending ? 'Analyse…' : 'Suggestions locales'}
            </button>
          )}
          <button className="secondary-button" type="button" onClick={() => applyRules.mutate()} disabled={applyRules.isPending}>
            <Icon name="rules" />{applyRules.isPending ? 'Application…' : 'Appliquer les règles'}
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
                await Promise.all([
                  queryClient.invalidateQueries({ queryKey: ['categorization-inbox'] }),
                  queryClient.invalidateQueries({ queryKey: ['categorization-rules'] }),
                ])
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
          name: item.description.slice(0, 120),
          match_type: 'beneficiary',
          patterns: [item.description],
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
        <Field label="Catégorie">
          <FormSelect value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Choisir une catégorie</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </FormSelect>
        </Field>
        <label className={`categorization-rule-toggle${createRule ? ' active' : ''}`}>
          <span className="categorization-toggle-icon"><Icon name="rules" /></span>
          <span>
            <strong>Créer une règle</strong>
            <small>Pour ce libellé</small>
          </span>
          <FormInput type="checkbox" checked={createRule} onChange={(event) => setCreateRule(event.target.checked)} />
          <span className="toggle-visual" aria-hidden="true" />
        </label>
        <button
          className="primary-button categorization-submit"
          type="button"
          disabled={!categoryId || assign.isPending}
          onClick={() => assign.mutate()}
        >
          <Icon name="check" />{assign.isPending ? 'Affectation…' : 'Affecter'}
        </button>
      </div>
      {assign.error && <p className="form-error">{errorMessage(assign.error)}</p>}
    </article>
  )
}

function RulesPanel({ categories, rules }: { categories: Category[]; rules: CategorizationRule[] }) {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [ruleToEdit, setRuleToEdit] = useState<CategorizationRule | null>(null)
  const refreshRules = () => queryClient.invalidateQueries({ queryKey: ['categorization-rules'] })
  return (
    <Panel
      title="Règles de catégorisation"
      subtitle="Les règles déterministes sont toujours appliquées avant les suggestions locales."
      action={<button className="secondary-button small-button" type="button" onClick={() => setShowCreateModal(true)}><Icon name="plus" />Nouvelle règle</button>}
    >
      {showCreateModal && (
        <RuleModal
          categories={categories}
          onClose={() => setShowCreateModal(false)}
          onSaved={async () => {
            await refreshRules()
            setShowCreateModal(false)
          }}
        />
      )}
      {ruleToEdit && (
        <RuleModal
          categories={categories}
          key={ruleToEdit.id}
          rule={ruleToEdit}
          onClose={() => setRuleToEdit(null)}
          onSaved={async () => {
            await refreshRules()
            setRuleToEdit(null)
          }}
        />
      )}
      {rules.length > 0 ? (
        <div className="rule-list">
          {rules.map((rule) => (
            <RuleRow
              categoryName={categories.find((category) => category.id === rule.category_id)?.name ?? 'Catégorie supprimée'}
              key={rule.id}
              onEdit={() => setRuleToEdit(rule)}
              onSaved={refreshRules}
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

function RuleModal({
  categories,
  rule,
  onClose,
  onSaved,
}: {
  categories: Category[]
  rule?: CategorizationRule
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const availableCategories = categories.filter((category) => !category.archived || category.id === rule?.category_id)
  const [name, setName] = useState(rule?.name ?? '')
  const [matchType, setMatchType] = useState<CategorizationRule['match_type']>(rule?.match_type ?? 'beneficiary')
  const [patterns, setPatterns] = useState(
    rule?.patterns.length ? [...rule.patterns] : [rule?.pattern ?? ''],
  )
  const [categoryId, setCategoryId] = useState(String(rule?.category_id ?? ''))
  const [priority, setPriority] = useState(String(rule?.priority ?? 100))
  const [enabled, setEnabled] = useState(rule?.enabled ?? true)
  const submittedPatterns = patterns.map((pattern) => pattern.trim()).filter(Boolean)
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
      name,
      match_type: matchType,
      patterns: submittedPatterns,
      category_id: Number(categoryId),
      priority: Number(priority),
      enabled,
      }
      return rule
      ? apiPatch<CategorizationRule>(`/rules/${rule.id}`, payload)
      : apiPost<CategorizationRule>('/rules', payload)
    },
    onSuccess: onSaved,
  })
  const formId = rule ? `rule-edit-${rule.id}` : 'rule-create'
  return (
    <Modal
      title={rule ? 'Modifier la règle' : 'Nouvelle règle de catégorisation'}
      description="La règle s’applique dès qu’au moins un des motifs correspond au libellé."
      onClose={onClose}
      actions={(
      <>
        <button
          className="primary-button"
          type="submit"
          form={formId}
          disabled={mutation.isPending || !name.trim() || !categoryId || submittedPatterns.length === 0}
        >
          {mutation.isPending ? 'Enregistrement…' : rule ? 'Enregistrer' : 'Créer la règle'}
        </button>
        <button className="text-button" type="button" onClick={onClose}>Annuler</button>
      </>
      )}
    >
      <form className="modal-form rule-modal-form" id={formId} onSubmit={(event: FormEvent) => {
      event.preventDefault()
      mutation.mutate()
      }}>
      <Field label="Nom de la règle">
        <FormInput value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
      </Field>
      <div className="rule-modal-grid">
        <Field label="Type de correspondance">
          <FormSelect value={matchType} onChange={(event) => setMatchType(event.target.value as CategorizationRule['match_type'])}>
            <option value="beneficiary">Bénéficiaire / libellé</option>
            <option value="keyword">Mot-clé</option>
          </FormSelect>
        </Field>
        <Field label="Catégorie cible">
          <FormSelect value={categoryId} onChange={(event) => setCategoryId(event.target.value)} required>
            <option value="">Choisir une catégorie</option>
            {availableCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </FormSelect>
        </Field>
        <Field label="Priorité">
          <FormInput type="number" min="0" max="10000" value={priority} onChange={(event) => setPriority(event.target.value)} required />
        </Field>
      </div>
      <div className="rule-patterns-editor">
        <div className="rule-patterns-header">
          <span>
            <strong>Motifs à reconnaître</strong>
            <small>Un seul motif correspondant suffit pour appliquer la règle.</small>
          </span>
          <button
            className="secondary-button small-button"
            type="button"
            disabled={patterns.length >= 20}
            onClick={() => setPatterns((current) => [...current, ''])}
          >
            <Icon name="plus" />Ajouter un motif
          </button>
        </div>
        <div className="rule-pattern-inputs">
          {patterns.map((pattern, index) => (
            <div className="rule-pattern-input" key={index}>
              <Field label={`Motif ${index + 1}`}>
                <FormInput
                  value={pattern}
                  maxLength={200}
                  placeholder={matchType === 'keyword' ? 'Ex. SUPERMARCHÉ' : 'Ex. Nom du bénéficiaire'}
                  onChange={(event) => {
                    const value = event.target.value
                    setPatterns((current) => current.map((item, itemIndex) => (
                      itemIndex === index ? value : item
                    )))
                  }}
                  required
                />
              </Field>
              <button
                className="icon-action destructive-button"
                type="button"
                aria-label={`Supprimer le motif ${index + 1}`}
                disabled={patterns.length === 1}
                onClick={() => setPatterns((current) => current.filter((_, itemIndex) => itemIndex !== index))}
              >
                <Icon name="trash" />
              </button>
            </div>
          ))}
        </div>
      </div>
      <label className="toggle-row rule-enabled-toggle">
        <span>
          <strong>Règle active</strong>
          <small>Les règles désactivées restent enregistrées sans être appliquées.</small>
        </span>
        <FormInput type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
        <span className="toggle-visual" aria-hidden="true" />
      </label>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function RuleRow({
  categoryName,
  rule,
  onEdit,
  onSaved,
}: {
  categoryName: string
  rule: CategorizationRule
  onEdit: () => void
  onSaved: () => Promise<unknown>
}) {
  const remove = useMutation({
    mutationFn: () => apiDelete(`/rules/${rule.id}`),
    onSuccess: onSaved,
  })
  return (
    <div className={rule.enabled ? '' : 'disabled'}>
      <StatusBadge tone={rule.enabled ? 'primary' : 'neutral'}>
      {rule.match_type === 'beneficiary' ? 'Bénéficiaire' : 'Mot-clé'}
      </StatusBadge>
      <span className="rule-copy">
      <strong>{rule.name}</strong>
      <span className="rule-pattern-list">
        {rule.patterns.map((pattern) => <small key={pattern}>{pattern}</small>)}
      </span>
      </span>
      <Icon name="arrow" />
      <span className="rule-target"><small>Catégorie</small><strong>{categoryName}</strong></span>
      <span className="row-actions">
      <button className="icon-action" type="button" aria-label={`Modifier ${rule.name}`} onClick={onEdit}><Icon name="edit" /></button>
      <button
        className="icon-action destructive-button"
        type="button"
        aria-label={`Supprimer ${rule.name}`}
        disabled={remove.isPending}
        onClick={() => {
          if (window.confirm(`Supprimer la règle « ${rule.name} » ?`)) remove.mutate()
        }}
      >
        <Icon name="trash" />
      </button>
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
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [transactionToEdit, setTransactionToEdit] = useState<Transaction | null>(null)
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
        <button className="primary-button" type="button" onClick={() => setShowCreateModal(true)}><Icon name="plus" />Ajouter une transaction</button>
      </section>
      {showCreateModal && (
        <LedgerTransactionModal
          accounts={accounts}
          categories={categories}
          onClose={() => setShowCreateModal(false)}
          onSaved={async () => {
            await refreshLedger()
            setShowCreateModal(false)
          }}
        />
      )}
      {transactionToEdit && (
        <LedgerTransactionModal
          accounts={accounts}
          categories={categories}
          key={transactionToEdit.id}
          transaction={transactionToEdit}
          onAttachmentChanged={refreshLedger}
          onClose={() => setTransactionToEdit(null)}
          onSaved={async () => {
            await refreshLedger()
            setTransactionToEdit(null)
          }}
        />
      )}
      {(pageQuery.error || countQuery.error) && <div className="error-banner">{errorMessage(pageQuery.error ?? countQuery.error)}</div>}
      <Panel title="Transactions" subtitle={`${total} résultat${total === 1 ? '' : 's'}`}>
        <div className="transaction-toolbar">
          <label className="transaction-search-control">
            <span>Rechercher</span>
            <span className="search-field">
              <Icon name="search" />
              <FormInput type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Libellé ou note" />
            </span>
          </label>
          <Field label="Catégorie">
            <FormSelect value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              <option value="all">Toutes les catégories</option>
              <option value="none">Sans catégorie</option>
              {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </FormSelect>
          </Field>
        </div>
        <div className="data-table-wrap">
          <table className="transaction-table">
            <thead><tr><th>Date</th><th>Libellé</th><th>Compte</th><th>Catégorie</th><th className="amount-column">Montant</th><th /></tr></thead>
            <tbody>
              {filtered.map((transaction) => (
                <TransactionRow
                  accounts={accounts}
                  key={transaction.id}
                  transaction={transaction}
                  onEdit={() => setTransactionToEdit(transaction)}
                  onSaved={refreshLedger}
                />
              ))}
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

function TransactionRow({
  accounts,
  transaction,
  onEdit,
  onSaved,
}: {
  accounts: Account[]
  transaction: Transaction
  onEdit: () => void
  onSaved: () => Promise<void>
}) {
  const [showAttachments, setShowAttachments] = useState(false)
  const linkedTransfer = transaction.transfer_group !== null
  const readOnly = accounts.find((account) => account.id === transaction.account_id)?.archived ?? true
  const remove = useMutation({
    mutationFn: () => apiDelete(`/transactions/${transaction.id}`),
    onSuccess: onSaved,
  })
  return (
    <>
      <tr>
        <td data-label="Date">{formatDate(transaction.booked_at)}</td>
        <td data-label="Libellé"><strong>{transaction.description}</strong>{transaction.notes && <small>{transaction.notes}</small>}</td>
        <td data-label="Compte">{transaction.account_name}</td>
        <td data-label="Catégorie">
          {linkedTransfer ? <StatusBadge>Transfert interne</StatusBadge> : transaction.category_name ?? 'Sans catégorie'}
        </td>
        <td data-label="Montant" className={`amount-column ${Number(transaction.amount) >= 0 ? 'positive' : 'negative'}`}>{signedMoney(transaction.amount)}</td>
        <td data-label="Actions" className="row-actions">
          {(!readOnly || transaction.attachment_count > 0) && (
            <button
              className="icon-action attachment-button"
              type="button"
              aria-label={`Pièces jointes de ${transaction.description}${transaction.attachment_count > 0 ? ` (${transaction.attachment_count})` : ''}`}
              aria-expanded={showAttachments}
              onClick={() => setShowAttachments((current) => !current)}
            >
              <Icon name="attachment" />
              {transaction.attachment_count > 0 && (
                <span className="attachment-count-badge">{transaction.attachment_count}</span>
              )}
            </button>
          )}
          <button
            className="icon-action"
            type="button"
            aria-label={`Modifier ${transaction.description}`}
            disabled={readOnly || linkedTransfer}
            title={readOnly ? 'Le compte est archivé' : linkedTransfer ? "Un transfert lié n'est pas modifiable" : undefined}
            onClick={onEdit}
          >
            <Icon name="edit" />
          </button>
          <button
            className="icon-action destructive-button"
            type="button"
            aria-label={`Supprimer ${transaction.description}`}
            disabled={readOnly || linkedTransfer || remove.isPending}
            title={readOnly ? 'Le compte est archivé' : linkedTransfer ? "Un transfert lié n'est pas supprimable individuellement" : undefined}
            onClick={() => {
              if (window.confirm('Supprimer définitivement cette transaction ?')) remove.mutate()
            }}
          >
            <Icon name="trash" />
          </button>
          {remove.error && <span className="form-error">{errorMessage(remove.error)}</span>}
        </td>
      </tr>
      {showAttachments && (
        <tr className="attachment-table-row">
          <td colSpan={6}>
            <AttachmentManager
              owner={{ kind: 'transaction', transactionId: transaction.id }}
              readOnly={readOnly}
              onChanged={onSaved}
            />
          </td>
        </tr>
      )}
    </>
  )
}

function LedgerTransactionModal({
  accounts,
  categories,
  transaction,
  onAttachmentChanged,
  onClose,
  onSaved,
}: {
  accounts: Account[]
  categories: Category[]
  transaction?: Transaction
  onAttachmentChanged?: () => Promise<void>
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const selectableAccounts = accounts.filter((account) => !account.archived)
  const selectableCategories = categories.filter((category) => (
    !category.archived || category.id === transaction?.category_id
  ))
  const [date, setDate] = useState(transaction?.booked_at ?? localDateInputValue())
  const [description, setDescription] = useState(transaction?.description ?? '')
  const [direction, setDirection] = useState<TransactionDirection>(
    transaction && Number(transaction.amount) >= 0 ? 'deposit' : 'withdrawal',
  )
  const [amount, setAmount] = useState(
    transaction ? String(Math.abs(Number(transaction.amount))) : '',
  )
  const [accountId, setAccountId] = useState(String(transaction?.account_id ?? selectableAccounts[0]?.id ?? ''))
  const [categoryId, setCategoryId] = useState(String(transaction?.category_id ?? ''))
  const [notes, setNotes] = useState(transaction?.notes ?? '')
  const [attachment, setAttachment] = useState<File | null>(null)
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        booked_at: date,
        description,
        amount: directedAmount(amount, direction),
        account_id: Number(accountId),
        category_id: categoryId ? Number(categoryId) : null,
        notes: notes || null,
      }
      if (transaction) return apiPatch<Transaction>(`/transactions/${transaction.id}`, payload)
      const data = new FormData()
      data.append('payload_json', JSON.stringify(payload))
      if (attachment) data.append('file', attachment)
      return apiUpload<Transaction>('/transactions/with-attachment', data)
    },
    onSuccess: onSaved,
  })
  const formId = transaction ? `transaction-edit-${transaction.id}` : 'transaction-create'
  return (
    <Modal
      title={transaction ? 'Modifier la transaction' : 'Nouvelle transaction'}
      description={transaction ? 'Modifiez le mouvement, son compte ou sa catégorie.' : 'Ajoutez un dépôt ou un retrait à l’un de vos comptes.'}
      onClose={onClose}
      actions={(
        <>
          <button
            className="primary-button"
            type="submit"
            form={formId}
            disabled={mutation.isPending || !accountId || !description.trim() || Number(amount) <= 0}
          >
            {mutation.isPending ? 'Enregistrement…' : transaction ? 'Enregistrer' : 'Créer la transaction'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form transaction-modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <AmountDirectionToggle value={direction} onChange={setDirection} />
        <div className="transaction-modal-grid">
          <Field label="Date"><FormInput type="date" value={date} onChange={(event) => setDate(event.target.value)} required /></Field>
          <Field label="Compte">
            <FormSelect value={accountId} onChange={(event) => setAccountId(event.target.value)} required>
              {selectableAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </FormSelect>
          </Field>
          <div className="transaction-modal-wide">
            <Field label="Libellé"><FormInput value={description} onChange={(event) => setDescription(event.target.value)} required autoFocus /></Field>
          </div>
          <Field label="Montant"><FormInput type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></Field>
          <Field label="Catégorie">
            <FormSelect value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
              <option value="">Sans catégorie</option>
              {selectableCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </FormSelect>
          </Field>
          <div className="transaction-modal-wide">
            <Field label="Note"><FormTextarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></Field>
          </div>
        </div>
        {!transaction && (
          <div className="transaction-create-attachment">
            <span className="transaction-create-attachment-icon"><Icon name="attachment" /></span>
            <span>
              <strong>Pièce jointe</strong>
              <small>Facultative · stockage local · 25 Mio maximum</small>
            </span>
            <label className="secondary-button small-button">
              <FormInput
                aria-label="Choisir une pièce jointe"
                type="file"
                onChange={(event) => setAttachment(event.target.files?.[0] ?? null)}
              />
              {attachment ? 'Changer' : 'Choisir un fichier'}
            </label>
            {attachment && (
              <span className="transaction-create-attachment-file">
                <strong>{attachment.name}</strong>
                <button className="icon-action" type="button" aria-label="Retirer la pièce jointe" onClick={() => setAttachment(null)}>
                  <Icon name="close" />
                </button>
              </span>
            )}
          </div>
        )}
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
      {transaction && (
        <div className="transaction-modal-attachments">
          <AttachmentManager
            owner={{ kind: 'transaction', transactionId: transaction.id }}
            readOnly={false}
            onChanged={onAttachmentChanged}
          />
        </div>
      )}
    </Modal>
  )
}

function EnvelopesPanel({ categories, onRefresh }: { categories: Category[]; onRefresh: () => Promise<void> }) {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [categoryToEdit, setCategoryToEdit] = useState<Category | null>(null)
  const [categoryToRemove, setCategoryToRemove] = useState<Category | null>(null)
  const [categoryToRestore, setCategoryToRestore] = useState<Category | null>(null)
  const envelopes = useQuery({
    queryKey: ['budget-envelopes', 'current'],
    queryFn: () => apiGet<Envelope[]>('/budget/envelopes'),
  })
  const envelopeByCategory = useMemo(
    () => new Map((envelopes.data ?? []).map((envelope) => [envelope.category_id, envelope])),
    [envelopes.data],
  )
  const effectiveParentByCategory = useMemo(
    () => effectiveCategoryParentIds(categories),
    [categories],
  )
  const roots = [
    ...categories.filter(
      (category) => (
        !category.archived
        && effectiveParentByCategory.get(category.id) === null
      ),
    ),
    ...categories.filter((category) => category.archived),
  ]
  const activeExpenseRoots = roots.filter(
    (category) => category.kind === 'expense' && !category.archived,
  )
  const totalBudget = activeExpenseRoots.reduce(
    (sum, category) => sum + Number(category.monthly_budget ?? 0),
    0,
  )
  const totalSpent = activeExpenseRoots.reduce(
    (sum, category) => sum + Number(envelopeByCategory.get(category.id)?.spent ?? 0),
    0,
  )
  const budgetedSpent = activeExpenseRoots.reduce(
    (sum, category) => (
      category.monthly_budget === null
        ? sum
        : sum + Number(envelopeByCategory.get(category.id)?.spent ?? 0)
    ),
    0,
  )
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['budget-envelopes'] }),
      queryClient.invalidateQueries({ queryKey: ['recurring-series'] }),
      queryClient.invalidateQueries({ queryKey: ['categorization-rules'] }),
      onRefresh(),
    ])
  }
  return (
    <>
      <section className="section-intro">
        <p>Répartissez votre budget entre catégories et sous-catégories.</p>
        <button className="primary-button" type="button" onClick={() => setShowCreateModal(true)}>
          <Icon name="plus" />Ajouter une catégorie
        </button>
      </section>
      {showCreateModal && (
        <CategoryEditorModal
          categories={categories}
          onClose={() => setShowCreateModal(false)}
          onSaved={async () => {
            await refresh()
            setShowCreateModal(false)
          }}
        />
      )}
      {categoryToEdit && (
        <CategoryEditorModal
          categories={categories}
          category={categoryToEdit}
          key={categoryToEdit.id}
          onClose={() => setCategoryToEdit(null)}
          onRemove={() => {
            setCategoryToRemove(categoryToEdit)
            setCategoryToEdit(null)
          }}
          onSaved={async () => {
            await refresh()
            setCategoryToEdit(null)
          }}
        />
      )}
      {categoryToRemove && (
        <CategoryRemovalModal
          categories={categories}
          category={categoryToRemove}
          key={categoryToRemove.id}
          onClose={() => setCategoryToRemove(null)}
          onSaved={async () => {
            await refresh()
            setCategoryToRemove(null)
          }}
        />
      )}
      {categoryToRestore && (
        <CategoryRestoreModal
          category={categoryToRestore}
          key={categoryToRestore.id}
          onClose={() => setCategoryToRestore(null)}
          onSaved={async () => {
            await refresh()
            setCategoryToRestore(null)
          }}
        />
      )}
      {envelopes.error && <div className="error-banner">{errorMessage(envelopes.error)}</div>}
      <section className="budget-summary" aria-label="Résumé du budget mensuel">
        <div><span>Budget</span><strong>{money(totalBudget)}</strong></div>
        <div><span>Dépensé</span><strong>{money(totalSpent)}</strong></div>
        <div>
          <span>Disponible</span>
          <strong className={totalBudget >= budgetedSpent ? 'positive' : 'negative'}>
            {money(totalBudget - budgetedSpent)}
          </strong>
        </div>
      </section>
      {roots.length > 0 ? (
        <Panel title="Catégories" subtitle="Le budget d’un parent est réparti entre ses sous-catégories.">
          <div className="category-tree-list">
            {roots.map((category) => (
              <CategoryTreeRow
                categories={categories}
                category={category}
                depth={0}
                effectiveParentByCategory={effectiveParentByCategory}
                envelopeByCategory={envelopeByCategory}
                key={category.id}
                onEdit={setCategoryToEdit}
                onRestore={setCategoryToRestore}
              />
            ))}
          </div>
        </Panel>
      ) : (
        <EmptyState
          icon="budget"
          title="Aucune catégorie"
          text="Ajoutez une catégorie de dépense pour commencer à suivre vos enveloppes."
          action={<button className="primary-button" type="button" onClick={() => setShowCreateModal(true)}><Icon name="plus" />Ajouter une catégorie</button>}
        />
      )}
    </>
  )
}

function CategoryTreeRow({
  categories,
  category,
  depth,
  effectiveParentByCategory,
  envelopeByCategory,
  onEdit,
  onRestore,
}: {
  categories: Category[]
  category: Category
  depth: number
  effectiveParentByCategory: Map<number, number | null>
  envelopeByCategory: Map<number, Envelope>
  onEdit: (category: Category) => void
  onRestore: (category: Category) => void
}) {
  const children = category.archived
    ? []
    : categories.filter(
      (child) => (
        !child.archived
        && effectiveParentByCategory.get(child.id) === category.id
      ),
    )
  const activeChildren = children.filter((child) => !child.archived)
  const envelope = envelopeByCategory.get(category.id)
  const remainderBudget = Number(envelope?.remainder_budget ?? 0)
  return (
    <div className="category-tree-group">
      <CategoryTreeItem
        category={category}
        childCount={activeChildren.length}
        depth={depth}
        envelope={envelope}
        spent={Number(envelope?.spent ?? 0)}
        onEdit={() => onEdit(category)}
        onRestore={() => onRestore(category)}
      />
      {(children.length > 0 || remainderBudget > 0) && (
        <div className="category-tree-children">
          {children.map((child) => (
            <CategoryTreeRow
              categories={categories}
              category={child}
              depth={depth + 1}
              effectiveParentByCategory={effectiveParentByCategory}
              envelopeByCategory={envelopeByCategory}
              key={child.id}
              onEdit={onEdit}
              onRestore={onRestore}
            />
          ))}
          {remainderBudget > 0 && (
            <RemainderCategoryRow
              budget={remainderBudget}
              color={category.color}
              spent={Number(envelope?.direct_spent ?? 0)}
            />
          )}
        </div>
      )}
    </div>
  )
}

function CategoryTreeItem({
  category,
  childCount,
  depth,
  envelope,
  spent,
  onEdit,
  onRestore,
}: {
  category: Category
  childCount: number
  depth: number
  envelope?: Envelope
  spent: number
  onEdit: () => void
  onRestore: () => void
}) {
  const budget = envelope?.budget !== undefined && envelope.budget !== null ? Number(envelope.budget) : null
  const showBudgetRow = !category.archived && category.kind === 'expense'
  return (
    <div className={`category-tree-row ${depth > 0 ? 'child' : ''} ${category.archived ? 'archived' : ''}`}>
      {depth > 0 && <Icon name="arrow" />}
      <i style={{ background: category.color }} />
      <strong>{category.name}</strong>
      {category.archived
        ? <StatusBadge tone="warning">Archivée</StatusBadge>
        : childCount > 0
          ? <small>{childCount} sous-catégorie{childCount === 1 ? '' : 's'}</small>
          : category.kind === 'income'
            ? <small>Revenu</small>
            : null}
      <div className="row-actions">
        {category.archived ? (
          <button className="icon-action positive" type="button" aria-label={`Restaurer ${category.name}`} onClick={onRestore}>
            <Icon name="refresh" />
          </button>
        ) : (
          <button className="icon-action" type="button" aria-label={`Modifier ${category.name}`} onClick={onEdit}>
            <Icon name="edit" />
          </button>
        )}
      </div>
      {showBudgetRow && (
        <CategoryBudgetLine budget={budget} color={category.color} spent={spent} />
      )}
    </div>
  )
}

function RemainderCategoryRow({
  budget,
  color,
  spent,
}: {
  budget: number
  color: string
  spent: number
}) {
  return (
    <div className="category-tree-row category-tree-remainder child">
      <Icon name="arrow" />
      <i style={{ background: color }} />
      <strong>Autres</strong>
      <span className="category-automatic-label">Automatique</span>
      <CategoryBudgetLine budget={budget} color={color} spent={spent} />
    </div>
  )
}

function CategoryBudgetLine({
  budget,
  color,
  spent,
}: {
  budget: number | null
  color: string
  spent: number
}) {
  if (budget === null) {
    return (
      <div className="category-tree-budget no-limit">
        <small>Sans plafond{spent > 0 ? ` · ${money(spent)} dépensés` : ''}</small>
      </div>
    )
  }
  const remaining = budget - spent
  const ratio = budget > 0 ? (spent / budget) * 100 : 0
  return (
    <div className="category-tree-budget">
      <div className="category-budget-copy">
        <span>{money(spent)} dépensés</span>
        <strong className={remaining < 0 ? 'negative' : ''}>
          {remaining >= 0 ? `${money(remaining)} restants` : `${money(-remaining)} dépassés`}
        </strong>
      </div>
      <ProgressBar value={ratio} color={color} danger={ratio > 100} />
    </div>
  )
}

function CategoryEditorModal({
  categories,
  category,
  onClose,
  onRemove,
  onSaved,
}: {
  categories: Category[]
  category?: Category
  onClose: () => void
  onRemove?: () => void
  onSaved: () => Promise<void>
}) {
  const effectiveParentByCategory = useMemo(
    () => effectiveCategoryParentIds(categories),
    [categories],
  )
  const childrenBudget = category
    ? categories
      .filter((candidate) => (
        !candidate.archived
        && effectiveParentByCategory.get(candidate.id) === category.id
      ))
      .reduce((sum, child) => sum + Number(child.monthly_budget ?? 0), 0)
    : 0
  const [name, setName] = useState(category?.name ?? '')
  const [kind, setKind] = useState<Category['kind']>(category?.kind ?? 'expense')
  const [color, setColor] = useState(category?.color ?? '#615fff')
  const [parentId, setParentId] = useState(String(category?.parent_id ?? ''))
  const [unlimited, setUnlimited] = useState(
    category ? category.monthly_budget === null && childrenBudget === 0 : true,
  )
  const [budget, setBudget] = useState(
    category?.monthly_budget ?? (childrenBudget > 0 ? childrenBudget.toFixed(2) : ''),
  )
  const descendants = category ? categoryDescendantIds(category.id, categories) : new Set<number>()
  const parentOptions = categories.filter((candidate) => (
    candidate.kind === kind
    && candidate.id !== category?.id
    && !descendants.has(candidate.id)
    && (!candidate.archived || candidate.id === category?.parent_id)
  ))
  useEffect(() => {
    if (parentId && !parentOptions.some((parent) => parent.id === Number(parentId))) {
      setParentId('')
    }
  }, [parentId, parentOptions])
  const showBudgetFields = kind === 'expense'
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        name,
        color,
        parent_id: parentId ? Number(parentId) : null,
        monthly_budget: showBudgetFields && !unlimited ? budget : null,
      }
      return category
        ? apiPatch<Category>(`/categories/${category.id}`, payload)
        : apiPost<Category>('/categories', { ...payload, kind })
    },
    onSuccess: onSaved,
  })
  const formId = category ? `category-edit-${category.id}` : 'category-create'
  const budgetMissing = showBudgetFields && !unlimited && !budget
  return (
    <Modal
      title={category ? 'Modifier la catégorie' : 'Nouvelle catégorie'}
      description={category ? 'Renommez, recolorez, déplacez ou ajustez le plafond de cette catégorie.' : 'Créez une catégorie de revenu ou de dépense, avec un plafond mensuel facultatif.'}
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="submit" form={formId} disabled={mutation.isPending || !name.trim() || budgetMissing}>
            {mutation.isPending ? 'Enregistrement…' : category ? 'Enregistrer' : 'Créer la catégorie'}
          </button>
          {category && onRemove && (
            <button className="text-button destructive-button" type="button" onClick={onRemove}>
              Supprimer
            </button>
          )}
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form className="modal-form category-modal-form" id={formId} onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom">
          <FormInput value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
        </Field>
        {!category && (
          <Field label="Type">
            <FormSelect value={kind} onChange={(event) => setKind(event.target.value as Category['kind'])}>
              <option value="expense">Dépense</option>
              <option value="income">Revenu</option>
            </FormSelect>
          </Field>
        )}
        <Field label="Catégorie parente">
          <FormSelect value={parentId} onChange={(event) => setParentId(event.target.value)}>
            <option value="">Sans parent · catégorie principale</option>
            {parentOptions.map((parent) => (
              <option key={parent.id} value={parent.id}>{parent.name}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Couleur">
          <FormInput className="color-input category-modal-color" type="color" value={color} onChange={(event) => setColor(event.target.value)} />
        </Field>
        {showBudgetFields && (
          <>
            <div className="field">
              <span>Enveloppe de dépense</span>
              <EnvelopeLimitChoice
                allowUnlimited={childrenBudget === 0}
                unlimited={unlimited}
                onChange={setUnlimited}
              />
            </div>
            {!unlimited && (
              <Field label="Plafond mensuel">
                <FormInput
                  type="number"
                  min={childrenBudget > 0 ? childrenBudget : '0.01'}
                  step="0.01"
                  value={budget}
                  onChange={(event) => setBudget(event.target.value)}
                  required
                />
              </Field>
            )}
            {childrenBudget > 0 && (
              <p className="modal-hint">
                {money(childrenBudget)} sont déjà répartis entre les sous-catégories.
                Le reliquat éventuel sera placé automatiquement dans « Autres ».
              </p>
            )}
            {unlimited && <p className="modal-hint">Les dépenses seront suivies sans réduire le budget disponible des enveloppes plafonnées.</p>}
          </>
        )}
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function EnvelopeLimitChoice({
  allowUnlimited = true,
  unlimited,
  onChange,
}: {
  allowUnlimited?: boolean
  unlimited: boolean
  onChange: (unlimited: boolean) => void
}) {
  return (
    <div className="segmented-control envelope-limit-choice" role="group" aria-label="Type d’enveloppe">
      <button className={unlimited ? '' : 'active'} type="button" aria-pressed={!unlimited} onClick={() => onChange(false)}>Avec plafond</button>
      <button
        className={unlimited ? 'active' : ''}
        type="button"
        aria-pressed={unlimited}
        disabled={!allowUnlimited}
        onClick={() => onChange(true)}
      >
        Sans plafond
      </button>
    </div>
  )
}

function CategoryRemovalModal({
  categories,
  category,
  onClose,
  onSaved,
}: {
  categories: Category[]
  category: Category
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [reassign, setReassign] = useState(false)
  const destinations = categories.filter((candidate) => (
    candidate.kind === category.kind && candidate.id !== category.id && !candidate.archived
  ))
  const [replacementCategoryId, setReplacementCategoryId] = useState(String(destinations[0]?.id ?? ''))
  const usage = useQuery({
    queryKey: ['transaction-count', 'category', category.id],
    queryFn: () => apiGet<TransactionCount>(`/transactions/count${queryString({
      category_id: category.id,
    })}`),
  })
  const archiveOrDelete = useMutation({
    mutationFn: () => apiPost<CategoryRemovalResult>(`/categories/${category.id}/remove`),
    onSuccess: onSaved,
  })
  const reassignAndDelete = useMutation({
    mutationFn: () => apiDelete(`/categories/${category.id}${queryString({
      replacement_category_id: Number(replacementCategoryId),
    })}`),
    onSuccess: onSaved,
  })
  const transactionCount = usage.data?.count ?? 0
  return (
    <Modal
      title={`Supprimer « ${category.name} » ?`}
      description={reassign
        ? 'Les transactions, règles et séries récurrentes liées seront réaffectées avant la suppression définitive.'
        : 'La suppression protège automatiquement votre historique.'}
      onClose={onClose}
      actions={(
        <>
          {reassign ? (
            <button
              className="secondary-button destructive-button"
              type="button"
              disabled={!replacementCategoryId || reassignAndDelete.isPending}
              onClick={() => reassignAndDelete.mutate()}
            >
              {reassignAndDelete.isPending ? 'Suppression…' : 'Réaffecter puis supprimer'}
            </button>
          ) : (
            <button
              className="secondary-button destructive-button"
              type="button"
              disabled={usage.isLoading || archiveOrDelete.isPending}
              onClick={() => archiveOrDelete.mutate()}
            >
              {archiveOrDelete.isPending ? 'Traitement…' : transactionCount > 0 ? 'Archiver la catégorie' : 'Supprimer la catégorie'}
            </button>
          )}
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <div className={`modal-warning${transactionCount > 0 ? ' warning' : ''}`}>
        <Icon name="alert" />
        <p>
          {usage.isLoading
            ? 'Vérification de l’historique lié…'
            : transactionCount > 0
              ? `${transactionCount} transaction${transactionCount === 1 ? '' : 's'} utilise${transactionCount === 1 ? '' : 'nt'} cette catégorie. Elle sera archivée et pourra être restaurée.`
              : 'Si aucun autre élément ne dépend de cette catégorie, elle sera supprimée définitivement. Sinon, elle sera archivée et restera restaurable.'}
        </p>
      </div>
      {transactionCount > 0 && destinations.length > 0 && (
        <label className="toggle-row category-removal-reassign-toggle">
          <span>
            <strong>Réaffecter avant suppression définitive</strong>
            <small>Déplace les transactions, règles et séries vers une autre catégorie puis supprime celle-ci sans possibilité de restauration.</small>
          </span>
          <FormInput type="checkbox" checked={reassign} onChange={(event) => setReassign(event.target.checked)} />
          <span className="toggle-visual" aria-hidden="true" />
        </label>
      )}
      {reassign && (
        <Field label="Réaffecter vers">
          <FormSelect value={replacementCategoryId} onChange={(event) => setReplacementCategoryId(event.target.value)}>
            {destinations.map((destination) => (
              <option key={destination.id} value={destination.id}>{destination.name}</option>
            ))}
          </FormSelect>
        </Field>
      )}
      {(usage.error || archiveOrDelete.error || reassignAndDelete.error) && (
        <p className="form-error">{errorMessage(usage.error ?? archiveOrDelete.error ?? reassignAndDelete.error)}</p>
      )}
    </Modal>
  )
}

function CategoryRestoreModal({
  category,
  onClose,
  onSaved,
}: {
  category: Category
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const mutation = useMutation({
    mutationFn: () => apiPost<Category>(`/categories/${category.id}/archive${queryString({
      archived: false,
    })}`),
    onSuccess: onSaved,
  })
  return (
    <Modal
      title={`Restaurer « ${category.name} » ?`}
      description="La catégorie redeviendra disponible pour les nouvelles transactions et les règles."
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? 'Restauration…' : 'Restaurer'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Modal>
  )
}

function categoryDescendantIds(categoryId: number, categories: Category[]): Set<number> {
  const descendants = new Set<number>()
  const visit = (parentId: number) => {
    for (const child of categories.filter((category) => category.parent_id === parentId)) {
      if (descendants.has(child.id)) continue
      descendants.add(child.id)
      visit(child.id)
    }
  }
  visit(categoryId)
  return descendants
}

function effectiveCategoryParentIds(categories: Category[]): Map<number, number | null> {
  const byId = new Map(categories.map((category) => [category.id, category]))
  const result = new Map<number, number | null>()
  for (const category of categories) {
    if (category.archived) continue
    let parentId = category.parent_id
    const visited = new Set([category.id])
    while (parentId !== null) {
      if (visited.has(parentId)) {
        parentId = null
        break
      }
      visited.add(parentId)
      const parent = byId.get(parentId)
      if (!parent) {
        parentId = null
        break
      }
      if (!parent.archived) break
      parentId = parent.parent_id
    }
    result.set(category.id, parentId)
  }
  return result
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
  const containerRef = useRef<HTMLDivElement>(null)
  const selectedYear = Number(value.slice(0, 4))
  const selectedMonth = Number(value.slice(5, 7)) - 1
  const [open, setOpen] = useState(false)
  const [pickerYear, setPickerYear] = useState(selectedYear)
  const [yearRangeStart, setYearRangeStart] = useState(Math.floor(selectedYear / 10) * 10)

  useEffect(() => {
    setPickerYear(selectedYear)
    setYearRangeStart(Math.floor(selectedYear / 10) * 10)
  }, [selectedYear])
  useEffect(() => setOpen(false), [mode])
  useEffect(() => {
    if (!open) return
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) {
        setOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const shift = (delta: number) => onChange(shiftPeriodDate(value, delta, mode))
  const chooseMonth = (month: number) => {
    onChange(replaceDatePeriod(value, pickerYear, month))
    setOpen(false)
  }
  const chooseYear = (year: number) => {
    onChange(replaceDatePeriod(value, year, selectedMonth))
    setOpen(false)
  }

  return (
    <div className="period-picker-shell" ref={containerRef}>
      <div className="period-picker">
        <button
          type="button"
          aria-label={mode === 'year' ? 'Année précédente' : 'Mois précédent'}
          onClick={() => shift(-1)}
        >
          <Icon name="back" />
        </button>
        <button
          className="period-picker-current"
          type="button"
          aria-expanded={open}
          aria-haspopup="dialog"
          onClick={() => setOpen((current) => !current)}
        >
          <Icon name="calendar" />
          <strong>{mode === 'year' ? selectedYear : formatMonth(value.slice(0, 7))}</strong>
        </button>
        <button
          type="button"
          aria-label={mode === 'year' ? 'Année suivante' : 'Mois suivant'}
          onClick={() => shift(1)}
        >
          <Icon name="arrow" />
        </button>
      </div>
      {open && (
        <div
          className="period-quick-picker"
          role="dialog"
          aria-label={mode === 'year' ? 'Sélection rapide de l’année' : 'Sélection rapide du mois'}
        >
          <div className="period-quick-header">
            <button
              type="button"
              aria-label={mode === 'year' ? 'Années précédentes' : 'Année précédente'}
              onClick={() => {
                if (mode === 'year') setYearRangeStart((current) => current - 10)
                else setPickerYear((current) => current - 1)
              }}
            >
              <Icon name="back" />
            </button>
            <strong>
              {mode === 'year' ? `${yearRangeStart} – ${yearRangeStart + 9}` : pickerYear}
            </strong>
            <button
              type="button"
              aria-label={mode === 'year' ? 'Années suivantes' : 'Année suivante'}
              onClick={() => {
                if (mode === 'year') setYearRangeStart((current) => current + 10)
                else setPickerYear((current) => current + 1)
              }}
            >
              <Icon name="arrow" />
            </button>
          </div>
          <div className={`period-option-grid ${mode}`}>
            {mode === 'cycle'
              ? Array.from({ length: 12 }, (_, month) => (
                <button
                  className={pickerYear === selectedYear && month === selectedMonth ? 'active' : ''}
                  type="button"
                  key={month}
                  aria-pressed={pickerYear === selectedYear && month === selectedMonth}
                  onClick={() => chooseMonth(month)}
                >
                  {shortMonth(`${pickerYear}-${String(month + 1).padStart(2, '0')}`)}
                </button>
              ))
              : Array.from({ length: 10 }, (_, offset) => yearRangeStart + offset).map((year) => (
                <button
                  className={year === selectedYear ? 'active' : ''}
                  type="button"
                  key={year}
                  aria-pressed={year === selectedYear}
                  onClick={() => chooseYear(year)}
                >
                  {year}
                </button>
              ))}
          </div>
          <button
            className="period-quick-current"
            type="button"
            onClick={() => {
              onChange(localDateInputValue())
              setOpen(false)
            }}
          >
            {mode === 'year' ? 'Cette année' : 'Ce mois-ci'}
          </button>
        </div>
      )}
    </div>
  )
}

function shiftPeriodDate(value: string, delta: number, mode: PeriodPickerMode): string {
  const year = Number(value.slice(0, 4))
  const month = Number(value.slice(5, 7)) - 1
  if (mode === 'year') return replaceDatePeriod(value, year + delta, month)
  const absoluteMonth = year * 12 + month + delta
  return replaceDatePeriod(
    value,
    Math.floor(absoluteMonth / 12),
    ((absoluteMonth % 12) + 12) % 12,
  )
}

function replaceDatePeriod(value: string, year: number, month: number): string {
  const requestedDay = Number(value.slice(8, 10))
  const day = Math.min(requestedDay, new Date(year, month + 1, 0).getDate())
  return [
    String(year).padStart(4, '0'),
    String(month + 1).padStart(2, '0'),
    String(day).padStart(2, '0'),
  ].join('-')
}

function buildSankey(
  sourceFlows: CashflowFlow[],
  categoryFlows: CashflowFlow[],
  categories: Category[],
) {
  const sources = sourceFlows
    .filter((flow) => Number(flow.inflow) > 0)
    .map((flow) => ({ name: flow.label, amount: Number(flow.inflow), color: '#16c79a' }))
  const destinations = categoryFlows
    .filter((flow) => Number(flow.outflow) > 0)
    .map((flow) => ({
      name: flow.label,
      amount: Number(flow.outflow),
      color: cashflowCategoryColor(flow, categories),
    }))
  if (sources.length === 0 || destinations.length === 0) return { nodes: [], links: [] }
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

function cashflowCategoryColor(flow: CashflowFlow, categories: Category[]): string {
  const rawCategoryId = flow.key.startsWith('category:') ? flow.key.slice('category:'.length) : ''
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
      <span>{item.name ?? 'Flux'}</span>
      <strong>{money(Number(item.value ?? 0))}</strong>
    </div>
  )
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
