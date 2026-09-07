import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiGet, queryString } from '../api/client'
import type {
  Account,
  Debt,
  MerchantIdentity,
  MonthlyPoint,
  NetWorthPoint,
  NetWorthSummary,
  Overview,
  PortfolioSummary,
  Transaction,
} from '../api/types'
import { accountInstitutionLabel } from '../institutions'
import type { Route } from '../routing'
import {
  CategorizationSummary,
  EmptyState,
  Icon,
  InstitutionLogo,
  MerchantAvatar,
  MetricCard,
  Panel,
  ProgressBar,
  chartTooltipStyle,
  compactMoney,
  errorMessage,
  formatDate,
  formatMonth,
  localDateInputValue,
  money,
  shortMonthYear,
  signedMoney,
} from '../ui'
import { useQuery } from '@tanstack/react-query'

const colors = ['#16c79a', '#615fff', '#1da9e8', '#f97316', '#8758f6', '#ec4899']

export function DashboardView({
  externalError,
  isOnline,
  merchants,
  onRefresh,
  navigate,
}: {
  externalError?: unknown
  isOnline: boolean
  merchants: MerchantIdentity[]
  onRefresh: () => Promise<void>
  navigate: (route: Route) => void
}) {
  const today = localDateInputValue()
  const accounts = useQuery({
    queryKey: ['dashboard-accounts', today],
    queryFn: () => apiGet<Account[]>(`/accounts${queryString({ include_archived: true, as_of: today })}`),
    networkMode: 'always',
  })
  const overview = useQuery({
    queryKey: ['overview', today],
    queryFn: () => apiGet<Overview>(`/overview${queryString({ as_of: today })}`),
    networkMode: 'always',
  })
  const monthlyStats = useQuery({
    queryKey: ['monthly-stats', today],
    queryFn: () => apiGet<MonthlyPoint[]>(`/stats/monthly${queryString({ as_of: today })}`),
    networkMode: 'always',
  })
  const netWorth = useQuery({
    queryKey: ['net-worth', 'dashboard', today],
    queryFn: () => apiGet<NetWorthSummary>(`/networth/overview${queryString({ as_of: today })}`),
    networkMode: 'always',
  })
  const portfolio = useQuery({
    queryKey: ['wealth-summary'],
    queryFn: () => apiGet<PortfolioSummary>('/portfolio/summary'),
    networkMode: 'always',
  })
  const history = useQuery({
    queryKey: ['net-worth-history', 'dashboard', today],
    queryFn: () => apiGet<NetWorthPoint[]>(`/networth/history${queryString({ as_of: today })}`),
    networkMode: 'always',
  })
  const debts = useQuery({
    queryKey: ['debts'],
    queryFn: () => apiGet<Debt[]>('/debts'),
    networkMode: 'always',
  })
  const recentTransactions = useQuery({
    queryKey: ['dashboard-transactions', today],
    queryFn: () => apiGet<Transaction[]>(`/transactions${queryString({ end: today, limit: 6 })}`),
    enabled: isOnline,
  })
  const requiredQueries = [accounts, overview, monthlyStats]
  const optionalQueries = [netWorth, history, portfolio, debts, recentTransactions]
  const firstError = requiredQueries
    .filter((query) => query.data === undefined)
    .map((query) => query.error)
    .find(Boolean)
  const isLoading = requiredQueries.some((query) => query.data === undefined && query.isPending)
  const partialError = externalError ?? [...requiredQueries, ...optionalQueries]
    .map((query) => query.error)
    .find(Boolean)
  const accountItems = accounts.data
  const overviewData = overview.data
  const monthlyPoints = monthlyStats.data

  if (firstError) {
    return <DashboardLoadError message={errorMessage(firstError)} onRefresh={onRefresh} />
  }
  if (isLoading) {
    return <div className="loading-card" role="status" aria-live="polite">Chargement du tableau de bord…</div>
  }
  if (!accountItems || !overviewData || !monthlyPoints) {
    return <DashboardLoadError message="Les données reçues sont incomplètes." onRefresh={onRefresh} />
  }

  const activeAccounts = accountItems.filter((account) => !account.archived)
  const dashboardAccounts = [...activeAccounts].sort((left, right) => {
    const balanceDifference = Number(right.balance) - Number(left.balance)
    return balanceDifference || left.name.localeCompare(right.name, 'fr')
  })
  const archivedAccountCount = accountItems.length - activeAccounts.length
  const allocation = activeAccounts
    .filter((account) => Number(account.balance) > 0)
    .map((account, index) => ({
      id: account.id,
      name: account.name,
      value: Number(account.balance),
      color: colors[index % colors.length],
    }))
  const activeDebts = (debts.data ?? []).filter((debt) => !debt.archived)
  const netWorthData = netWorth.data
  const portfolioData = portfolio.data
  const assets = netWorthData
    ? Number(netWorthData.cash) + Number(netWorthData.investments) + Number(netWorthData.real_estate)
    : 0
  const portfolioCostBasis = Number(portfolioData?.cost_basis ?? 0)
  const portfolioGain = Number(portfolioData?.gain ?? 0)
  const gainPercent = portfolioCostBasis > 0
    ? (portfolioGain / portfolioCostBasis) * 100
    : 0
  const historyData = (history.data ?? []).map((point) => ({
    ...point,
    net_worth: Number(point.net_worth),
  }))
  const monthlyData = monthlyPoints.map((point) => ({
    ...point,
    income: Number(point.income),
    expenses: Number(point.expenses),
  }))
  const budgetRemaining = Number(overviewData.budget_remaining)

  return (
    <div className="view-stack">
      {partialError && (
        <div className="error-banner" role="alert">
          Certaines données sont indisponibles : {errorMessage(partialError)} Les autres indicateurs restent affichés.
        </div>
      )}
      {netWorthData ? (
        <section className="wealth-hero dashboard-wealth-hero">
          <div>
            <p className="eyebrow">Patrimoine net</p>
            <p className="hero-value">{money(netWorthData.net_worth)}</p>
            <div className="wealth-equation">
              <span>Total des actifs <strong>{money(assets)}</strong></span>
              <i>−</i>
              <span>Total des dettes <strong className="negative">{money(netWorthData.debts)}</strong></span>
            </div>
            <small className="dashboard-scope-note">Les éléments archivés restent inclus dans ce calcul patrimonial.</small>
            {portfolioData ? (
              portfolioCostBasis > 0 ? (
                <span className={portfolioGain >= 0 ? 'portfolio-change positive' : 'portfolio-change negative'}>
                  <Icon name="trend" />
                  Performance des placements : {signedMoney(portfolioGain)} ({gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%)
                </span>
              ) : (
                <span className="portfolio-change"><Icon name="trend" />Aucun placement valorisé</span>
              )
            ) : (
              <span className="portfolio-change"><Icon name="trend" />Performance des placements indisponible</span>
            )}
          </div>
          <button className="secondary-button" type="button" onClick={() => navigate({ name: 'wealth', tab: 'overview' })}>
            Voir le patrimoine <Icon name="arrow" />
          </button>
        </section>
      ) : (
        <section className="loading-card" role={netWorth.isPending ? 'status' : undefined}>
          {netWorth.isPending ? 'Chargement du patrimoine…' : 'Le patrimoine est temporairement indisponible.'}
        </section>
      )}

      <section className="metric-grid" aria-label="Indicateurs du mois">
        <MetricCard
          label="Solde total"
          value={money(overviewData.balance)}
          detail={archivedAccountCount > 0
            ? `${activeAccounts.length} actif${activeAccounts.length === 1 ? '' : 's'} · ${archivedAccountCount} archivé${archivedAccountCount === 1 ? '' : 's'} inclus`
            : `${activeAccounts.length} compte${activeAccounts.length === 1 ? '' : 's'} actif${activeAccounts.length === 1 ? '' : 's'}`}
          icon="accounts"
          tone={Number(overviewData.balance) < 0 ? 'negative' : undefined}
        />
        <MetricCard
          label="Revenus du mois"
          value={money(overviewData.income_current_month)}
          detail={`Solde net : ${signedMoney(overviewData.net_current_month)}`}
          icon="trend"
          tone="positive"
        />
        <MetricCard
          label="Dépenses du mois"
          value={money(overviewData.expenses_current_month)}
          detail="Hors transferts internes"
          icon="receipt"
          tone="negative"
        />
        <MetricCard
          label="Budget restant"
          value={signedMoney(overviewData.budget_remaining)}
          detail={`sur ${money(overviewData.budget_current_month)}`}
          icon="budget"
          tone={budgetRemaining < 0 ? 'negative' : 'positive'}
        />
      </section>

      {isOnline && overviewData.uncategorized_count > 0 && (
        <CategorizationSummary
          detail={`${overviewData.uncategorized_count} mouvement${overviewData.uncategorized_count === 1 ? '' : 's'} sans catégorie`}
          onCategorize={() => navigate({ name: 'budget', tab: 'categorize' })}
        />
      )}

      <Panel
        title="Revenus et dépenses"
        subtitle="12 derniers mois, hors transferts internes"
        action={(
          <button className="secondary-button small-button" type="button" onClick={() => navigate({ name: 'budget', tab: 'overview' })}>
            Ouvrir le budget <Icon name="arrow" />
          </button>
        )}
      >
        <div className="chart-container">
          {monthlyData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                accessibilityLayer
                aria-label="Comparaison mensuelle des revenus et des dépenses"
                data={monthlyData}
                margin={{ top: 12, right: 10, left: -8, bottom: 0 }}
              >
                <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={shortMonthYear} />
                <YAxis axisLine={false} padding={{ top: 12 }} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                <Tooltip
                  contentStyle={chartTooltipStyle}
                  formatter={(value) => money(Number(value))}
                  labelFormatter={(value) => formatMonth(String(value))}
                />
                <Bar dataKey="income" name="Revenus" fill="#16c79a" maxBarSize={28} radius={[5, 5, 0, 0]} />
                <Bar dataKey="expenses" name="Dépenses" fill="#615fff" maxBarSize={28} radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon="trend" text="Les premiers mouvements construiront cette comparaison." />
          )}
        </div>
        {monthlyData.length > 0 && (
          <div className="chart-legend" aria-hidden="true">
            <span><i className="legend-line" />Revenus</span>
            <span><i className="legend-line expenses" />Dépenses</span>
          </div>
        )}
      </Panel>

      <section className="dashboard-grid">
        <Panel title="Évolution mensuelle du patrimoine net" subtitle="Actifs moins dettes">
          <div className="chart-container">
            {history.data === undefined ? (
              <div className="chart-loading" role={history.isPending ? 'status' : undefined}>
                {history.isPending ? 'Chargement de l’historique…' : 'Historique temporairement indisponible.'}
              </div>
            ) : historyData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  accessibilityLayer
                  aria-label="Évolution mensuelle du patrimoine net"
                  data={historyData}
                  margin={{ top: 12, right: 10, left: -8, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="dashboard-net-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="4 5" vertical={false} />
                  <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={shortMonthYear} />
                  <YAxis axisLine={false} padding={{ top: 12 }} tickLine={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} tickFormatter={compactMoney} />
                  <Tooltip
                    contentStyle={chartTooltipStyle}
                    formatter={(value) => money(Number(value))}
                    labelFormatter={(value) => formatMonth(String(value))}
                  />
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
                    <PieChart accessibilityLayer aria-label="Répartition des soldes positifs entre les comptes actifs">
                      <Pie data={allocation} dataKey="value" nameKey="name" innerRadius="64%" outerRadius="88%" paddingAngle={2} stroke="none">
                        {allocation.map((entry) => <Cell key={entry.id} fill={entry.color} />)}
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
                <div key={entry.id}><span><i style={{ background: entry.color }} />{entry.name}</span><strong>{money(entry.value)}</strong></div>
              ))}
            </div>
          </div>
        </Panel>
      </section>

      {activeDebts.length > 0 && (
        <Panel
          title="Dettes"
          subtitle={`Dettes actives · total restant : ${money(activeDebts.reduce((sum, debt) => sum + Number(debt.balance), 0))}`}
          action={(
            <button className="secondary-button small-button" type="button" onClick={() => navigate({ name: 'wealth', tab: 'debts' })}>
              Gérer les dettes <Icon name="arrow" />
            </button>
          )}
        >
          <div className="debt-list compact-debts">
            {activeDebts.slice(0, 3).map((debt) => (
              <article key={debt.id}>
                <div className="debt-head"><span><i style={{ background: debt.color ?? '#ff6b70' }} /><strong>{debt.name}</strong></span><strong className="negative">{money(debt.balance)}</strong></div>
                <ProgressBar value={Number(debt.progress) * 100} color={debt.color ?? '#ff6b70'} />
                <div className="debt-meta">
                  <span>{Math.round(Number(debt.progress) * 100)}% remboursé</span>
                  <span>{debt.minimum_payment === null ? 'Mensualité non renseignée' : `${money(debt.minimum_payment)} / mois`}</span>
                </div>
              </article>
            ))}
          </div>
        </Panel>
      )}

      <section className="dashboard-grid lower-grid">
        <Panel
          title="Comptes"
          subtitle="Soldes disponibles"
          action={(
            <button className="secondary-button small-button" type="button" onClick={() => navigate({ name: 'accounts' })}>
              Tous les comptes <Icon name="arrow" />
            </button>
          )}
        >
          {activeAccounts.length > 0 ? (
            <div className="data-list dashboard-data-list dashboard-account-list">
              {dashboardAccounts.map((account) => (
                <button type="button" key={account.id} onClick={() => navigate({ name: 'account', accountId: account.id })}>
                  <InstitutionLogo institution={account.institution} />
                  <span><strong>{account.name}</strong><small>{accountInstitutionLabel(account) || account.type}</small></span>
                  <strong className={Number(account.balance) < 0 ? 'negative' : undefined}>{money(account.balance)}</strong>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="accounts"
              title="Aucun compte actif"
              text="Ajoutez un compte pour commencer à suivre vos soldes."
              action={<button className="primary-button" type="button" onClick={() => navigate({ name: 'accounts' })}>Configurer mes comptes</button>}
            />
          )}
        </Panel>
        <Panel
          title="Activité récente"
          subtitle="Derniers mouvements"
          action={isOnline ? (
            <button className="secondary-button small-button" type="button" onClick={() => navigate({ name: 'budget', tab: 'transactions' })}>
              Voir le registre <Icon name="arrow" />
            </button>
          ) : undefined}
        >
          {!isOnline ? (
            <EmptyState
              icon="receipt"
              title="Registre non conservé hors ligne"
              text="Les graphiques et les synthèses restent disponibles, contrairement aux listes de transactions."
            />
          ) : recentTransactions.data === undefined ? (
            <div className="chart-loading" role={recentTransactions.isPending ? 'status' : undefined}>
              {recentTransactions.isPending ? 'Chargement des mouvements…' : 'Activité temporairement indisponible.'}
            </div>
          ) : recentTransactions.data.length > 0 ? (
            <div className="data-list dashboard-data-list">
              {recentTransactions.data.map((transaction) => (
                <button
                  type="button"
                  key={transaction.id}
                  onClick={() => navigate({ name: 'account', accountId: transaction.account_id })}
                >
                  <MerchantAvatar description={transaction.description} identities={merchants} />
                  <span><strong>{transaction.description}</strong><small>{transaction.category_name ?? 'Sans catégorie'} · {formatDate(transaction.booked_at)}</small></span>
                  <strong className={Number(transaction.amount) >= 0 ? 'positive' : 'negative'}>{signedMoney(transaction.amount)}</strong>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="receipt"
              title="Aucun mouvement"
              text="Les transactions les plus récentes apparaîtront ici."
              action={<button className="primary-button" type="button" onClick={() => navigate({ name: 'budget', tab: 'transactions' })}>Ouvrir le registre</button>}
            />
          )}
        </Panel>
      </section>
    </div>
  )
}

function DashboardLoadError({
  message,
  onRefresh,
}: {
  message: string
  onRefresh: () => Promise<void>
}) {
  return (
    <section className="view-error" role="alert">
      <span><Icon name="alert" /></span>
      <div>
        <h2>Le tableau de bord n'a pas pu être chargé</h2>
        <p>{message}</p>
        <button className="secondary-button" type="button" onClick={() => void onRefresh()}>
          <Icon name="refresh" />Réessayer
        </button>
      </div>
    </section>
  )
}
