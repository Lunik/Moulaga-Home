import { FormEvent, useState } from 'react'
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

import { apiGet, apiPatch, apiPost, apiPut, queryString } from '../api/client'
import type { Account, AccountDetail, AccountPocket, AccountSnapshot, Category, Transaction } from '../api/types'
import type { Route } from '../routing'
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

const accountColors = ['#615fff', '#16c79a', '#1da9e8', '#f97316', '#8758f6', '#ec4899']

export function AccountsView({
  accounts,
  transactions,
  navigate,
  onRefresh,
}: {
  accounts: Account[]
  transactions: Transaction[]
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  const [showForm, setShowForm] = useState(false)
  const [typeFilter, setTypeFilter] = useState('all')
  const visibleAccounts = accounts.filter((account) => !account.archived && (typeFilter === 'all' || account.type === typeFilter))
  const total = visibleAccounts.reduce((sum, account) => sum + Number(account.balance), 0)
  const types = [...new Set(accounts.map((account) => account.type))]

  return (
    <div className="view-stack">
      <section className="section-intro">
        <p>Soldes, historiques et poches virtuelles stockés dans votre base locale.</p>
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
            <span><Icon name="receipt" />{transactions.length} transaction{transactions.length === 1 ? '' : 's'}</span>
          </div>
        </div>
      </section>

      <nav className="filter-tabs" aria-label="Types de comptes">
        <button className={typeFilter === 'all' ? 'active' : ''} type="button" onClick={() => setTypeFilter('all')}>Tous</button>
        {types.map((type) => (
          <button className={typeFilter === type ? 'active' : ''} type="button" key={type} onClick={() => setTypeFilter(type)}>
            {accountType(type)}
          </button>
        ))}
      </nav>

      <section className="account-grid">
        {visibleAccounts.map((account, index) => {
          const transactionCount = transactions.filter((transaction) => transaction.account_id === account.id).length
          return (
            <button className="account-card interactive-card" type="button" key={account.id} onClick={() => navigate({ name: 'account', accountId: account.id })}>
              <div className="account-card-head">
                <span className="account-avatar" style={{ background: account.color ?? accountColors[index % accountColors.length] }}>
                  {initials(account.name)}
                </span>
                <StatusBadge>{accountType(account.type)}</StatusBadge>
              </div>
              <div className="account-card-copy">
                <h2>{account.name}</h2>
                <p>{account.institution || 'Établissement non renseigné'}</p>
              </div>
              <strong className="account-balance">{money(account.balance)}</strong>
              <div className="account-meta">
                <span>{transactionCount} transaction{transactionCount === 1 ? '' : 's'}</span>
                <span>Voir le détail <Icon name="arrow" /></span>
              </div>
            </button>
          )
        })}
        {visibleAccounts.length === 0 && <EmptyState icon="accounts" text="Aucun compte pour ce filtre." />}
      </section>
    </div>
  )
}

export function AccountDetailView({
  accountId,
  categories,
  navigate,
  onRefresh,
}: {
  accountId: number
  categories: Category[]
  navigate: (route: Route) => void
  onRefresh: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const account = useQuery({
    queryKey: ['account', accountId],
    queryFn: () => apiGet<AccountDetail>(`/accounts/${accountId}`),
  })
  const transactions = useQuery({
    queryKey: ['transactions', 'account', accountId],
    queryFn: () => apiGet<Transaction[]>(`/transactions${queryString({ account_id: accountId, limit: 1000 })}`),
  })
  const snapshots = useQuery({
    queryKey: ['account-snapshots', accountId],
    queryFn: () => apiGet<AccountSnapshot[]>(`/accounts/${accountId}/snapshots`),
  })
  const pockets = useQuery({
    queryKey: ['account-pockets', accountId],
    queryFn: () => apiGet<AccountPocket[]>(`/accounts/${accountId}/pockets`),
  })
  const [showTransaction, setShowTransaction] = useState(false)
  const [showSnapshot, setShowSnapshot] = useState(false)
  const [showPocket, setShowPocket] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const errors = [account.error, transactions.error, snapshots.error, pockets.error].filter(Boolean)

  const refreshDetail = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['transactions', 'account', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['account-snapshots', accountId] }),
      queryClient.invalidateQueries({ queryKey: ['account-pockets', accountId] }),
      onRefresh(),
    ])
  }

  if (account.isLoading) return <div className="loading-card">Chargement du compte…</div>
  if (!account.data) return <div className="error-banner">{errors.length > 0 ? errorMessage(errors[0]) : 'Compte introuvable.'}</div>

  return (
    <div className="view-stack">
      <section className="detail-heading">
        <button className="secondary-button" type="button" onClick={() => navigate({ name: 'accounts' })}>
          <Icon name="back" /> Retour
        </button>
        <div className="header-actions">
          <button className="secondary-button" type="button" onClick={() => setShowEdit((current) => !current)}>
            <Icon name="edit" /> Modifier
          </button>
          <button className="primary-button" type="button" onClick={() => setShowTransaction((current) => !current)}>
            <Icon name="plus" /> Transaction
          </button>
        </div>
      </section>

      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}

      {showEdit && (
        <EditAccountForm
          account={account.data}
          onCancel={() => setShowEdit(false)}
          onSaved={async () => {
            await refreshDetail()
            setShowEdit(false)
          }}
        />
      )}
      {showTransaction && (
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

      <section className="account-detail-hero">
        <div className="detail-account-title">
          <i style={{ background: account.data.color ?? '#615fff' }} />
          <strong>{account.data.name}</strong>
          <StatusBadge>{accountType(account.data.type)}</StatusBadge>
        </div>
        <p>Solde actuel</p>
        <strong>{money(account.data.balance)}</strong>
        <small>{account.data.institution || 'Établissement non renseigné'}</small>
      </section>

      <Panel
        title="Historique"
        subtitle="Relevés mensuels persistants"
        action={(
          <button className="secondary-button small-button" type="button" onClick={() => setShowSnapshot((current) => !current)}>
            <Icon name="calendar" /> Ajouter un relevé
          </button>
        )}
      >
        {showSnapshot && (
          <SnapshotForm
            account={account.data}
            onCancel={() => setShowSnapshot(false)}
            onSaved={async () => {
              await refreshDetail()
              setShowSnapshot(false)
            }}
          />
        )}
        <div className="chart-container account-history-chart">
          {(snapshots.data?.length ?? 0) > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={[...(snapshots.data ?? [])].sort((left, right) => left.period.localeCompare(right.period))}>
                <defs>
                  <linearGradient id="account-history-fill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                <Tooltip contentStyle={chartTooltipStyle} labelFormatter={(value) => String(value)} formatter={(value) => money(Number(value))} />
                <Area dataKey="balance" type="monotone" stroke="#16c79a" strokeWidth={2.5} fill="url(#account-history-fill)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon="calendar" text="Ajoutez le premier relevé mensuel pour construire l'historique." />
          )}
        </div>
      </Panel>

      <section className="dashboard-grid lower-grid">
        <Panel
          title="Poches"
          subtitle="Affectations virtuelles, sans modifier le solde réel"
          action={(
            <button className="secondary-button small-button" type="button" onClick={() => setShowPocket((current) => !current)}>
              <Icon name="plus" /> Nouvelle poche
            </button>
          )}
        >
          {showPocket && (
            <PocketForm
              accountId={accountId}
              onCancel={() => setShowPocket(false)}
              onSaved={async () => {
                await refreshDetail()
                setShowPocket(false)
              }}
            />
          )}
          {(pockets.data ?? []).length > 0 ? (
            <div className="pocket-list">
              {pockets.data?.map((pocket) => {
                const ratio = Number(pocket.target ?? 0) > 0
                  ? (Number(pocket.allocated) / Number(pocket.target)) * 100
                  : 0
                return (
                  <article key={pocket.id}>
                    <div><i style={{ background: pocket.color }} /><strong>{pocket.name}</strong></div>
                    <strong>{money(pocket.allocated)}</strong>
                    {pocket.target && (
                      <>
                        <ProgressBar value={ratio} color={pocket.color} />
                        <small>Objectif {money(pocket.target)}</small>
                      </>
                    )}
                  </article>
                )
              })}
            </div>
          ) : (
            <EmptyState icon="target" text="Aucune poche virtuelle sur ce compte." />
          )}
        </Panel>

        <Panel title="Relevés mensuels" subtitle={`${snapshots.data?.length ?? 0} relevé${snapshots.data?.length === 1 ? '' : 's'}`}>
          {(snapshots.data ?? []).length > 0 ? (
            <div className="statement-list">
              {[...(snapshots.data ?? [])].sort((left, right) => right.period.localeCompare(left.period)).map((snapshot) => (
                <div key={snapshot.id}>
                  <span>{snapshot.period}</span>
                  <strong>{money(snapshot.balance)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon="calendar" text="Aucun relevé enregistré." />
          )}
        </Panel>
      </section>

      <Panel title="Transactions" subtitle={`${transactions.data?.length ?? 0} mouvement${transactions.data?.length === 1 ? '' : 's'}`}>
        <div className="data-table-wrap">
          <table className="transaction-table">
            <thead><tr><th>Date</th><th>Libellé</th><th>Catégorie</th><th className="amount-column">Montant</th></tr></thead>
            <tbody>
              {transactions.data?.map((transaction) => (
                <tr key={transaction.id}>
                  <td data-label="Date">{formatDate(transaction.booked_at)}</td>
                  <td data-label="Libellé"><strong>{transaction.description}</strong>{transaction.notes && <small>{transaction.notes}</small>}</td>
                  <td data-label="Catégorie">{transaction.category_name ?? 'Sans catégorie'}</td>
                  <td data-label="Montant" className={`amount-column ${Number(transaction.amount) >= 0 ? 'positive' : 'negative'}`}>{signedMoney(transaction.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(transactions.data?.length ?? 0) === 0 && <EmptyState icon="receipt" text="Aucune transaction sur ce compte." />}
        </div>
      </Panel>
    </div>
  )
}

function AccountForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [institution, setInstitution] = useState('')
  const [initialBalance, setInitialBalance] = useState('0')
  const [color, setColor] = useState('#615fff')
  const mutation = useMutation({
    mutationFn: () => apiPost<Account>('/accounts', {
      name,
      type,
      currency: 'EUR',
      institution: institution || null,
      initial_balance: initialBalance,
      color,
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
        <Field label="Établissement"><input value={institution} onChange={(event) => setInstitution(event.target.value)} maxLength={120} /></Field>
        <Field label="Type">
          <select value={type} onChange={(event) => setType(event.target.value)}>
            <option value="checking">Compte courant</option>
            <option value="savings">Épargne</option>
            <option value="investment">Investissement</option>
            <option value="cash">Espèces</option>
          </select>
        </Field>
        <Field label="Solde initial"><input type="number" step="0.01" value={initialBalance} onChange={(event) => setInitialBalance(event.target.value)} required /></Field>
        <Field label="Couleur"><input className="color-input" type="color" value={color} onChange={(event) => setColor(event.target.value)} /></Field>
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
  const [institution, setInstitution] = useState(account.institution ?? '')
  const [color, setColor] = useState(account.color ?? '#615fff')
  const [archived, setArchived] = useState(account.archived ?? false)
  const mutation = useMutation({
    mutationFn: () => apiPatch<Account>(`/accounts/${account.id}`, {
      name,
      institution: institution || null,
      color,
      archived,
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
        <Field label="Établissement"><input value={institution} onChange={(event) => setInstitution(event.target.value)} /></Field>
        <Field label="Couleur"><input className="color-input" type="color" value={color} onChange={(event) => setColor(event.target.value)} /></Field>
        <label className="checkbox-field"><input type="checkbox" checked={archived} onChange={(event) => setArchived(event.target.checked)} />Archiver ce compte</label>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit">Enregistrer</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
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
  const [amount, setAmount] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Transaction>('/transactions', {
      booked_at: date,
      description,
      amount,
      account_id: account.id,
      category_id: categoryId ? Number(categoryId) : null,
      notes: null,
    }),
    onSuccess: onSaved,
  })
  return (
    <Panel title={`Nouvelle transaction · ${account.name}`}>
      <form className="inline-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Date"><input type="date" value={date} onChange={(event) => setDate(event.target.value)} required /></Field>
        <Field label="Libellé"><input value={description} onChange={(event) => setDescription(event.target.value)} required /></Field>
        <Field label="Montant"><input type="number" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required /></Field>
        <Field label="Catégorie">
          <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">Sans catégorie</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit">Ajouter</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
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
      <button className="primary-button small-button" type="submit">Enregistrer</button>
      <button className="text-button" type="button" onClick={onCancel}>Annuler</button>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </form>
  )
}

function PocketForm({ accountId, onCancel, onSaved }: { accountId: number; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [allocated, setAllocated] = useState('')
  const [target, setTarget] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<AccountPocket>(`/accounts/${accountId}/pockets`, {
      name,
      allocated,
      target: target || null,
      color: '#314ac8',
    }),
    onSuccess: onSaved,
  })
  return (
    <form className="compact-feature-form pocket-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <input placeholder="Nom" value={name} onChange={(event) => setName(event.target.value)} required />
      <input type="number" min="0" step="0.01" placeholder="Affecté" value={allocated} onChange={(event) => setAllocated(event.target.value)} required />
      <input type="number" min="0" step="0.01" placeholder="Objectif" value={target} onChange={(event) => setTarget(event.target.value)} />
      <button className="primary-button small-button" type="submit">Créer</button>
      <button className="text-button" type="button" onClick={onCancel}>Annuler</button>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </form>
  )
}

function accountType(type: string): string {
  return {
    checking: 'Compte courant',
    savings: 'Épargne',
    investment: 'Investissement',
    cash: 'Espèces',
  }[type] ?? type
}
