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
import { useState } from 'react'

import { apiGet, queryString } from '../api/client'
import type {
  Account,
  CashflowFlow,
  Category,
  Debt,
  NetWorthPoint,
  NetWorthSummary,
  Overview,
  PortfolioSummary,
  RecurringForecastItem,
} from '../api/types'
import { accountInstitutionLabel } from '../institutions'
import {
  CashflowPeriodSelector,
  RecurringCashflowSankey,
  type CashflowPeriodMonths,
} from '../RecurringCashflowSankey'
import type { Route } from '../routing'
import {
  EmptyState,
  Icon,
  InstitutionLogo,
  MetricCard,
  Panel,
  ProgressBar,
  chartTooltipStyle,
  compactMoney,
  errorMessage,
  formatDate,
  formatMonth,
  initials,
  localDateInputValue,
  maskNumericValue,
  money,
  shortMonthYear,
  signedMoney,
} from '../ui'
import { useQuery } from '@tanstack/react-query'

const colors = ['#16c79a', '#615fff', '#1da9e8', '#f97316', '#8758f6', '#ec4899']

export function DashboardView({
  categories,
  onRefresh,
  navigate,
}: {
  categories: Category[]
  onRefresh: () => Promise<void>
  navigate: (route: Route) => void
}) {
  const today = localDateInputValue()
  const [cashflowMonths, setCashflowMonths] = useState<CashflowPeriodMonths>(1)
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
  const sourceFlows = useQuery({
    queryKey: ['budget-cashflow', 'projection', cashflowMonths, 'source'],
    queryFn: () => apiGet<CashflowFlow[]>(
      `/budget/cashflow${queryString({ months: cashflowMonths, by: 'source' })}`,
    ),
    networkMode: 'always',
  })
  const categoryFlows = useQuery({
    queryKey: ['budget-cashflow', 'projection', cashflowMonths, 'category'],
    queryFn: () => apiGet<CashflowFlow[]>(
      `/budget/cashflow${queryString({ months: cashflowMonths, by: 'category' })}`,
    ),
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
  const recurringForecast = useQuery({
    queryKey: ['recurring-forecast', 3],
    queryFn: () => apiGet<RecurringForecastItem[]>('/recurring/forecast?months=3'),
    networkMode: 'always',
  })
  const requiredQueries = [accounts, overview]
  const optionalQueries = [
    sourceFlows,
    categoryFlows,
    netWorth,
    history,
    portfolio,
    debts,
    recurringForecast,
  ]
  const firstError = requiredQueries
    .filter((query) => query.data === undefined)
    .map((query) => query.error)
    .find(Boolean)
  const isLoading = requiredQueries.some((query) => query.data === undefined && query.isPending)
  const partialError = [...requiredQueries, ...optionalQueries]
    .map((query) => query.error)
    .find(Boolean)
  const accountItems = accounts.data
  const overviewData = overview.data

  if (firstError) {
    return <DashboardLoadError message={errorMessage(firstError)} onRefresh={onRefresh} />
  }
  if (isLoading) {
    return <div className="loading-card" role="status" aria-live="polite">Chargement du tableau de bord…</div>
  }
  if (!accountItems || !overviewData) {
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
    .sort((left, right) => right.value - left.value || left.name.localeCompare(right.name, 'fr'))
  const activeDebts = (debts.data ?? []).filter((debt) => !debt.archived)
  const netWorthData = netWorth.data
  const portfolioData = portfolio.data
  const assets = netWorthData
    ? Number(netWorthData.cash) + Number(netWorthData.investments) + Number(netWorthData.real_estate)
    : 0
  const portfolioCostBasis = Number(portfolioData?.total_cost_basis ?? portfolioData?.cost_basis ?? 0)
  const portfolioGain = Number(portfolioData?.total_gain ?? portfolioData?.gain ?? 0)
  const gainPercent = portfolioCostBasis > 0
    ? (portfolioGain / portfolioCostBasis) * 100
    : 0
  const historyData = (history.data ?? []).map((point) => ({
    ...point,
    net_worth: Number(point.net_worth),
  }))
  const positiveHistoryData = historyData.map((point) => ({
    ...point,
    net_worth: Number(point.net_worth) > 0 ? Number(point.net_worth) : null,
  }))
  const negativeHistoryData = historyData.map((point) => ({
    ...point,
    net_worth: Number(point.net_worth) < 0 ? Number(point.net_worth) : null,
  }))
  const recurringIncome = (sourceFlows.data ?? []).reduce(
    (total, flow) => total + Number(flow.inflow),
    0,
  )
  const recurringExpenses = (categoryFlows.data ?? []).reduce(
    (total, flow) => total + Number(flow.outflow),
    0,
  )
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
                  Performance des placements : {signedMoney(portfolioGain, true)} ({gainPercent.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}%)
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
            ? `Derniers relevés · ${activeAccounts.length} actif${activeAccounts.length === 1 ? '' : 's'} · ${archivedAccountCount} archivé${archivedAccountCount === 1 ? '' : 's'} inclus`
            : `Derniers relevés · ${activeAccounts.length} compte${activeAccounts.length === 1 ? '' : 's'} actif${activeAccounts.length === 1 ? '' : 's'}`}
          icon="accounts"
          tone={Number(overviewData.balance) < 0 ? 'negative' : undefined}
        />
        <MetricCard
          label="Revenus récurrents"
          value={money(overviewData.income_current_month)}
          detail={`Solde prévisionnel : ${signedMoney(overviewData.net_current_month)}`}
          icon="trend"
          tone="positive"
        />
        <MetricCard
          label="Dépenses récurrentes"
          value={money(overviewData.expenses_current_month)}
          detail="Budget mensuel · hors virements"
          icon="receipt"
          tone="negative"
        />
        <MetricCard
          label="Budget disponible"
          value={signedMoney(overviewData.budget_remaining)}
          detail={`après récurrents · sur ${money(overviewData.budget_current_month)}`}
          icon="budget"
          tone={budgetRemaining < 0 ? 'negative' : 'positive'}
        />
      </section>

      <Panel
        title="Flux récurrents"
        subtitle={`Entrées ${money(recurringIncome)} · Sorties ${money(recurringExpenses)} · Solde ${signedMoney(recurringIncome - recurringExpenses)}`}
        className="cashflow-panel"
        action={(
          <div className="cashflow-panel-actions">
            <CashflowPeriodSelector value={cashflowMonths} onChange={setCashflowMonths} />
            <button className="secondary-button small-button" type="button" onClick={() => navigate({ name: 'budget', tab: 'cashflow' })}>
              Ouvrir le cashflow <Icon name="arrow" />
            </button>
          </div>
        )}
      >
        <RecurringCashflowSankey
          categories={categories}
          categoryFlows={categoryFlows.data ?? []}
          sourceFlows={sourceFlows.data ?? []}
        />
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
                    <linearGradient id="dashboard-net-fill-positive" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#16c79a" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#16c79a" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="dashboard-net-fill-negative" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#e11d48" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#e11d48" stopOpacity={0} />
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
                  <Area data={positiveHistoryData} dataKey="net_worth" name="Patrimoine" type="monotone" stroke="#16c79a" strokeWidth={2.5} fill="url(#dashboard-net-fill-positive)" connectNulls={false} />
                  <Area data={negativeHistoryData} dataKey="net_worth" name="Patrimoine" type="monotone" stroke="#e11d48" strokeWidth={2.5} fill="url(#dashboard-net-fill-negative)" connectNulls={false} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState icon="trend" text="Les relevés mensuels construiront cette courbe." />
            )}
          </div>
        </Panel>
        <Panel title="Répartition des comptes" subtitle={`${allocation.length} compte${allocation.length === 1 ? '' : 's'} avec un dernier relevé positif`}>
          <div className="distribution-layout">
            <div className="donut-container">
              {allocation.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart accessibilityLayer aria-label="Répartition des soldes positifs entre les comptes actifs">
                      <Pie data={allocation} dataKey="value" nameKey="name" innerRadius="64%" outerRadius="88%" paddingAngle={2} stroke="none">
                        {allocation.map((entry) => <Cell key={entry.id} fill={entry.color} />)}
                      </Pie>
                      <Tooltip
                        contentStyle={chartTooltipStyle}
                        itemStyle={{ color: 'var(--text)' }}
                        formatter={(value) => money(Number(value))}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-label"><strong>{allocation.length}</strong><span>comptes</span></div>
                </>
              ) : (
                <EmptyState icon="accounts" text="Aucun solde positif à répartir." />
              )}
            </div>
            <div
              className="distribution-list"
              role="list"
              aria-label="Comptes classés par solde décroissant"
              tabIndex={allocation.length > 6 ? 0 : undefined}
            >
              {allocation.map((entry) => (
                <div key={entry.id} role="listitem"><span><i style={{ background: entry.color }} />{entry.name}</span><strong>{money(entry.value)}</strong></div>
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
                  <span>{maskNumericValue(`${Math.round(Number(debt.progress) * 100)}%`)} remboursé</span>
                </div>
              </article>
            ))}
          </div>
        </Panel>
      )}

      <section className="dashboard-grid lower-grid">
        <Panel
          title="Comptes"
          subtitle="Derniers soldes relevés"
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
          title="Échéances récurrentes"
          subtitle="Prochains revenus et prélèvements planifiés"
          action={(
            <button className="secondary-button small-button" type="button" onClick={() => navigate({ name: 'budget', tab: 'recurring' })}>
              Voir les récurrents <Icon name="arrow" />
            </button>
          )}
        >
          {recurringForecast.data === undefined ? (
            <div className="chart-loading" role={recurringForecast.isPending ? 'status' : undefined}>
              {recurringForecast.isPending ? 'Chargement des échéances…' : 'Prévision temporairement indisponible.'}
            </div>
          ) : recurringForecast.data.length > 0 ? (
            <div className="data-list dashboard-data-list">
              {recurringForecast.data.slice(0, 6).map((item) => (
                <button
                  type="button"
                  key={`${item.series_id}-${item.due_date}`}
                  onClick={() => navigate({ name: 'budget', tab: 'recurring', focusId: item.series_id })}
                >
                  <span className="entity-avatar">{initials(item.label)}</span>
                  <span><strong>{item.label}</strong><small>{item.category_name ?? item.account_name} · {formatDate(item.due_date)}</small></span>
                  <strong className={Number(item.amount) >= 0 ? 'positive' : 'negative'}>{signedMoney(item.amount)}</strong>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="recurring"
              title="Aucune échéance"
              text="Les prochaines séries récurrentes apparaîtront ici."
              action={<button className="primary-button" type="button" onClick={() => navigate({ name: 'budget', tab: 'recurring' })}>Configurer les récurrents</button>}
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
