import { FormEvent, useEffect, useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiDelete, apiGet, apiPatch, apiPost, apiPut, queryString } from '../api/client'
import type {
  Account,
  AccountDetail,
  AccountInstitutionHistoryPoint,
  AccountSnapshot,
  AccountSnapshotImportResult,
  Holding,
} from '../api/types'
import { supportsHoldings } from '../accountCapabilities'
import {
  AttachmentManager,
  AttachmentPicker,
  uploadOwnerAttachment,
} from '../AttachmentManager'
import {
  accountInstitutionLabel,
  institutionOptions,
  regionalEntitySuggestions,
} from '../institutions'
import type { Route } from '../routing'
import { calculateSavingsProjection } from '../savingsProjection'
import {
  EmptyState,
  Field,
  FormInput,
  FormSelect,
  FormTextarea,
  Icon,
  InstitutionLogo,
  Modal,
  Panel,
  StatusBadge,
  chartTooltipStyle,
  compactMoney,
  errorMessage,
  localDateInputValue,
  money,
  signedMoney,
} from '../ui'

const accountTypeOptions = [
  { value: 'checking', label: 'Compte courant' },
  { value: 'savings', label: 'Épargne' },
  { value: 'pea', label: 'PEA' },
  { value: 'peg', label: 'PEG' },
  { value: 'percol', label: 'PER/PERCOL' },
  { value: 'securities', label: 'Compte-titres' },
  { value: 'life_insurance', label: 'Assurance-vie' },
  { value: 'cash', label: 'Espèces' },
  { value: 'wallet', label: 'Wallet crypto' },
] as const
const accountTypeFilterOrder = [
  'checking',
  'savings',
  'pea',
  'life_insurance',
  'peg',
  'percol',
]
const savingsProducts = [
  { name: 'Livret A', rate: '1.700', cap: '22950.00' },
  { name: 'LDDS', rate: '1.700', cap: '12000.00' },
  { name: 'LEP', rate: '2.500', cap: '10000.00' },
  { name: 'Livret Jeune', rate: '1.700', cap: '1600.00' },
  { name: 'CEL', rate: '1.250', cap: '15300.00' },
  { name: 'PEL', rate: '2.000', cap: '61200.00' },
] as const

const institutionChartColors = [
  '#615fff',
  '#16c79a',
  '#1da9e8',
  '#f97316',
  '#8758f6',
  '#ec4899',
  '#eab308',
  '#14b8a6',
  '#f43f5e',
  '#84cc16',
]

type InstitutionChartRow = {
  period: string
  [key: string]: string | number
}

type StatementListItem =
  | { kind: 'snapshot'; snapshot: AccountSnapshot }
  | { kind: 'missing'; period: string }

const institutionHistoryRanges = [
  { value: '6m', label: '6M', description: '6 derniers mois', months: 6 },
  { value: '1y', label: '1A', description: '1 an', months: 12 },
  { value: '3y', label: '3A', description: '3 dernières années', months: 36 },
  { value: '5y', label: '5A', description: '5 dernières années', months: 60 },
  { value: 'max', label: 'Max', description: 'Depuis toujours', months: null },
] as const

type InstitutionHistoryRange = (typeof institutionHistoryRanges)[number]['value']

function buildInstitutionChart(history: AccountInstitutionHistoryPoint[]) {
  const institutions = [...new Set(history.map((point) => point.institution))]
    .sort((left, right) => left.localeCompare(right, 'fr'))
  const series = institutions.map((institution, index) => ({
    institution,
    dataKey: `institution_${index}`,
    color: institutionChartColors[index % institutionChartColors.length],
  }))
  const dataKeyByInstitution = new Map(
    series.map(({ institution, dataKey }) => [institution, dataKey]),
  )
  const rowsByPeriod = new Map<string, InstitutionChartRow>()

  for (const point of history) {
    const row = rowsByPeriod.get(point.period) ?? { period: point.period }
    const dataKey = dataKeyByInstitution.get(point.institution)
    if (dataKey === undefined) {
      throw new Error(`Série introuvable pour l'établissement ${point.institution}`)
    }
    row[dataKey] = Number(point.balance)
    rowsByPeriod.set(point.period, row)
  }

  return {
    data: [...rowsByPeriod.values()]
      .sort((left, right) => left.period.localeCompare(right.period)),
    series,
  }
}

function filterInstitutionChartData(
  data: InstitutionChartRow[],
  months: number | null,
) {
  if (months === null || data.length === 0) return data

  const latestPeriod = data[data.length - 1].period
  const [latestYear, latestMonth] = latestPeriod.split('-').map(Number)
  const firstMonthIndex = latestYear * 12 + latestMonth - months

  return data.filter((row) => {
    const [year, month] = row.period.split('-').map(Number)
    return year * 12 + month - 1 >= firstMonthIndex
  })
}

