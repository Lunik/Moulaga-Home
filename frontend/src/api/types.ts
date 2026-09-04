export type Money = string

export interface Overview {
  balance: Money
  income_current_month: Money
  expenses_current_month: Money
  net_current_month: Money
  budget_current_month: Money
  budget_remaining: Money
  uncategorized_count: number
}

export interface Account {
  id: number
  name: string
  type: string
  currency: string
  initial_balance: Money
  balance: Money
  institution: string | null
  account_number: string | null
  archived: boolean
  transaction_count: number
  savings_product: string | null
  annual_interest_rate: string | null
  legal_cap: Money | null
}

export interface AccountSnapshot {
  id: number
  account_id: number
  period: string
  balance: Money
  attachment_count: number
}

export interface AccountHistoryPoint {
  period: string
  balance: Money
}

export interface AccountInstitutionHistoryPoint {
  period: string
  institution: string
  balance: Money
}

export interface AccountDetail extends Account {
  history: AccountHistoryPoint[]
  transaction_count: number
}

export interface Category {
  id: number
  name: string
  kind: 'income' | 'expense'
  color: string
  monthly_budget: Money | null
  spent_this_month: Money
  parent_id: number | null
  archived: boolean
  is_default: boolean
}

export interface CategoryRemovalResult {
  action: 'archived' | 'deleted'
  transaction_count: number
}

export interface Transaction {
  id: number
  booked_at: string
  description: string
  amount: Money
  account_id: number
  account_name: string
  category_id: number | null
  category_name: string | null
  category_kind: 'income' | 'expense' | null
  notes: string | null
  transfer_group: string | null
  attachment_count: number
}

export interface StoredAttachment {
  id: number
  original_name: string
  storage_path: string
  content_type: string | null
  size: number
}

export interface TransactionAttachment extends StoredAttachment {
  transaction_id: number
}

export interface AccountSnapshotAttachment extends StoredAttachment {
  snapshot_id: number
}

export interface TransactionCount {
  count: number
}

export interface MonthlyPoint {
  month: string
  income: Money
  expenses: Money
  net: Money
}

export interface CategoryBreakdown {
  category_id: number | null
  category_name: string
  amount: Money
  budget: Money | null
}

export interface AppSettings {
  theme: 'light' | 'dark' | 'system'
  language: 'fr' | 'en' | 'de' | 'es'
  date_format: 'localized' | 'day-month-year' | 'YYYY-MM-DD'
  navigation_style: 'sidebar' | 'topbar' | 'compact'
  budget_cycle_start_day: number
  local_merchant_identities: boolean
  private_categorization_enabled: boolean
  private_categorization_mode: 'off' | 'suggest' | 'auto'
  private_categorization_confidence: number
}

export interface BudgetCycle {
  start: string
  end: string
  start_day: number
}

export interface BudgetOverview {
  cycle: BudgetCycle
  income: Money
  expenses: Money
  net: Money
  budget_total: Money
  budget_remaining: Money
  uncategorized_count: number
  envelope_spent?: Money
  envelope_remaining?: Money
  upcoming_recurring_amount: Money
  upcoming_recurring_count: number
  savings_contributions: Money
}

export interface Envelope {
  category_id: number
  category_name: string
  color: string
  budget: Money | null
  spent: Money
  remaining: Money | null
}

export interface CashflowFlow {
  key: string
  label: string
  inflow: Money
  outflow: Money
  net: Money
}

export interface SpendingNode {
  category_id: number | null
  category_name: string
  amount: Money
  transaction_count: number
  children: SpendingNode[]
}

export interface CategorizationRule {
  id: number
  name: string
  match_type: 'beneficiary' | 'keyword'
  pattern: string
  patterns: string[]
  category_id: number
  priority: number
  enabled: boolean
}

export interface CategorizationSuggestion {
  transaction_id: number
  category_id: number | null
  category_name: string | null
  confidence: number
  explanation: string
  source: 'rule' | 'history' | 'none'
  applied: boolean
}

