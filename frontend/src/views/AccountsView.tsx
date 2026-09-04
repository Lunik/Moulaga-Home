import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload, queryString } from '../api/client'
import type {
  Account,
  AccountDetail,
  AccountSnapshot,
  Category,
  Holding,
  Transaction,
  TransactionAttachment,
  TransactionCount,
} from '../api/types'
import type { Route } from '../routing'
import {
  AmountDirectionToggle,
  EmptyState,
  Field,
  Icon,
  InstitutionLogo,
  Modal,
  Panel,
  StatusBadge,
  type TransactionDirection,
  chartTooltipStyle,
  compactMoney,
  directedAmount,
  errorMessage,
  formatDate,
  localDateInputValue,
  money,
  signedMoney,
} from '../ui'

const institutions = [
  'ABN AMRO',
  'Banca Intesa Sanpaolo',
  'Banco Santander',
  'Bank of Ireland',
  'Barclays',
  'BBVA',
  'BNP Paribas',
  'Boursobank',
  'Caisse d’Épargne',
  'Commerzbank',
  'Crédit Agricole',
  'Crédit Mutuel',
  'Danske Bank',
  'Deutsche Bank',
  'Fortuneo',
  'Hello bank!',
  'HSBC',
  'ING',
  'KBC',
  'La Banque Postale',
  'LCL',
  'Lloyds Bank',
  'Monabanq',
  'N26',
  'NatWest',
  'Raiffeisen Bank',
  'Revolut',
  'Société Générale',
  'Trade Republic',
  'UniCredit',
  'Volkswagen Bank',
  'Wise',
]
const accountTypeOptions = [
  { value: 'checking', label: 'Compte courant' },
  { value: 'savings', label: 'Épargne' },
  { value: 'investment', label: 'Investissement' },
  { value: 'pea', label: 'PEA' },
  { value: 'securities', label: 'Compte-titres' },
  { value: 'life_insurance', label: 'Assurance-vie' },
  { value: 'cash', label: 'Espèces' },
  { value: 'wallet', label: 'Wallet crypto' },
] as const
const positionAccountTypes = new Set([
  'investment',
  'pea',
  'securities',
  'life_insurance',
  'wallet',
])
const savingsProducts = [
  { name: 'Livret A', rate: '1.700', cap: '22950.00' },
  { name: 'LDDS', rate: '1.700', cap: '12000.00' },
  { name: 'LEP', rate: '2.500', cap: '10000.00' },
  { name: 'Livret Jeune', rate: '1.700', cap: '1600.00' },
  { name: 'CEL', rate: '1.250', cap: '15300.00' },
  { name: 'PEL', rate: '2.000', cap: '61200.00' },
] as const

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
  const [collapsedInstitutions, setCollapsedInstitutions] = useState<Set<string>>(new Set())
  const visibleAccounts = accounts.filter((account) => {
    return account.archived === showArchived && (typeFilter === 'all' || account.type === typeFilter)
  })
  const total = visibleAccounts.reduce((sum, account) => sum + Number(account.balance), 0)
  const transactionCount = visibleAccounts.reduce(
    (sum, account) => sum + account.transaction_count,
    0,
  )
  const types = [...new Set(accounts.map((account) => account.type))]
  const accountGroups = Object.entries(
    visibleAccounts.reduce<Record<string, Account[]>>((groups, account) => {
      const institution = account.institution?.trim() || 'Établissement non renseigné'
      groups[institution] = [...(groups[institution] ?? []), account]
      return groups
    }, {}),
  ).sort(([left], [right]) => left.localeCompare(right, 'fr'))
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
        <p>Soldes, historiques et relevés mensuels stockés dans votre base locale.</p>
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
          <p className="eyebrow">Total des comptes affichés</p>
          <p className="hero-value">{money(total)}</p>
          <div className="hero-detail">
            <span><Icon name="accounts" />{visibleAccounts.length} compte{visibleAccounts.length === 1 ? '' : 's'}</span>
            <span><Icon name="receipt" />{transactionCount} transaction{transactionCount === 1 ? '' : 's'}</span>
          </div>
        </div>
      </section>

      <div className="account-filter-groups">
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

      {accountGroups.length > 0 ? (
        <div className="institution-groups">
          {accountGroups.map(([institution, institutionAccounts]) => {
            const collapsed = collapsedInstitutions.has(institution)
            const institutionTotal = institutionAccounts.reduce(
              (sum, account) => sum + Number(account.balance),
              0,
            )
            return (
              <section className="institution-group" key={institution}>
                <button
                  aria-expanded={!collapsed}
                  className="institution-group-header"
                  type="button"
                  onClick={() => toggleInstitution(institution)}
                >
                  <span className="institution-group-identity">
                    <InstitutionLogo institution={institution === 'Établissement non renseigné' ? null : institution} />
                    <span>
                      <strong>{institution}</strong>
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
        <p>{account.institution || 'Établissement non renseigné'}</p>
      </div>
      <strong className="account-balance">{money(account.balance)}</strong>
      <div className="account-meta">
        <span>{account.transaction_count} transaction{account.transaction_count === 1 ? '' : 's'}</span>
        <span>Voir le détail <Icon name="arrow" /></span>
      </div>
    </button>
  )
}

export function AccountDetailView({
  accountId,
  accounts,
  categories,
  navigate,
  onRefresh,
}: {
  accountId: number
  accounts: Account[]
  categories: Category[]
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const transactionPageSize = 100
  const [transactionPage, setTransactionPage] = useState(0)
  const account = useQuery({
    queryKey: ['account', accountId],
    queryFn: () => apiGet<AccountDetail>(`/accounts/${accountId}`),
  })
  const transactions = useQuery({
    queryKey: ['transactions', 'account', accountId, transactionPage],
    queryFn: () => apiGet<Transaction[]>(`/transactions${queryString({
      account_id: accountId,
      limit: transactionPageSize,
      offset: transactionPage * transactionPageSize,
    })}`),
  })
  const snapshots = useQuery({
    queryKey: ['account-snapshots', accountId],
    queryFn: () => apiGet<AccountSnapshot[]>(`/accounts/${accountId}/snapshots`),
  })
  const uncategorizedCount = useQuery({
    queryKey: ['transaction-count', 'account', accountId, 'uncategorized'],
    queryFn: () => apiGet<TransactionCount>(`/transactions/count${queryString({
      account_id: accountId,
      uncategorized: true,
    })}`),
  })
  const positionsEnabled = positionAccountTypes.has(account.data?.type ?? '')
  const positions = useQuery({
    queryKey: ['holdings', 'account', accountId],
    queryFn: () => apiGet<Holding[]>(`/holdings${queryString({ account_id: accountId })}`),
    enabled: positionsEnabled,
  })
  const [showTransaction, setShowTransaction] = useState(false)
  const [showSnapshot, setShowSnapshot] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [showArchiveModal, setShowArchiveModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [transferTargetId, setTransferTargetId] = useState('')
  const [editingTransaction, setEditingTransaction] = useState<Transaction | null>(null)
  const errors = [
    account.error,
    transactions.error,
    snapshots.error,
    uncategorizedCount.error,
    positionsEnabled ? positions.error : null,
  ].filter(Boolean)

  useEffect(() => setTransactionPage(0), [accountId])

  const refreshDetail = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['transactions', 'account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['account-snapshots', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['holdings', 'account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['transaction-count', 'account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['transaction-count'] }),
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
      setShowTransaction(false)
      setEditingTransaction(null)
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
  const snapshotChartData = [...(snapshots.data ?? [])]
    .sort((left, right) => left.period.localeCompare(right.period))
    .map((snapshot) => ({ ...snapshot, balance: Number(snapshot.balance) }))
  const transferTargets = accounts.filter((candidate) => (
    candidate.id !== accountId
    && !candidate.archived
    && candidate.currency === account.data.currency
  ))
  const openArchiveModal = () => {
    setTransferTargetId(String(transferTargets[0]?.id ?? ''))
    setShowArchiveModal(true)
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
              onClick={() => setShowSnapshot((current) => !current)}
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
              <button className="text-button" type="button" onClick={() => setShowDeleteModal(false)}>
                Annuler
              </button>
            </>
          )}
        >
          <div className="modal-warning">
            <Icon name="alert" />
            <p>
              Un compte contenant des transactions, relevés, positions ou liens ne peut pas être
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
              <button
                className="secondary-button"
                type="button"
                disabled={archive.isPending}
                onClick={() => archive.mutate({ archived: true })}
              >
                Archiver sans transfert
              </button>
              <button className="text-button" type="button" onClick={() => setShowArchiveModal(false)}>
                Annuler
              </button>
            </>
          )}
        >
          {balance !== 0 && (
            <div className="modal-warning warning">
              <Icon name="alert" />
              <p>
                Ce compte possède encore un solde de <strong>{money(account.data.balance)}</strong>.
                Vérifiez-le avant de poursuivre.
              </p>
            </div>
          )}
          {balance > 0 && transferTargets.length > 0 && (
            <div className="archive-transfer">
              <Field label="Transférer les fonds vers">
                <select
                  value={transferTargetId}
                  onChange={(event) => setTransferTargetId(event.target.value)}
                >
                  {transferTargets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name} · {money(target.balance)}
                    </option>
                  ))}
                </select>
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

      {editingTransaction && !readOnly && (
        <TransactionEditModal
          categories={categories}
          transaction={editingTransaction}
          onClose={() => setEditingTransaction(null)}
          onSaved={async () => {
            setEditingTransaction(null)
            await refreshDetail()
          }}
        />
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

      {showSnapshot && !readOnly && (
        <Panel title="Nouveau relevé" subtitle="Enregistrez le solde de clôture d'un mois.">
          <SnapshotForm
            account={account.data}
            onCancel={() => setShowSnapshot(false)}
            onSaved={async () => {
              await refreshDetail()
              setShowSnapshot(false)
            }}
          />
        </Panel>
      )}

      <section className="account-detail-hero">
        <div className="detail-account-title">
          <InstitutionLogo institution={account.data.institution} />
          <strong>{account.data.name}</strong>
          <StatusBadge>{accountType(account.data.type)}</StatusBadge>
          {account.data.archived && <StatusBadge tone="warning">Archivé</StatusBadge>}
        </div>
        <p>Solde actuel</p>
        <strong>{money(account.data.balance)}</strong>
        <small>{account.data.institution || 'Établissement non renseigné'}</small>
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

      <Panel title="Relevés mensuels" subtitle={`${snapshots.data?.length ?? 0} relevé${snapshots.data?.length === 1 ? '' : 's'}`}>
        {(snapshots.data ?? []).length > 0 ? (
          <div className="statement-list">
            {[...(snapshots.data ?? [])].sort((left, right) => right.period.localeCompare(left.period)).map((snapshot) => (
              <SnapshotRow
                accountId={accountId}
                key={snapshot.id}
                snapshot={snapshot}
                onSaved={refreshDetail}
                readOnly={readOnly}
              />
            ))}
          </div>
        ) : (
          <EmptyState icon="calendar" text="Aucun relevé enregistré." />
        )}
      </Panel>

      <Panel
        title="Transactions"
        subtitle={`${account.data.transaction_count} mouvement${account.data.transaction_count === 1 ? '' : 's'}`}
        action={!readOnly ? (
          <button
            className="primary-button small-button"
            type="button"
            onClick={() => setShowTransaction((current) => !current)}
          >
            <Icon name="plus" /> Ajouter une transaction
          </button>
        ) : undefined}
      >
        {!readOnly && (uncategorizedCount.data?.count ?? 0) > 0 && (
          <div className="categorization-summary">
            <span className="categorization-summary-icon"><Icon name="sparkle" /></span>
            <span>
              <strong>Transactions à catégoriser</strong>
              <small>
                {uncategorizedCount.data?.count ?? 0} mouvement
                {(uncategorizedCount.data?.count ?? 0) === 1 ? '' : 's'} sans catégorie sur ce compte
              </small>
            </span>
            <button
              className="secondary-button small-button"
              type="button"
              onClick={() => navigate({ name: 'budget', tab: 'categorize' })}
            >
              Catégoriser <Icon name="arrow" />
            </button>
          </div>
        )}
        {showTransaction && !readOnly && (
          <AccountTransactionForm
            account={account.data}
            categories={categories}
            onCancel={() => setShowTransaction(false)}
            onSaved={async () => {
              await refreshDetail()
              setShowTransaction(false)
            }}
          />
        )}
        <div className="data-table-wrap">
          <table className="transaction-table">
            <thead><tr><th>Date</th><th>Libellé</th><th>Catégorie</th><th className="amount-column">Montant</th><th /></tr></thead>
            <tbody>
              {transactions.data?.map((transaction) => (
                <AccountTransactionRow
                  key={transaction.id}
                  transaction={transaction}
                  onEdit={() => setEditingTransaction(transaction)}
                  onSaved={refreshDetail}
                  readOnly={readOnly}
                />
              ))}
            </tbody>
          </table>
          {(transactions.data?.length ?? 0) === 0 && <EmptyState icon="receipt" text="Aucune transaction sur ce compte." />}
        </div>
        {account.data.transaction_count > transactionPageSize && (
          <div className="pagination">
            <button
              className="secondary-button small-button"
              type="button"
              disabled={transactionPage === 0}
              onClick={() => setTransactionPage((current) => current - 1)}
            >
              <Icon name="back" />Précédent
            </button>
            <span>
              Page {transactionPage + 1} sur {Math.ceil(account.data.transaction_count / transactionPageSize)}
            </span>
            <button
              className="secondary-button small-button"
              type="button"
              disabled={(transactionPage + 1) * transactionPageSize >= account.data.transaction_count}
              onClick={() => setTransactionPage((current) => current + 1)}
            >
              Suivant<Icon name="arrow" />
            </button>
          </div>
        )}
        {!readOnly && <div className="account-delete-action">
          <button
            className="text-button destructive-button"
            type="button"
            disabled={remove.isPending}
            onClick={() => setShowDeleteModal(true)}
          >
            <Icon name="trash" /> Supprimer ce compte
          </button>
          <small>La suppression est disponible uniquement si le compte ne contient aucun historique ni lien.</small>
        </div>}
      </Panel>
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
  if (editing) {
    return (
      <div className="statement-row editing">
        <input
          aria-label="Période du relevé"
          type="month"
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
          required
        />
        <input
          aria-label="Solde du relevé"
          type="number"
          step="0.01"
          value={balance}
          onChange={(event) => setBalance(event.target.value)}
          required
        />
        <span className="row-actions">
          <button
            className="icon-action positive"
            type="button"
            aria-label="Enregistrer le relevé"
            disabled={update.isPending}
            onClick={() => update.mutate()}
          >
            <Icon name="check" />
          </button>
          <button className="icon-action" type="button" aria-label="Annuler" onClick={() => setEditing(false)}>
            <Icon name="close" />
          </button>
        </span>
        {update.error && <span className="form-error row-error">{errorMessage(update.error)}</span>}
      </div>
    )
  }
  return (
    <div className="statement-row">
      <span>{snapshot.period}</span>
      <strong>{money(snapshot.balance)}</strong>
      {!readOnly && (
        <span className="row-actions">
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
        </span>
      )}
      {remove.error && <span className="form-error row-error">{errorMessage(remove.error)}</span>}
    </div>
  )
}

function AccountTransactionRow({
  transaction,
  onEdit,
  onSaved,
  readOnly,
}: {
  transaction: Transaction
  onEdit: () => void
  onSaved: () => Promise<void>
  readOnly: boolean
}) {
  const [showAttachments, setShowAttachments] = useState(false)
  const linkedTransfer = transaction.transfer_group !== null
  const remove = useMutation({
    mutationFn: () => apiDelete(`/transactions/${transaction.id}`),
    onSuccess: onSaved,
  })
  return (
    <>
      <tr>
        <td data-label="Date">{formatDate(transaction.booked_at)}</td>
        <td data-label="Libellé">
          <strong>{transaction.description}</strong>
          {transaction.notes && <small>{transaction.notes}</small>}
        </td>
        <td data-label="Catégorie">
          {linkedTransfer ? <StatusBadge>Transfert interne</StatusBadge> : transaction.category_name ?? 'Sans catégorie'}
        </td>
        <td
          data-label="Montant"
          className={`amount-column ${Number(transaction.amount) >= 0 ? 'positive' : 'negative'}`}
        >
          {signedMoney(transaction.amount)}
        </td>
        <td data-label="Actions" className="row-actions">
          {(!readOnly || transaction.attachment_count > 0) && (
            <button
              className="icon-action attachment-button"
              type="button"
              aria-label={`Pièces jointes${transaction.attachment_count > 0 ? ` (${transaction.attachment_count})` : ''}`}
              aria-expanded={showAttachments}
              onClick={() => setShowAttachments((current) => !current)}
            >
              <Icon name="attachment" />
              {transaction.attachment_count > 0 && (
                <span className="attachment-count-badge">{transaction.attachment_count}</span>
              )}
            </button>
          )}
          {!readOnly && (
            <>
              <button
                className="icon-action"
                type="button"
                aria-label="Modifier la transaction"
                disabled={linkedTransfer}
                title={linkedTransfer ? "Un transfert lié n'est pas modifiable" : undefined}
                onClick={onEdit}
              >
                <Icon name="edit" />
              </button>
              <button
                className="icon-action"
                type="button"
                aria-label="Supprimer la transaction"
                disabled={linkedTransfer || remove.isPending}
                title={linkedTransfer ? "Un transfert lié n'est pas supprimable individuellement" : undefined}
                onClick={() => {
                  if (window.confirm('Supprimer définitivement cette transaction ?')) remove.mutate()
                }}
              >
                <Icon name="trash" />
              </button>
            </>
          )}
          {remove.error && <span className="form-error">{errorMessage(remove.error)}</span>}
        </td>
      </tr>
      {showAttachments && (
        <tr className="attachment-table-row">
          <td colSpan={5}>
            <AttachmentManager readOnly={readOnly} transactionId={transaction.id} />
          </td>
        </tr>
      )}
    </>
  )
}

function AttachmentManager({
  transactionId,
  readOnly,
}: {
  transactionId: number
  readOnly: boolean
}) {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [inputKey, setInputKey] = useState(0)
  const attachments = useQuery({
    queryKey: ['transaction-attachments', transactionId],
    queryFn: () => apiGet<TransactionAttachment[]>(`/transactions/${transactionId}/attachments`),
  })
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['transaction-attachments', transactionId] }),
    queryClient.invalidateQueries({ queryKey: ['transactions'] }),
  ])
  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('Choisissez un fichier à joindre.')
      const data = new FormData()
      data.append('file', file)
      return apiUpload<TransactionAttachment>(`/transactions/${transactionId}/attachments`, data)
    },
    onSuccess: async () => {
      setFile(null)
      setInputKey((current) => current + 1)
      await refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (attachmentId: number) => apiDelete(
      `/transactions/${transactionId}/attachments/${attachmentId}`,
    ),
    onSuccess: refresh,
  })
  return (
    <div className="attachment-manager">
      <div className="attachment-heading">
        <span>
          <strong>Pièces jointes</strong>
          <small>Stockage local, 25 Mio maximum par fichier.</small>
        </span>
        {!readOnly && (
          <form
            className="attachment-upload"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              upload.mutate()
            }}
          >
            <input
              key={inputKey}
              aria-label="Choisir une pièce jointe"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <button className="secondary-button small-button" type="submit" disabled={!file || upload.isPending}>
              <Icon name="attachment" /> Joindre
            </button>
          </form>
        )}
      </div>
      {attachments.isLoading ? (
        <p className="attachment-empty">Chargement…</p>
      ) : (attachments.data ?? []).length > 0 ? (
        <div className="attachment-list">
          {attachments.data?.map((attachment) => (
            <div key={attachment.id}>
              <Icon name="attachment" />
              <span>
                <a href={`/api/transactions/${transactionId}/attachments/${attachment.id}/download`}>
                  {attachment.original_name}
                </a>
                <small>{formatFileSize(attachment.size)}</small>
              </span>
              {!readOnly && (
                <button
                  className="icon-action"
                  type="button"
                  aria-label={`Supprimer ${attachment.original_name}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(attachment.id)}
                >
                  <Icon name="trash" />
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="attachment-empty">Aucune pièce jointe.</p>
      )}
      {(attachments.error || upload.error || remove.error) && (
        <p className="form-error">{errorMessage(attachments.error ?? upload.error ?? remove.error)}</p>
      )}
    </div>
  )
}

function TransactionEditModal({
  transaction,
  categories,
  onClose,
  onSaved,
}: {
  transaction: Transaction
  categories: Category[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [bookedAt, setBookedAt] = useState(transaction.booked_at)
  const [description, setDescription] = useState(transaction.description)
  const [direction, setDirection] = useState<TransactionDirection>(
    Number(transaction.amount) >= 0 ? 'deposit' : 'withdrawal',
  )
  const [amount, setAmount] = useState(String(Math.abs(Number(transaction.amount))))
  const [categoryId, setCategoryId] = useState(String(transaction.category_id ?? ''))
  const [notes, setNotes] = useState(transaction.notes ?? '')
  const update = useMutation({
    mutationFn: () => apiPatch<Transaction>(`/transactions/${transaction.id}`, {
      booked_at: bookedAt,
      description,
      amount: directedAmount(amount, direction),
      category_id: categoryId ? Number(categoryId) : null,
      notes: notes || null,
    }),
    onSuccess: onSaved,
  })
  const formId = `transaction-edit-${transaction.id}`
  return (
    <Modal
      title="Modifier la transaction"
      description="Mettez à jour les informations du mouvement."
      onClose={onClose}
      actions={(
        <>
          <button className="primary-button" type="submit" form={formId} disabled={update.isPending}>
            Enregistrer
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form
        className="modal-form"
        id={formId}
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          update.mutate()
        }}
      >
        <AmountDirectionToggle value={direction} onChange={setDirection} />
        <Field label="Date">
          <input type="date" value={bookedAt} onChange={(event) => setBookedAt(event.target.value)} required />
        </Field>
        <Field label="Libellé">
          <input value={description} onChange={(event) => setDescription(event.target.value)} required />
        </Field>
        <Field label="Montant">
          <input type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        </Field>
        <Field label="Catégorie">
          <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Sans catégorie</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>{category.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Note">
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />
        </Field>
        {update.error && <p className="form-error">{errorMessage(update.error)}</p>}
      </form>
    </Modal>
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
                const gainPercent = Number(holding.cost_basis) > 0
                  ? (Number(holding.gain) / Number(holding.cost_basis)) * 100
                  : 0
                const gainTone = Number(holding.gain) >= 0 ? 'positive' : 'negative'
                return (
                  <tr key={holding.id}>
                    <td data-label="Ticker"><strong>{holding.symbol || '—'}</strong></td>
                    <td data-label="Nom">{holding.name}</td>
                    <td data-label="Quantité" className="amount-column">{formatQuantity(holding.quantity)}</td>
                    <td data-label="Prix moyen d'achat" className="amount-column">{money(holding.average_price)}</td>
                    <td data-label="Prix du titre" className="amount-column">{money(holding.current_price)}</td>
                    <td data-label="Valeur" className="amount-column">{money(holding.market_value)}</td>
                    <td data-label="Plus-value / Moins-value" className={`amount-column ${gainTone}`}>{signedMoney(holding.gain)}</td>
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
    onSuccess: onSaved,
  })
  const currentBalance = Math.max(0, Number(account.balance))
  const projectedBalance = currentBalance * (1 + Number(annualRate || 0) / 100)
  const cap = Number(legalCap || 0)
  const chartData: Array<{
    period: string
    balance?: number
    projection?: number
  }> = snapshots.map((snapshot) => ({ ...snapshot }))
  const latestSnapshot = chartData.at(-1)
  if (latestSnapshot) latestSnapshot.projection = latestSnapshot.balance
  chartData.push(
    { period: "Aujourd'hui", projection: currentBalance },
    { period: 'Dans 1 an', projection: projectedBalance },
  )
  return (
    <Panel
      title="Historique et projection"
      subtitle="Relevés mensuels et projection à un an, hors nouveaux versements."
      action={!readOnly ? (
        <button
          className="secondary-button small-button"
          type="button"
          onClick={() => setShowConfig((current) => !current)}
        >
          <Icon name={showConfig ? 'close' : 'settings'} />
          {showConfig ? 'Masquer' : 'Configurer'}
        </button>
      ) : undefined}
    >
      {showConfig && !readOnly && (
        <>
          <form
            className="savings-config-form"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              mutation.mutate()
            }}
          >
            <Field label="Produit">
              <select
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
              </select>
            </Field>
            <Field label="Taux annuel">
              <div className="input-with-suffix">
                <input
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
              <input
                type="number"
                min="0"
                step="0.01"
                value={legalCap}
                onChange={(event) => setLegalCap(event.target.value)}
                required
              />
            </Field>
            <button className="primary-button" type="submit" disabled={mutation.isPending}>
              Enregistrer la configuration
            </button>
          </form>
          {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
        </>
      )}
      <div className="savings-metrics">
        <article>
          <span>Solde actuel</span>
          <strong>{money(currentBalance)}</strong>
        </article>
        <article>
          <span>Plafond légal</span>
          <strong>{money(cap)}</strong>
        </article>
        <article>
          <span>Projection dans 1 an</span>
          <strong>{money(projectedBalance)}</strong>
          <small>+{money(projectedBalance - currentBalance)} d'intérêts estimés</small>
        </article>
      </div>
      <div className="chart-container savings-history-chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
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
            <Area
              dataKey="projection"
              dot={{ fill: '#615fff', r: 4 }}
              fill="transparent"
              name="Projection"
              stroke="#615fff"
              strokeDasharray="7 7"
              strokeWidth={2.5}
              type="monotone"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend savings-history-legend">
        <span><i className="legend-line" /> Relevés</span>
        <span><i className="legend-line projection" /> Projection</span>
      </div>
    </Panel>
  )
}

function AccountForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [institution, setInstitution] = useState('')
  const [initialBalance, setInitialBalance] = useState('0')
  const mutation = useMutation({
    mutationFn: () => apiPost<Account>('/accounts', {
      name,
      type,
      currency: 'EUR',
      institution: institution || null,
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
        <Field label="Nom"><input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></Field>
        <InstitutionField institution={institution} onChange={setInstitution} />
        <Field label="Type">
          <select value={type} onChange={(event) => setType(event.target.value)}>
            {accountTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Solde initial"><input type="number" step="0.01" value={initialBalance} onChange={(event) => setInitialBalance(event.target.value)} required /></Field>
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
  const [initialBalance, setInitialBalance] = useState(account.initial_balance)
  const mutation = useMutation({
    mutationFn: () => apiPatch<Account>(`/accounts/${account.id}`, {
      name,
      type,
      institution: institution || null,
      initial_balance: initialBalance,
      ...(type === 'savings' && account.type !== 'savings' ? {
        savings_product: savingsProducts[0].name,
        annual_interest_rate: savingsProducts[0].rate,
        legal_cap: savingsProducts[0].cap,
      } : {}),
    }),
    onSuccess: onSaved,
  })
  return (
    <Panel title="Modifier le compte">
      <form className="inline-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom"><input value={name} onChange={(event) => setName(event.target.value)} required /></Field>
        <InstitutionField institution={institution} onChange={setInstitution} />
        <Field label="Type">
          <select value={type} onChange={(event) => setType(event.target.value)}>
            {accountTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Solde initial"><input type="number" step="0.01" value={initialBalance} onChange={(event) => setInitialBalance(event.target.value)} required /></Field>
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
  onChange,
}: {
  institution: string
  onChange: (value: string) => void
}) {
  const isKnown = institutions.includes(institution)
  const [isOther, setIsOther] = useState(Boolean(institution) && !isKnown)
  const selection = isOther ? 'other' : institution
  return (
    <>
      <Field label="Établissement">
        <select
          aria-label="Établissement"
          value={selection}
          onChange={(event) => {
            const value = event.target.value
            setIsOther(value === 'other')
            if (value !== 'other') onChange(value)
          }}
        >
          <option value="">Non renseigné</option>
          {institutions.map((item) => <option key={item} value={item}>{item}</option>)}
          <option value="other">Autre…</option>
        </select>
      </Field>
      {isOther && (
        <Field label="Autre établissement">
          <input
            aria-label="Autre établissement"
            value={institution}
            onChange={(event) => onChange(event.target.value)}
            maxLength={120}
            required
          />
        </Field>
      )}
    </>
  )
}

function AccountTransactionForm({
  account,
  categories,
  onCancel,
  onSaved,
}: {
  account: Account
  categories: Category[]
  onCancel: () => void
  onSaved: () => Promise<void>
}) {
  const [date, setDate] = useState(localDateInputValue)
  const [description, setDescription] = useState('')
  const [direction, setDirection] = useState<TransactionDirection>('withdrawal')
  const [amount, setAmount] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Transaction>('/transactions', {
      booked_at: date,
      description,
      amount: directedAmount(amount, direction),
      account_id: account.id,
      category_id: categoryId ? Number(categoryId) : null,
      notes: null,
    }),
    onSuccess: onSaved,
  })
  return (
    <div className="account-transaction-form">
      <AmountDirectionToggle value={direction} onChange={setDirection} />
      <form className="inline-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Date"><input type="date" value={date} onChange={(event) => setDate(event.target.value)} required /></Field>
        <Field label="Libellé"><input value={description} onChange={(event) => setDescription(event.target.value)} required /></Field>
        <Field label="Montant"><input type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></Field>
        <Field label="Catégorie">
          <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Sans catégorie</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending}>Ajouter</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </div>
  )
}

function SnapshotForm({ account, onCancel, onSaved }: { account: Account; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [date, setDate] = useState(localDateInputValue)
  const [balance, setBalance] = useState(account.balance)
  const mutation = useMutation({
    mutationFn: () => apiPut<AccountSnapshot>(`/accounts/${account.id}/snapshots`, { period: date.slice(0, 7), balance }),
    onSuccess: onSaved,
  })
  return (
    <form className="compact-feature-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
      <input type="number" step="0.01" value={balance} onChange={(event) => setBalance(event.target.value)} required />
      <button className="primary-button small-button" type="submit" disabled={mutation.isPending}>Enregistrer</button>
      <button className="text-button" type="button" onClick={onCancel}>Annuler</button>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </form>
  )
}

function accountType(type: string): string {
  return accountTypeOptions.find((option) => option.value === type)?.label ?? type
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

function formatFileSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Mio`
  if (size >= 1024) return `${(size / 1024).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Kio`
  return `${size} octet${size === 1 ? '' : 's'}`
}