export function AccountsView({
  accounts,
  navigate,
  onRefresh,
}: {
  accounts: Account[]
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  const [showForm, setShowForm] = useState(false)
  const [typeFilter, setTypeFilter] = useState('all')
  const [showArchived, setShowArchived] = useState(false)
  const [institutionHistoryRange, setInstitutionHistoryRange] =
    useState<InstitutionHistoryRange>('max')
  const [collapsedInstitutions, setCollapsedInstitutions] = useState<Set<string>>(new Set())
  const institutionHistory = useQuery({
    queryKey: ['account-institution-history', typeFilter],
    queryFn: () => apiGet<AccountInstitutionHistoryPoint[]>(
      `/accounts/institution-history${queryString({
        include_archived: true,
        account_type: typeFilter === 'all' ? undefined : typeFilter,
      })}`,
    ),
  })
  const visibleAccounts = accounts.filter((account) => {
    return account.archived === showArchived && (typeFilter === 'all' || account.type === typeFilter)
  })
  const total = visibleAccounts.reduce((sum, account) => sum + Number(account.balance), 0)
  const availableTypes = new Set(accounts.map((account) => account.type))
  const types = [
    ...accountTypeFilterOrder.filter((type) => availableTypes.has(type)),
    ...[...availableTypes].filter((type) => !accountTypeFilterOrder.includes(type)),
  ]
  const accountGroups = Object.entries(
    visibleAccounts.reduce<Record<string, Account[]>>((groups, account) => {
      const group = accountInstitutionLabel(account) || 'Établissement non renseigné'
      groups[group] = [...(groups[group] ?? []), account]
      return groups
    }, {}),
  ).sort(([left], [right]) => left.localeCompare(right, 'fr'))
  const {
    data: allInstitutionChartData,
    series: institutionChartSeries,
  } = buildInstitutionChart(institutionHistory.data ?? [])
  const activeInstitutionHistoryRange = institutionHistoryRanges.find(
    (range) => range.value === institutionHistoryRange,
  ) ?? institutionHistoryRanges[institutionHistoryRanges.length - 1]
  const institutionChartData = filterInstitutionChartData(
    allInstitutionChartData,
    activeInstitutionHistoryRange.months,
  )
  const visibleInstitutionChartSeries = institutionChartSeries.filter((series) => (
    institutionChartData.some((row) => series.dataKey in row)
  ))
  const toggleInstitution = (institution: string) => {
    setCollapsedInstitutions((current) => {
      const next = new Set(current)
      if (next.has(institution)) next.delete(institution)
      else next.add(institution)
      return next
    })
  }

  return (
    <div className="view-stack">
      <section className="section-intro">
        <p>Les derniers relevés mensuels pilotent les soldes et leurs historiques.</p>
        <button className="primary-button" type="button" onClick={() => setShowForm((current) => !current)}>
          <Icon name="plus" /> Ajouter un compte
        </button>
      </section>

      {showForm && (
        <AccountForm
          onCancel={() => setShowForm(false)}
          onSaved={async () => {
            await onRefresh()
            setShowForm(false)
          }}
        />
      )}

      <section className="balance-hero compact-hero">
        <div>
          <p className="eyebrow">Total des derniers soldes relevés</p>
          <p className="hero-value">{money(total)}</p>
          <div className="hero-detail">
            <span><Icon name="accounts" />{visibleAccounts.length} compte{visibleAccounts.length === 1 ? '' : 's'}</span>
            <span><Icon name="calendar" />Soldes issus des derniers relevés</span>
          </div>
        </div>
      </section>

      <div className="account-filter-groups">
        <FormSelect
          className="account-type-filter-select"
          aria-label="Filtrer par type de compte"
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)}
        >
          <option value="all">Tous les types</option>
          {types.map((type) => (
            <option key={type} value={type}>{accountType(type)}</option>
          ))}
        </FormSelect>
        <nav className="filter-tabs" aria-label="Types de comptes">
          <button className={typeFilter === 'all' ? 'active' : ''} type="button" onClick={() => setTypeFilter('all')}>Tous les types</button>
          {types.map((type) => (
            <button className={typeFilter === type ? 'active' : ''} type="button" key={type} onClick={() => setTypeFilter(type)}>
              {accountType(type)}
            </button>
          ))}
        </nav>
        <button
          className="archive-view-button"
          type="button"
          aria-pressed={showArchived}
          onClick={() => setShowArchived((current) => !current)}
        >
          <Icon name={showArchived ? 'back' : 'archive'} />
          {showArchived ? 'Comptes actifs' : 'Archivés'}
          {!showArchived && accounts.some((account) => account.archived) && (
            <span>{accounts.filter((account) => account.archived).length}</span>
          )}
        </button>
      </div>

      <Panel
        action={(
          <div
            aria-label="Période affichée"
            className="segmented-control account-history-range-selector"
            role="group"
          >
            {institutionHistoryRanges.map((range) => (
              <button
                aria-label={range.description}
                aria-pressed={institutionHistoryRange === range.value}
                className={institutionHistoryRange === range.value ? 'active' : ''}
                key={range.value}
                title={range.description}
                type="button"
                onClick={() => setInstitutionHistoryRange(range.value)}
              >
                {range.label}
              </button>
            ))}
          </div>
        )}
        className="account-history-panel"
        title="Évolution des soldes par établissement"
        subtitle="Comptes actifs et archivés, regroupés par établissement et entité régionale"
      >
        {visibleInstitutionChartSeries.length > 0 && (
          <div
            aria-label="Établissements représentés"
            className="chart-legend institution-history-legend"
            role="list"
          >
            {visibleInstitutionChartSeries.map((series) => (
              <span key={series.dataKey} role="listitem">
                <i className="legend-line" style={{ background: series.color }} />
                {series.institution}
              </span>
            ))}
          </div>
        )}
        <div className="chart-container institution-history-chart">
          {institutionHistory.isLoading ? (
            <div className="chart-loading">Chargement de l'historique…</div>
          ) : institutionHistory.error ? (
            <div className="error-banner" role="alert">
              Impossible de charger l'historique : {errorMessage(institutionHistory.error)}
            </div>
          ) : institutionChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                accessibilityLayer
                aria-label={`Évolution des soldes par établissement, ${activeInstitutionHistoryRange.description.toLowerCase()}`}
                data={institutionChartData}
                margin={{ top: 12, right: 18, bottom: 4, left: 0 }}
              >
                <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                <XAxis
                  axisLine={false}
                  dataKey="period"
                  tick={{ fill: 'var(--muted)', fontSize: 12 }}
                  tickLine={false}
                />
                <YAxis
                  axisLine={false}
                  padding={{ top: 12 }}
                  tick={{ fill: 'var(--muted)', fontSize: 12 }}
                  tickFormatter={compactMoney}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={chartTooltipStyle}
                  formatter={(value) => money(Number(value))}
                  labelFormatter={(label) => `Période ${label}`}
                />
                {visibleInstitutionChartSeries.map((series) => (
                  <Line
                    connectNulls
                    dataKey={series.dataKey}
                    dot={{ fill: series.color, r: 2.5, strokeWidth: 0 }}
                    key={series.dataKey}
                    name={series.institution}
                    stroke={series.color}
                    strokeWidth={2.5}
                    type="monotone"
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState
              icon="calendar"
              text="Ajoutez des relevés mensuels pour suivre l'évolution par établissement."
            />
          )}
        </div>
      </Panel>

      {accountGroups.length > 0 ? (
        <div className="institution-groups">
          {accountGroups.map(([institutionLabel, institutionAccounts]) => {
            const collapsed = collapsedInstitutions.has(institutionLabel)
            const institutionTotal = institutionAccounts.reduce(
              (sum, account) => sum + Number(account.balance),
              0,
            )
            return (
              <section className="institution-group" key={institutionLabel}>
                <button
                  aria-expanded={!collapsed}
                  className="institution-group-header"
                  type="button"
                  onClick={() => toggleInstitution(institutionLabel)}
                >
                  <span className="institution-group-identity">
                    <InstitutionLogo institution={institutionAccounts[0]?.institution} />
                    <span>
                      <strong>{institutionLabel}</strong>
                      <small>
                        {institutionAccounts.length} compte{institutionAccounts.length === 1 ? '' : 's'}
                      </small>
                    </span>
                  </span>
                  <span className="institution-group-balance">
                    <strong>{money(institutionTotal)}</strong>
                    <Icon className={collapsed ? '' : 'expanded'} name="arrow" />
                  </span>
                </button>
                {!collapsed && (
                  <div className="account-grid">
                    {institutionAccounts.map((account) => (
                      <AccountCard account={account} key={account.id} navigate={navigate} />
                    ))}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      ) : (
        <EmptyState
          icon={showArchived ? 'archive' : 'accounts'}
          text={showArchived ? 'Aucun compte archivé.' : 'Aucun compte pour ce filtre.'}
        />
      )}
    </div>
  )
}

function AccountCard({
  account,
  navigate,
}: {
  account: Account
  navigate: (route: Route) => void
}) {
  const missingSnapshotCount = account.missing_snapshot_periods.length
  return (
    <button
      className="account-card interactive-card"
      type="button"
      onClick={() => navigate({ name: 'account', accountId: account.id })}
    >
      <div className="account-card-head">
        <InstitutionLogo institution={account.institution} />
        <span className="account-card-badges">
          <StatusBadge>{accountType(account.type)}</StatusBadge>
          {account.archived && <StatusBadge tone="warning">Archivé</StatusBadge>}
        </span>
      </div>
      <div className="account-card-copy">
        <h2>{account.name}</h2>
        <p>{accountInstitutionLabel(account) || 'Établissement non renseigné'}</p>
        {account.account_number && (
          <small className="account-number">ID : {account.account_number}</small>
        )}
      </div>
      <strong className="account-balance">{money(account.balance)}</strong>
      <div className="account-meta">
        {missingSnapshotCount > 0 && !account.archived ? (
          <span className="account-missing-statements">
            <Icon name="alert" />
            {missingStatementsLabel(missingSnapshotCount)}
          </span>
        ) : (
          <span>Solde relevé</span>
        )}
        <span>Voir le détail <Icon name="arrow" /></span>
      </div>
    </button>
  )
}

export function AccountDetailView({
  accountId,
  accounts,
  navigate,
  onRefresh,
}: {
  accountId: number
  accounts: Account[]
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const account = useQuery({
    queryKey: ['account', accountId],
    queryFn: () => apiGet<AccountDetail>(`/accounts/${accountId}`),
  })
  const snapshots = useQuery({
    queryKey: ['account-snapshots', accountId],
    queryFn: () => apiGet<AccountSnapshot[]>(`/accounts/${accountId}/snapshots`),
  })
  const positionsEnabled = supportsHoldings(account.data?.type ?? '')
  const positions = useQuery({
    queryKey: ['holdings', 'account', accountId],
    queryFn: () => apiGet<Holding[]>(`/holdings${queryString({ account_id: accountId })}`),
    enabled: positionsEnabled,
  })
  const [showSnapshot, setShowSnapshot] = useState(false)
  const [newSnapshotPeriod, setNewSnapshotPeriod] = useState<string | null>(null)
  const [showSnapshotImport, setShowSnapshotImport] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [showArchiveModal, setShowArchiveModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [transferTargetId, setTransferTargetId] = useState('')
  const errors = [
    account.error,
    snapshots.error,
    positionsEnabled ? positions.error : null,
  ].filter(Boolean)

  const refreshDetail = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['account-snapshots', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['holdings', 'account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
      onRefresh(),
    ])
  }
  const archive = useMutation({
    mutationFn: ({
      archived,
      transferToAccountId,
    }: {
      archived: boolean
      transferToAccountId?: number
    }) => apiPost<Account>(`/accounts/${accountId}/archive${queryString({
      archived,
      transfer_to_account_id: transferToAccountId,
    })}`),
    onSuccess: async () => {
      setShowArchiveModal(false)
      setShowDeleteModal(false)
      setShowEdit(false)
      setShowSnapshot(false)
      await refreshDetail()
    },
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/accounts/${accountId}`),
    onSuccess: () => {
      setShowDeleteModal(false)
      navigate({ name: 'accounts' })
    },
  })

  if (account.isLoading) return <div className="loading-card">Chargement du compte…</div>
  if (!account.data) return <div className="error-banner">{errors.length > 0 ? errorMessage(errors[0]) : 'Compte introuvable.'}</div>
  const readOnly = account.data.archived
  const balance = Number(account.data.balance)
  const missingSnapshotPeriods = readOnly ? [] : account.data.missing_snapshot_periods
  const snapshotChartData = [...(snapshots.data ?? [])]
    .sort((left, right) => left.period.localeCompare(right.period))
    .map((snapshot) => ({ ...snapshot, balance: Number(snapshot.balance) }))
  const statementItems: StatementListItem[] = [
    ...(snapshots.data ?? []).map((snapshot): StatementListItem => ({
      kind: 'snapshot',
      snapshot,
    })),
    ...missingSnapshotPeriods.map((period): StatementListItem => ({
      kind: 'missing',
      period,
    })),
  ].sort((left, right) => {
    const leftPeriod = left.kind === 'snapshot' ? left.snapshot.period : left.period
    const rightPeriod = right.kind === 'snapshot' ? right.snapshot.period : right.period
    return rightPeriod.localeCompare(leftPeriod)
  })
  const transferTargets = accounts.filter((candidate) => (
    candidate.id !== accountId
    && !candidate.archived
    && candidate.currency === account.data.currency
  ))
  const openArchiveModal = () => {
    setTransferTargetId(String(transferTargets[0]?.id ?? ''))
    setShowArchiveModal(true)
  }
  const openSnapshotModal = (period: string | null = null) => {
    setNewSnapshotPeriod(period)
    setShowSnapshot(true)
  }
  const closeSnapshotModal = () => {
    setShowSnapshot(false)
    setNewSnapshotPeriod(null)
  }

  return (
    <div className="view-stack">
      <section className="detail-heading">
        <button className="secondary-button" type="button" onClick={() => navigate({ name: 'accounts' })}>
          <Icon name="back" /> Retour
        </button>
        <div className="header-actions">
          {!readOnly && (
            <button
              className="secondary-button"
              type="button"
              onClick={() => openSnapshotModal()}
            >
              <Icon name="calendar" /> Ajouter un relevé
            </button>
          )}
          <button
            className="secondary-button"
            type="button"
            disabled={archive.isPending}
            onClick={() => {
              if (account.data.archived) archive.mutate({ archived: false })
              else openArchiveModal()
            }}
          >
            <Icon name="archive" /> {account.data.archived ? 'Restaurer' : 'Archiver'}
          </button>
          {!readOnly && (
            <button className="secondary-button" type="button" onClick={() => setShowEdit((current) => !current)}>
              <Icon name="edit" /> Modifier
            </button>
          )}
        </div>
      </section>

      {(errors.length > 0 || archive.error || remove.error) && (
        <div className="error-banner">{errorMessage(errors[0] ?? archive.error ?? remove.error)}</div>
      )}

      {showDeleteModal && !readOnly && (
        <Modal
          title="Que souhaitez-vous faire de ce compte ?"
          description="La suppression est irréversible. L'archivage conserve tout l'historique."
          onClose={() => setShowDeleteModal(false)}
          actions={(
            <>
              <button className="text-button" type="button" onClick={() => setShowDeleteModal(false)}>
                Annuler
              </button>
              <button
                className="secondary-button destructive-button"
                type="button"
                disabled={remove.isPending}
                onClick={() => remove.mutate()}
              >
                <Icon name="trash" /> Supprimer définitivement
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={archive.isPending}
                onClick={() => {
                  setShowDeleteModal(false)
                  if (account.data.archived) return
                  openArchiveModal()
                }}
              >
                <Icon name="archive" /> {account.data.archived ? 'Conserver archivé' : 'Archiver plutôt'}
              </button>
            </>
          )}
        >
          <div className="modal-warning">
            <Icon name="alert" />
            <p>
              Un compte contenant des relevés, séries récurrentes, positions ou liens ne peut pas être
              supprimé. Dans ce cas, choisissez l'archivage.
            </p>
          </div>
          {(remove.error || archive.error) && (
            <p className="form-error">{errorMessage(remove.error ?? archive.error)}</p>
          )}
        </Modal>
      )}

      {showArchiveModal && !readOnly && (
        <Modal
          title={`Archiver « ${account.data.name} » ?`}
          description="Le compte restera consultable dans la vue des comptes archivés."
          onClose={() => setShowArchiveModal(false)}
          actions={(
            <>
              <button className="text-button" type="button" onClick={() => setShowArchiveModal(false)}>
                Annuler
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={archive.isPending}
                onClick={() => archive.mutate({ archived: true })}
              >
                Archiver sans transfert
              </button>
            </>
          )}
        >
          {balance !== 0 && (
            <div className="modal-warning warning">
              <Icon name="alert" />
              <p>
                Le dernier relevé de ce compte indique <strong>{money(account.data.balance)}</strong>.
                Vérifiez-le avant de poursuivre.
              </p>
            </div>
          )}
          {balance > 0 && transferTargets.length > 0 && (
            <div className="archive-transfer">
              <Field label="Transférer les fonds vers">
                <FormSelect
                  value={transferTargetId}
                  onChange={(event) => setTransferTargetId(event.target.value)}
                >
                  {transferTargets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name} · {money(target.balance)}
                    </option>
                  ))}
                </FormSelect>
              </Field>
              <button
                className="primary-button"
                type="button"
                disabled={!transferTargetId || archive.isPending}
                onClick={() => archive.mutate({
                  archived: true,
                  transferToAccountId: Number(transferTargetId),
                })}
              >
                Transférer puis archiver
              </button>
            </div>
          )}
          {balance > 0 && transferTargets.length === 0 && (
            <p className="modal-hint">
              Aucun autre compte actif dans la même devise n'est disponible pour le transfert.
            </p>
          )}
          {archive.error && <p className="form-error">{errorMessage(archive.error)}</p>}
        </Modal>
      )}

      {showSnapshot && !readOnly && (
        <SnapshotForm
          account={account.data}
          initialPeriod={newSnapshotPeriod}
          onClose={closeSnapshotModal}
          onSaved={async () => {
            await refreshDetail()
            closeSnapshotModal()
          }}
        />
      )}

      {showSnapshotImport && !readOnly && (
        <Modal
          title="Import rapide des relevés"
          description="Collez deux colonnes TSV : la date, puis le solde du compte."
          onClose={() => setShowSnapshotImport(false)}
        >
          <SnapshotImportForm
            accountId={account.data.id}
            onCancel={() => setShowSnapshotImport(false)}
            onSaved={async () => {
              await refreshDetail()
              setShowSnapshotImport(false)
            }}
          />
        </Modal>
      )}

      {showEdit && !readOnly && (
        <EditAccountForm
          account={account.data}
          onCancel={() => setShowEdit(false)}
          onSaved={async () => {
            await refreshDetail()
            setShowEdit(false)
          }}
        />
      )}

      <section className="account-detail-hero">
        <div className="detail-account-title">
          <InstitutionLogo institution={account.data.institution} />
          <strong>{account.data.name}</strong>
          <StatusBadge>{accountType(account.data.type)}</StatusBadge>
          {account.data.archived && <StatusBadge tone="warning">Archivé</StatusBadge>}
        </div>
        <p>{snapshotChartData.length > 0 ? 'Dernier solde relevé' : 'Solde initial'}</p>
        <strong>{money(account.data.balance)}</strong>
        <small>
          {accountInstitutionLabel(account.data) || 'Établissement non renseigné'}
          {account.data.account_number && ` · ID : ${account.data.account_number}`}
        </small>
      </section>

      {account.data.type === 'savings' ? (
        <SavingsConfigurator
          account={account.data}
          onSaved={refreshDetail}
          readOnly={readOnly}
          snapshots={snapshotChartData}
        />
      ) : (
        <Panel title="Historique" subtitle="Relevés mensuels persistants">
          <div className="chart-container account-history-chart">
            {snapshotChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={snapshotChartData}>
                  <defs>
                    <linearGradient id="account-history-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} padding={{ top: 12 }} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip contentStyle={chartTooltipStyle} labelFormatter={(value) => String(value)} formatter={(value) => money(Number(value))} />
                  <Area dataKey="balance" type="monotone" stroke="#16c79a" strokeWidth={2.5} fill="url(#account-history-fill)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState icon="calendar" text="Ajoutez le premier relevé mensuel pour construire l'historique." />
            )}
          </div>
        </Panel>
      )}

      {positionsEnabled && (
        <AccountPositions
          holdings={positions.data ?? []}
          isLoading={positions.isLoading}
          navigate={navigate}
          readOnly={readOnly}
        />
      )}

      <Panel
        title="Relevés mensuels"
        subtitle={[
          `${snapshots.data?.length ?? 0} relevé${snapshots.data?.length === 1 ? '' : 's'}`,
          missingSnapshotPeriods.length > 0
            ? missingStatementsLabel(missingSnapshotPeriods.length)
            : null,
        ].filter(Boolean).join(' · ')}
        action={!readOnly ? (
          <div className="header-actions">
            <button
              className="secondary-button small-button"
              type="button"
              onClick={() => setShowSnapshotImport(true)}
            >
              <Icon name="database" /> Import rapide
            </button>
            <button
              className="primary-button small-button"
              type="button"
              onClick={() => openSnapshotModal()}
            >
              <Icon name="calendar" /> Ajouter un relevé
            </button>
          </div>
        ) : undefined}
      >
        {statementItems.length > 0 ? (
          <div className="statement-list">
            {statementItems.map((item) => (
              item.kind === 'snapshot' ? (
                <SnapshotRow
                  accountId={accountId}
                  key={`snapshot-${item.snapshot.id}`}
                  snapshot={item.snapshot}
                  onSaved={refreshDetail}
                  readOnly={readOnly}
                />
              ) : (
                <MissingSnapshotRow
                  key={`missing-${item.period}`}
                  period={item.period}
                  onCreate={() => openSnapshotModal(item.period)}
                />
              )
            ))}
          </div>
        ) : (
          <EmptyState icon="calendar" text="Aucun relevé enregistré." />
        )}
      </Panel>

      {!readOnly && (
        <div className="account-delete-action">
          <button
            className="text-button destructive-button"
            type="button"
            disabled={remove.isPending}
            onClick={() => setShowDeleteModal(true)}
          >
            <Icon name="trash" /> Supprimer ce compte
          </button>
          <small>
            La suppression est disponible uniquement si le compte ne contient aucun relevé,
            récurrent, actif, dette, objectif ou partage.
          </small>
        </div>
      )}
    </div>
  )
}

function MissingSnapshotRow({
  period,
  onCreate,
}: {
  period: string
  onCreate: () => void
}) {
  return (
    <div className="statement-row missing-statement-row">
      <span>{period}</span>
      <strong><Icon name="alert" /> Relevé manquant</strong>
      <button
        className="secondary-button small-button missing-statement-create"
        type="button"
        onClick={onCreate}
      >
        <Icon name="plus" /> Créer
      </button>
    </div>
  )
}

function SnapshotRow({
  accountId,
  snapshot,
  onSaved,
  readOnly,
}: {
  accountId: number
  snapshot: AccountSnapshot
  onSaved: () => Promise<void>
  readOnly: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [showAttachments, setShowAttachments] = useState(false)
  const [period, setPeriod] = useState(snapshot.period)
  const [balance, setBalance] = useState(snapshot.balance)
  const update = useMutation({
    mutationFn: () => apiPatch<AccountSnapshot>(
      `/accounts/${accountId}/snapshots/${snapshot.id}`,
      { period, balance },
    ),
    onSuccess: async () => {
      setEditing(false)
      await onSaved()
    },
  })
  const remove = useMutation({
    mutationFn: () => apiDelete(`/accounts/${accountId}/snapshots/${snapshot.id}`),
    onSuccess: onSaved,
  })
  return (
    <>
      {editing && (
        <Modal
          title={`Modifier le relevé ${snapshot.period}`}
          description="Mettez à jour le solde ou gérez les pièces jointes de ce relevé."
          onClose={() => setEditing(false)}
          actions={(
            <>
              <button className="text-button" type="button" onClick={() => setEditing(false)}>Annuler</button>
              <button
                className="primary-button"
                type="submit"
                form={`snapshot-edit-${snapshot.id}`}
                disabled={update.isPending}
              >
                {update.isPending ? 'Enregistrement…' : 'Enregistrer'}
              </button>
            </>
          )}
        >
          <form
            className="modal-form"
            id={`snapshot-edit-${snapshot.id}`}
            onSubmit={(event) => {
              event.preventDefault()
              update.mutate()
            }}
          >
            <Field label="Période">
              <FormInput
                type="month"
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                required
              />
            </Field>
            <Field label="Solde">
              <FormInput
                type="number"
                step="0.01"
                value={balance}
                onChange={(event) => setBalance(event.target.value)}
                required
              />
            </Field>
            <div className="modal-attachment-field">
              <AttachmentManager
                owner={{ kind: 'snapshot', accountId, snapshotId: snapshot.id }}
                readOnly={false}
              />
            </div>
            {update.error && <p className="form-error">{errorMessage(update.error)}</p>}
          </form>
        </Modal>
      )}
      <div className="statement-row">
        <span>{snapshot.period}</span>
        <strong>{money(snapshot.balance)}</strong>
        {(!readOnly || snapshot.attachment_count > 0) && (
          <span className="row-actions">
            <button
              className="icon-action attachment-button"
              type="button"
              aria-label={`Pièces jointes${snapshot.attachment_count > 0 ? ` (${snapshot.attachment_count})` : ''}`}
              aria-expanded={showAttachments}
              onClick={() => setShowAttachments((current) => !current)}
            >
              <Icon name="attachment" />
              {snapshot.attachment_count > 0 && (
                <span className="attachment-count-badge">{snapshot.attachment_count}</span>
              )}
            </button>
            {!readOnly && (
              <>
                <button className="icon-action" type="button" aria-label="Modifier le relevé" onClick={() => setEditing(true)}>
                  <Icon name="edit" />
                </button>
                <button
                  className="icon-action"
                  type="button"
                  aria-label="Supprimer le relevé"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(`Supprimer le relevé ${snapshot.period} ?`)) remove.mutate()
                  }}
                >
                  <Icon name="trash" />
                </button>
              </>
            )}
          </span>
        )}
        {showAttachments && (
          <div className="snapshot-attachment-panel">
            <AttachmentManager
              owner={{ kind: 'snapshot', accountId, snapshotId: snapshot.id }}
              readOnly={readOnly}
            />
          </div>
        )}
        {remove.error && <span className="form-error row-error">{errorMessage(remove.error)}</span>}
      </div>
    </>
  )
}

function AccountPositions({
  holdings,
  isLoading,
  navigate,
  readOnly,
}: {
  holdings: Holding[]
  isLoading: boolean
  navigate: (route: Route) => void
  readOnly: boolean
}) {
  return (
    <Panel
      title="Positions"
      subtitle={`${holdings.length} position${holdings.length === 1 ? '' : 's'} liée${holdings.length === 1 ? '' : 's'} à ce compte`}
      action={!readOnly ? (
        <button
          className="secondary-button small-button"
          type="button"
          onClick={() => navigate({ name: 'wealth', tab: 'holdings' })}
        >
          Gérer les positions <Icon name="arrow" />
        </button>
      ) : undefined}
    >
      {isLoading ? (
        <div className="loading-card">Chargement des positions…</div>
      ) : holdings.length > 0 ? (
        <div className="data-table-wrap position-table-wrap">
          <table className="position-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Nom</th>
                <th className="amount-column">Quantité</th>
                <th className="amount-column">Prix moyen d'achat</th>
                <th className="amount-column">Prix du titre</th>
                <th className="amount-column">Valeur</th>
                <th className="amount-column">Plus-value / Moins-value</th>
                <th className="amount-column">Plus-value / Moins-value %</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((holding) => {
                const gainPercent = Number(holding.total_cost_basis) > 0
                  ? (Number(holding.total_gain) / Number(holding.total_cost_basis)) * 100
                  : 0
                const gainTone = Number(holding.total_gain) >= 0 ? 'positive' : 'negative'
                return (
                  <tr key={holding.id}>
                    <td data-label="Ticker"><strong>{holding.symbol || '—'}</strong></td>
                    <td data-label="Nom">{holding.name}</td>
                    <td data-label="Quantité" className="amount-column">{formatQuantity(holding.quantity)}</td>
                    <td data-label="Prix moyen d'achat" className="amount-column">{money(holding.average_price)}</td>
                    <td data-label="Prix du titre" className="amount-column">{money(holding.current_price)}</td>
                    <td data-label="Valeur" className="amount-column">{money(holding.market_value)}</td>
                    <td data-label="Plus-value / Moins-value" className={`amount-column ${gainTone}`}>{signedMoney(holding.total_gain)}</td>
                    <td data-label="Plus-value / Moins-value %" className={`amount-column ${gainTone}`}>
                      {signedPercent(gainPercent)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon="holdings"
          text="Aucune position n'est encore rattachée à ce compte."
          action={!readOnly ? (
            <button
              className="secondary-button small-button"
              type="button"
              onClick={() => navigate({ name: 'wealth', tab: 'holdings' })}
            >
              Ajouter une position
            </button>
          ) : undefined}
        />
      )}
    </Panel>
  )
}

function SavingsConfigurator({
  account,
  onSaved,
  readOnly,
  snapshots,
}: {
  account: Account
  onSaved: () => Promise<void>
  readOnly: boolean
  snapshots: Array<{ period: string; balance: number }>
}) {
  const defaultProduct = savingsProducts[0]
  const [showConfig, setShowConfig] = useState(false)
  const [product, setProduct] = useState(account.savings_product ?? defaultProduct.name)
  const [annualRate, setAnnualRate] = useState(
    account.annual_interest_rate ?? defaultProduct.rate,
  )
  const [legalCap, setLegalCap] = useState(account.legal_cap ?? defaultProduct.cap)
  useEffect(() => {
    const configuredProduct = savingsProducts.find(
      (candidate) => candidate.name === account.savings_product,
    ) ?? defaultProduct
    setProduct(account.savings_product ?? configuredProduct.name)
    setAnnualRate(account.annual_interest_rate ?? configuredProduct.rate)
    setLegalCap(account.legal_cap ?? configuredProduct.cap)
  }, [
    account.id,
    account.savings_product,
    account.annual_interest_rate,
    account.legal_cap,
    defaultProduct,
  ])
  const mutation = useMutation({
    mutationFn: () => apiPatch<Account>(`/accounts/${account.id}`, {
      savings_product: product,
      annual_interest_rate: annualRate,
      legal_cap: legalCap,
    }),
    onSuccess: async () => {
      await onSaved()
      setShowConfig(false)
    },
  })
  const projection = calculateSavingsProjection(
    snapshots,
    Number(account.balance),
    Number(annualRate || 0),
    new Date().getFullYear(),
  )
  const cap = Number(legalCap || 0)
  return (
    <Panel
      title="Historique et projection"
      subtitle={`Projection fin ${projection.year}, pondérée par les soldes de clôture mensuels.`}
      action={!readOnly ? (
        showConfig ? (
          <button
            key="save-savings-config"
            className="primary-button small-button"
            type="submit"
            form="savings-config-form"
            disabled={mutation.isPending}
          >
            <Icon name="check" /> Sauvegarder
          </button>
        ) : (
          <button
            key="open-savings-config"
            className="secondary-button small-button"
            type="button"
            onClick={(event) => {
              event.preventDefault()
              setShowConfig(true)
            }}
          >
            <Icon name="settings" /> Configurer
          </button>
        )
      ) : undefined}
    >
      {showConfig && !readOnly && (
        <>
          <form
            id="savings-config-form"
            className="savings-config-form"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              mutation.mutate()
            }}
          >
            <Field label="Produit">
              <FormSelect
                value={product}
                onChange={(event) => {
                  const selected = savingsProducts.find(
                    (candidate) => candidate.name === event.target.value,
                  )
                  if (!selected) return
                  setProduct(selected.name)
                  setAnnualRate(selected.rate)
                  setLegalCap(selected.cap)
                }}
              >
                {savingsProducts.map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </FormSelect>
            </Field>
            <Field label="Taux annuel">
              <div className="input-with-suffix">
                <FormInput
                  type="number"
                  min="0"
                  max="100"
                  step="0.001"
                  value={annualRate}
                  onChange={(event) => setAnnualRate(event.target.value)}
                  required
                />
                <span>%</span>
              </div>
            </Field>
            <Field label="Plafond légal">
              <FormInput
                type="number"
                min="0"
                step="0.01"
                value={legalCap}
                onChange={(event) => setLegalCap(event.target.value)}
                required
              />
            </Field>
          </form>
          {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
        </>
      )}
      <div className="savings-metrics">
        <article>
          <span>Dernier solde connu</span>
          <strong>{money(projection.referenceBalance)}</strong>
          <small>{projection.referencePeriod ? `Relevé ${projection.referencePeriod}` : 'Solde actuel du compte'}</small>
        </article>
        <article>
          <span>Plafond légal</span>
          <strong>{money(cap)}</strong>
        </article>
        <article>
          <span>Projection fin {projection.year}</span>
          <strong>{money(projection.projectedBalance)}</strong>
          <small>+{money(projection.estimatedInterest)} d'intérêts estimés selon les soldes mensuels</small>
        </article>
      </div>
      <div className="chart-container savings-history-chart">
        {snapshots.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={snapshots} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
              <defs>
                <linearGradient id="savings-history-fill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
              <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
              <YAxis axisLine={false} padding={{ top: 12 }} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
              <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
              <Area
                dataKey="balance"
                fill="url(#savings-history-fill)"
                name="Relevé"
                stroke="#16c79a"
                strokeWidth={2.5}
                type="monotone"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState icon="calendar" text="Ajoutez le premier relevé mensuel pour construire l'historique." />
        )}
      </div>
    </Panel>
  )
}

function AccountForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [institution, setInstitution] = useState('')
  const [regionalEntity, setRegionalEntity] = useState('')
  const [accountNumber, setAccountNumber] = useState('')
  const [initialBalance, setInitialBalance] = useState('0')
  const mutation = useMutation({
    mutationFn: () => apiPost<Account>('/accounts', {
      name,
      type,
      currency: 'EUR',
      institution: institution || null,
      regional_entity: regionalEntity || null,
      account_number: accountNumber || null,
      initial_balance: initialBalance,
      ...(type === 'savings' ? {
        savings_product: savingsProducts[0].name,
        annual_interest_rate: savingsProducts[0].rate,
        legal_cap: savingsProducts[0].cap,
      } : {}),
    }),
    onSuccess: onSaved,
  })
  return (
    <Panel title="Nouveau compte" subtitle="Le solde initial sert de point de départ au suivi.">
      <form className="feature-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom"><FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></Field>
        <InstitutionField
          institution={institution}
          onInstitutionChange={setInstitution}
          onRegionalEntityChange={setRegionalEntity}
          regionalEntity={regionalEntity}
        />
        <Field label="Numéro / identifiant du compte">
          <FormInput
            value={accountNumber}
            onChange={(event) => setAccountNumber(event.target.value)}
            maxLength={120}
            spellCheck={false}
          />
        </Field>
        <Field label="Type">
          <FormSelect value={type} onChange={(event) => setType(event.target.value)}>
            {accountTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Solde initial"><FormInput type="number" step="0.01" value={initialBalance} onChange={(event) => setInitialBalance(event.target.value)} required /></Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending}>Créer</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function EditAccountForm({ account, onCancel, onSaved }: { account: Account; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(account.name)
  const [type, setType] = useState(account.type)
  const [institution, setInstitution] = useState(account.institution ?? '')
  const [regionalEntity, setRegionalEntity] = useState(account.regional_entity ?? '')
  const [accountNumber, setAccountNumber] = useState(account.account_number ?? '')
  const [balance, setBalance] = useState(account.balance)
  const mutation = useMutation({
    mutationFn: () => apiPatch<Account>(`/accounts/${account.id}`, {
      name,
      type,
      institution: institution || null,
      regional_entity: regionalEntity || null,
      account_number: accountNumber || null,
      ...(balance !== account.balance ? { balance } : {}),
      ...(type === 'savings' && account.type !== 'savings' ? {
        savings_product: savingsProducts[0].name,
        annual_interest_rate: savingsProducts[0].rate,
        legal_cap: savingsProducts[0].cap,
      } : {}),
    }),
    onSuccess: onSaved,
  })
  return (
    <Panel
      title="Modifier le compte"
      subtitle="Toute modification du solde enregistre un relevé pour le mois en cours."
    >
      <form className="inline-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom"><FormInput value={name} onChange={(event) => setName(event.target.value)} required /></Field>
        <InstitutionField
          institution={institution}
          onInstitutionChange={setInstitution}
          onRegionalEntityChange={setRegionalEntity}
          regionalEntity={regionalEntity}
        />
        <Field label="Numéro / identifiant du compte">
          <FormInput
            value={accountNumber}
            onChange={(event) => setAccountNumber(event.target.value)}
            maxLength={120}
            spellCheck={false}
          />
        </Field>
        <Field label="Type">
          <FormSelect value={type} onChange={(event) => setType(event.target.value)}>
            {!accountTypeOptions.some((option) => option.value === type) && (
              <option value={type}>{accountType(type)}</option>
            )}
            {accountTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </FormSelect>
        </Field>
        <Field label="Solde du mois en cours"><FormInput type="number" step="0.01" value={balance} onChange={(event) => setBalance(event.target.value)} required /></Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending}>Enregistrer</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function InstitutionField({
  institution,
  onInstitutionChange,
  onRegionalEntityChange,
  regionalEntity,
}: {
  institution: string
  onInstitutionChange: (value: string) => void
  onRegionalEntityChange: (value: string) => void
  regionalEntity: string
}) {
  const suggestionsId = useId()
  const isKnown = institutionOptions.includes(institution)
  const [isOther, setIsOther] = useState(Boolean(institution) && !isKnown)
  const selection = isOther ? 'other' : institution
  const suggestions = regionalEntitySuggestions[institution] ?? []
  return (
    <>
      <Field label="Établissement">
        <FormSelect
          aria-label="Établissement"
          value={selection}
          onChange={(event) => {
            const value = event.target.value
            setIsOther(value === 'other')
            onInstitutionChange(value === 'other' ? '' : value)
            onRegionalEntityChange('')
          }}
        >
          <option value="">Non renseigné</option>
          {institutionOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          <option value="other">Autre…</option>
        </FormSelect>
      </Field>
      {isOther && (
        <Field label="Autre établissement">
          <FormInput
            aria-label="Autre établissement"
            value={institution}
            onChange={(event) => onInstitutionChange(event.target.value)}
            maxLength={120}
            required
          />
        </Field>
      )}
      <Field
        label="Entité régionale"
        hint="Facultatif — par exemple Loire Drôme Ardèche ou Rhône Alpes."
      >
        <>
          <FormInput
            disabled={!institution.trim()}
            list={suggestions.length > 0 ? suggestionsId : undefined}
            value={regionalEntity}
            onChange={(event) => onRegionalEntityChange(event.target.value)}
            maxLength={120}
            placeholder={suggestions[0] ?? 'Nom de la caisse ou entité locale'}
          />
          {suggestions.length > 0 && (
            <datalist id={suggestionsId}>
              {suggestions.map((item) => <option key={item} value={item} />)}
            </datalist>
          )}
        </>
      </Field>
    </>
  )
}

function SnapshotForm({
  account,
  initialPeriod,
  onClose,
  onSaved,
}: {
  account: Account
  initialPeriod: string | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [period, setPeriod] = useState(
    initialPeriod ?? localDateInputValue().slice(0, 7),
  )
  const [balance, setBalance] = useState(account.balance)
  const [attachment, setAttachment] = useState<File | null>(null)
  const formId = 'snapshot-create'
  const mutation = useMutation({
    mutationFn: async () => {
      const snapshot = await apiPut<AccountSnapshot>(
        `/accounts/${account.id}/snapshots`,
        { period, balance },
      )
      if (attachment) {
        await uploadOwnerAttachment(
          { kind: 'snapshot', accountId: account.id, snapshotId: snapshot.id },
          attachment,
        )
      }
      return snapshot
    },
    onSuccess: onSaved,
  })
  return (
    <Modal
      title="Nouveau relevé"
      description="Enregistrez le solde de clôture d'un mois."
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
      <form
        className="modal-form"
        id={formId}
        onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <Field label="Période">
          <FormInput
            type="month"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
            required
          />
        </Field>
        <Field label="Solde de clôture">
          <FormInput
            type="number"
            step="0.01"
            value={balance}
            onChange={(event) => setBalance(event.target.value)}
            required
          />
        </Field>
        <div className="modal-attachment-field">
          <AttachmentPicker
            file={attachment}
            onChange={setAttachment}
            disabled={mutation.isPending}
          />
        </div>
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}

function SnapshotImportForm({
  accountId,
  onCancel,
  onSaved,
}: {
  accountId: number
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const [content, setContent] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<AccountSnapshotImportResult>(
      `/accounts/${accountId}/snapshots/import`,
      { content },
    ),
    onSuccess: onSaved,
  })
  return (
    <form className="snapshot-import-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <div className="snapshot-import-format">
        <strong>Format TSV</strong>
        <code>DD/MM/YYYY ↹ montant</code>
      </div>
      <Field label="Données à importer">
        <FormTextarea
          aria-label="Données TSV des relevés"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder={'31/01/2026\t1 250,40 €\n28/02/2026\t1 310,20 €'}
          rows={8}
          spellCheck={false}
          required
        />
      </Field>
      <p className="modal-hint">
        L’en-tête « Date ↹ Montant » est facultative. Une seule ligne est acceptée par mois.
        Le suffixe € est accepté. Les mois déjà enregistrés seront remplacés. En cas d’erreur,
        aucune ligne ne sera importée.
      </p>
      <div className="form-buttons">
        <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
        <button className="primary-button" type="submit" disabled={!content.trim() || mutation.isPending}>
          {mutation.isPending ? 'Import…' : 'Importer'}
        </button>
      </div>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </form>
  )
}

function accountType(type: string): string {
  if (type === 'investment') return 'Investissement (ancien type)'
  return accountTypeOptions.find((option) => option.value === type)?.label ?? type
}

function missingStatementsLabel(count: number): string {
  return `${count} relevé${count === 1 ? '' : 's'} manquant${count === 1 ? '' : 's'}`
}

function formatQuantity(value: string): string {
  return Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 6 })
}

function signedPercent(value: number): string {
  const formatted = Math.abs(value).toLocaleString('fr-FR', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })
  if (value === 0) return `${formatted} %`
  return `${value > 0 ? '+' : '−'}${formatted} %`
}