export interface CategorizationInboxItem {
  transaction_id: number
  booked_at: string
  description: string
  amount: Money
  account_id: number
}

export interface RecurringSeries {
  id: number
  label: string
  account_id: number
  account_name?: string
  category_id: number | null
  category_name?: string | null
  amount: Money | null
  frequency: 'weekly' | 'monthly' | 'quarterly' | 'yearly'
  next_due: string
  amount_type: 'fixed' | 'variable'
  status: 'active' | 'paused' | 'ended'
  confidence: number
}

export interface RecurringDetectionProposal {
  proposal_key: string
  kind: 'series' | 'change'
  series_id: number | null
  label: string
  account_id: number
  account_name: string
  category_id: number | null
  category_name: string | null
  amount: Money
  frequency: RecurringSeries['frequency']
  next_due: string
  amount_type: RecurringSeries['amount_type']
  confidence: number
}

export interface RecurringDetectionResult {
  created_series: number
  created_changes: number
}

export interface RecurringForecastItem {
  series_id: number
  label: string
  due_date: string
  amount: Money
  status?: 'active' | 'paused' | 'ended'
  color?: string
}

export interface RecurringChange {
  id: number
  series_id: number
  series_label?: string
  change_type: string
  detected_amount: Money | null
  detected_next_due: string | null
  status: 'pending' | 'accepted' | 'rejected'
  note: string | null
}

export interface Debt {
  id: number
  name: string
  principal: Money
  balance: Money
  interest_rate: string | null
  minimum_payment: Money | null
  account_id: number | null
  paid: Money
  progress: number
  due_date?: string | null
  color?: string
  archived?: boolean
}

export interface RealEstateAsset {
  id: number
  name: string
  property_type: string
  address: string | null
  acquired_on: string | null
  purchase_price: Money
  current_value: Money
  ownership_share: string
  debt_id: number | null
  debt_name: string | null
  debt_balance: Money
  owned_purchase_price: Money
  owned_value: Money
  gain: Money
  net_equity: Money
}

export interface Holding {
  id: number
  account_id: number
  name: string
  symbol: string | null
  asset_class: string
  quantity: string
  average_price: Money
  current_price: Money
  market_value: Money
  cost_basis: Money
  gain: Money
}

export interface InvestmentContribution {
  id: number
  holding_id: number
  holding_name?: string
  account_id?: number
  amount: Money
  occurred_on: string
  note: string | null
}

export interface PortfolioAllocation {
  asset_class: string
  market_value: Money
  weight: number
}

export interface PortfolioSummary {
  cost_basis: Money
  market_value: Money
  gain: Money
  contributions_total: Money
  holdings: number
  properties: number
}

export interface PerformancePoint {
  period: string
  contributions: Money
  cumulative_contributions: Money
  market_value?: Money
  cost_basis?: Money
  gain?: Money
}

export interface NetWorthSummary {
  cash: Money
  investments: Money
  real_estate: Money
  debts: Money
  net_worth: Money
}

export interface NetWorthPoint {
  period: string
  net_worth: Money
}

export interface Household {
  id: number
  name: string
  members: HouseholdMember[]
}

export interface HouseholdMember {
  id: number
  household_id: number
  name: string
  role: 'owner' | 'admin' | 'member' | 'viewer'
}

export interface SharedAccount {
  id: number
  household_id: number
  account_id: number
  permission: 'view' | 'edit'
  account_name?: string
  balance?: Money
}

export interface SharedGoal {
  id: number
  household_id: number | null
  name: string
  target_amount: Money
  current_amount: Money
  due_date: string | null
  account_id: number | null
  progress: number
}

export interface GoalContribution {
  id: number
  goal_id: number
  amount: Money
  occurred_on: string
  member_id: number | null
  member_name?: string
  note: string | null
}

export interface MerchantIdentity {
  id: number
  label: string
  pattern: string
  monogram: string
  color: string
}
