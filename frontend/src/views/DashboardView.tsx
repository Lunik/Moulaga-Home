import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiGet } from '../api/client'
import type {
  Account,
  Debt,
  MerchantIdentity,
  NetWorthPoint,
  NetWorthSummary,
  PortfolioSummary,
  Transaction,
} from '../api/types'
import type { Route } from '../routing'
import {
  EmptyState,
  Icon,
  MerchantAvatar,
  Panel,
  ProgressBar,
  chartTooltipStyle,
  compactMoney,
  formatDate,
  initials,
  money,
  signedMoney,
} from '../ui'
import { useQuery } from '@tanstack/react-query'

const colors = ['#16c79a', '#615fff', '#1da9e8', '#f97316', '#8758f6', '#ec4899']

export function DashboardView({
  accounts,
  merchants,
  transactions,
  navigate,
}: {
  accounts: Account[]
  merchants: MerchantIdentity[]
  transactions: Transaction[]
  navigate: (route: Route) => void
}) {
  const netWorth = useQuery({
    queryKey: ['net-worth'],
    queryFn: () => apiGet<NetWorthSummary>('/networth/overview'),
  })
  const portfolio = useQuery({
    queryKey: ['wealth-summary'],
    queryFn: () => apiGet<PortfolioSummary>('/portfolio/summary'),
  })
  const history = useQuery({
    queryKey: ['net-worth-history'],
    queryFn: () => apiGet<NetWorthPoint[]>('/networth/history'),
  })
  const debts = useQuery({
    queryKey: ['debts'],
    queryFn: () => apiGet<Debt[]>('/debts'),
  })
  const allocation = accounts
    .filter((account) => !account.archived && Number(account.balance) > 0)
    .map((account, index) => ({
      name: account.name,
      value: Number(account.balance),
      color: account.color ?? colors[index % colors.length],
    }))
  const activeDebts = (debts.data ?? []).filter((debt) => !debt.archived)
  const firstError = [netWorth.error, history.error, portfolio.error, debts.error].find(Boolean)
  const assets = Number(netWorth.data?.cash ?? 0) + Number(netWorth.data?.investments ?? 0)
  const gainPercent = Number(portfolio.data?.cost_basis ?? 0) > 0
    ? (Number(portfolio.data?.gain ?? 0) / Number(portfolio.data?.cost_basis ?? 0)) * 100
    : 0

  return (
    <div className="view-stack">
      {firstError && <div className="error-banner">{firstError instanceof Error ? firstError.message : 'Impossible de charger le patrimoine.'}</div>}
      <section className="wealth-hero dashboard-wealth-hero">
        <div>
          <p className="eyebrow">Patrimoine total</p>
          <p className="hero-value">{money(netWorth.data?.net_worth)}</p>
          <div className="wealth-equation">
            <span>Total des actifs <strong>{money(assets)}</strong></span>
            <i>−</i>
            <span>Total des dettes <strong className="negative">{money(netWorth.data?.debts)}</strong></span>
          </div>
          <span className={Number(portfolio.data?.gain ?? 0) >= 0 ? 'portfolio-change positive' : 'portfolio-change negative'}>
            <Icon name="trend" />{signedMoney(portfolio.data?.gain ?? 0)} ({gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%)
          </span>
        </div>
        <button className="secondary-button" type="button" onClick={() => navigate({ name: 'wealth', tab: 'overview' })}>
          Voir le patrimoine <Icon name="arrow" />
        </button>
      </section>

      <section className="dashboard-grid">
        <Panel title="Évolution du patrimoine net" subtitle="Actifs moins dettes">
          <div className="chart-container">
            {(history.data?.length ?? 0) > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history.data} margin={{ top: 12, right: 10, left: -8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="dashboard-net-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
                  <Area dataKey="net_worth" name="Patrimoine" type="monotone" stroke="#16c79a" strokeWidth={2.5} fill="url(#dashboard-net-fill)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState icon="trend" text="Les relevés mensuels construiront cette courbe." />
            )}
          </div>
        </Panel>
        <Panel title="Répartition des comptes" subtitle={`${allocation.length} compte${allocation.length === 1 ? '' : 's'} avec un solde positif`}>
          <div className="distribution-layout">
            <div className="donut-container">
              {allocation.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={allocation} dataKey="value" innerRadius="64%" outerRadius="88%" paddingAngle={2} stroke="none">
                        {allocation.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                      </Pie>
                      <Tooltip contentStyle={chartTooltipStyle} formatter={(value) => money(Number(value))} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-label"><strong>{allocation.length}</strong><span>comptes</span></div>
                </>
              ) : (
                <EmptyState icon="accounts" text="Aucun solde positif à répartir." />
              )}
            </div>
            <div className="distribution-list">
              {allocation.slice(0, 6).map((entry) => (
                <div key={entry.name}><span><i style={{ background: entry.color }} />{entry.name}</span><strong>{money(entry.value)}</strong></div>
              ))}
            </div>
          </div>
        </Panel>
      </section>

      {activeDebts.length > 0 && (
        <Panel title="Dettes" subtitle={`Total restant : ${money(activeDebts.reduce((sum, debt) => sum + Number(debt.balance), 0))}`}>
          <div className="debt-list compact-debts">
            {activeDebts.slice(0, 3).map((debt) => (
              <article key={debt.id}>
                <div className="debt-head"><span><i style={{ background: debt.color ?? '#ff6b70' }} /><strong>{debt.name}</strong></span><strong className="negative">{money(debt.balance)}</strong></div>
                <ProgressBar value={Number(debt.progress) * 100} color={debt.color ?? '#ff6b70'} />
                <div className="debt-meta"><span>{Math.round(Number(debt.progress) * 100)}% remboursé</span><span>{money(debt.minimum_payment)} / mois</span></div>
              </article>
            ))}
          </div>
        </Panel>
      )}

      <section className="dashboard-grid lower-grid">
        <Panel title="Comptes" subtitle="Soldes disponibles">
          {accounts.length > 0 ? (
            <div className="data-list">
              {accounts.filter((account) => !account.archived).slice(0, 6).map((account, index) => (
                <button type="button" key={account.id} onClick={() => navigate({ name: 'account', accountId: account.id })}>
                  <span className="account-avatar" style={{ background: account.color ?? colors[index % colors.length] }}>{initials(account.name)}</span>
                  <span><strong>{account.name}</strong><small>{account.institution || account.type}</small></span>
                  <strong>{money(account.balance)}</strong>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState icon="accounts" text="Aucun compte configuré." />
          )}
        </Panel>
        <Panel title="Activité récente" subtitle="Derniers mouvements">
          {transactions.length > 0 ? (
            <div className="data-list">
              {transactions.slice(0, 6).map((transaction) => (
                <div key={transaction.id}>
                  <MerchantAvatar description={transaction.description} identities={merchants} />
                  <span><strong>{transaction.description}</strong><small>{transaction.category_name ?? 'Sans catégorie'} · {formatDate(transaction.booked_at)}</small></span>
                  <strong className={Number(transaction.amount) >= 0 ? 'positive' : ''}>{signedMoney(transaction.amount)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon="receipt" text="Aucune transaction enregistrée." />
          )}
        </Panel>
      </section>
    </div>
  )
}
