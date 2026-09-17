export type Money = string

export interface Overview {
  balance: Money
  income_current_month: Money
  expenses_current_month: Money
  net_current_month: Money
  budget_current_month: Money
  budget_remaining: Money
}

export interface Account {
  id: number
  name: string
  type: string
  currency: string
  initial_balance: Money
  balance: Money
  institution: string | null
  regional_entity: string | null
  account_number: string | null
  archived: boolean
  savings_product: string | null
  annual_interest_rate: string | null
  legal_cap: Money | null
  missing_snapshot_periods: string[]
}

export interface AccountSnapshot {
  id: number
  account_id: number
  period: string
  balance: Money
  attachment_count: number
}

export interface AccountSnapshotImportResult {
  imported_count: number
  created_count: number
  updated_count: number
  snapshots: AccountSnapshot[]
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
}

export interface Category {
  id: number
  name: string
  kind: 'income' | 'expense'
  color: string
  monthly_budget: Money | null
  planned_this_month: Money
  parent_id: number | null
  archived: boolean
  is_default: boolean
}

export interface CategoryRemovalResult {
  action: 'archived' | 'deleted'
}

export interface StoredAttachment {
  id: number
  original_name: string
  storage_path: string
  content_type: string | null
  size: number
}

export type DocumentKind =
  | 'snapshot'
  | 'recurring'
  | 'debt'
  | 'real_estate'
  | 'work_contract'
  | 'payslip'

export interface DocumentItem {
  id: number
  kind: DocumentKind
  resource_id: number
  account_id: number | null
  resource_label: string
  resource_context: string
  reference: string | null
  original_name: string
  content_type: string | null
  size: number
  created_at: string
  download_url: string
}

export interface DocumentResource {
  kind: DocumentKind
  resource_id: number
  account_id: number | null
  label: string
  context: string
  reference: string | null
  can_upload: boolean
}

export interface DocumentKindSummary {
  kind: DocumentKind
  label: string
  total_resources: number
  covered_resources: number
  missing_resources: number
  document_count: number
}

export interface DocumentCenter {
  stats: {
    total_documents: number
    total_size: number
    total_resources: number
    covered_resources: number
    missing_resources: number
  }
  kinds: DocumentKindSummary[]
  documents: DocumentItem[]
  resources_without_documents: DocumentResource[]
  ignored_resources: DocumentResource[]
}

export interface AccountSnapshotAttachment extends StoredAttachment {
  snapshot_id: number
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
  envelope_planned: Money
  envelope_available: Money
  upcoming_recurring_amount: Money
  upcoming_recurring_count: number
  savings_contributions: Money
}

export interface Envelope {
  category_id: number
  category_name: string
  color: string
  parent_id: number | null
  budget: Money | null
  direct_planned: Money
  planned: Money
  available: Money | null
  children_budget: Money
  remainder_budget: Money | null
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
  occurrence_count: number
  children: SpendingNode[]
}

export type RecurringType =
  | 'uncategorized'
  | 'subscription'
  | 'rent'
  | 'energy'
  | 'telecom'
  | 'auto_insurance'
  | 'home_insurance'
  | 'health_insurance'
  | 'credit_insurance'
  | 'loan_payment'
  | 'tax'
  | 'salary'
  | 'transfer'
  | 'other'

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
  recurring_type: RecurringType
  custom_type: string | null
  credit_insurance_rate: string | null
  attachment_count: number
}

export interface RecurringForecastItem {
  series_id: number
  label: string
  due_date: string
  amount: Money
  account_name: string
  category_name: string | null
  status?: 'active' | 'paused' | 'ended'
  color?: string
}

export interface Debt {
  id: number
  name: string
  debt_type: 'consumer_credit' | 'mortgage' | 'other'
  principal: Money
  balance: Money
  interest_rate: string | null
  minimum_payment: Money | null
  account_id: number | null
  recurring_series_repayment_id: number | null
  recurring_series_insurance_id: number | null
  recurring_series_name_repayment: string | null
  recurring_series_name_insurance: string | null
  paid: Money
  progress: number
  due_date?: string | null
  color?: string
  archived?: boolean
  attachment_count: number
}

export interface RealEstateAsset {
  id: number
  name: string
  property_type: string
  address: string | null
  acquired_on: string | null
  purchase_price: Money
  current_value: Money | null
  ownership_share: string
  debt_ids: number[]
  debts: RealEstateDebt[]
  debt_balance: Money
  owned_purchase_price: Money
  owned_value: Money
  gain: Money
  net_equity: Money
  attachment_count: number
  icon_path?: string | null
}

export interface RealEstateDebt {
  id: number
  name: string
  balance: Money
  recurring_series_repayment_id: number | null
  recurring_series_insurance_id: number | null
  recurring_series_name_repayment: string | null
  recurring_series_name_insurance: string | null
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
  unrealized_cost_basis: Money
  realized_cost_basis: Money
  total_cost_basis: Money
  market_value: Money
  unrealized_gain: Money
  realized_gain: Money
  total_gain: Money
  cost_basis: Money
  gain: Money
  operation_count: number
}

export interface HoldingOperation {
  id: number
  holding_id: number
  operation_type: 'buy' | 'sell'
  quantity: string
  unit_price: Money
  total_value: Money
  realized_cost_basis: Money | null
  realized_gain: Money | null
  quantity_delta: string
  cash_flow: Money
  occurred_on: string
  created_at: string
}

export interface HoldingOperationResult {
  holding: Holding
  operation: HoldingOperation
}

export interface PortfolioAllocation {
  asset_class: string
  market_value: Money
  weight: number
}

export interface PortfolioSummary {
  cost_basis: Money
  unrealized_cost_basis: Money
  realized_cost_basis: Money
  total_cost_basis: Money
  market_value: Money
  unrealized_gain: Money
  realized_gain: Money
  total_gain: Money
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
  unrealized_cost_basis?: Money
  realized_cost_basis?: Money
  total_cost_basis?: Money
  unrealized_gain?: Money
  realized_gain?: Money
  total_gain?: Money
  gain?: Money
}

export interface AssetPerformancePoint {
  period: string
  market_value: Money
  cost_basis: Money
  unrealized_cost_basis: Money
  realized_cost_basis: Money
  total_cost_basis: Money
  unrealized_gain: Money
  realized_gain: Money
  total_gain: Money
  gain: Money
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

export interface WorkContract {
  id: number
  employer: string
  position: string
  contract_type: string
  start_date: string
  end_date: string | null
  gross_annual_salary: Money
  payment_period_months: number
  work_percentage: number
  recurring_series_id: number | null
  status: 'active' | 'ended'
  notes: string | null
  attachment_count: number
}

export interface PaySlipAttachment {
  id: number
  payslip_id: number
  original_name: string
  stored_path: string
  content_type: string | null
  size: number
}

export interface PaySlip {
  id: number
  contract_id: number | null
  period: string
  gross_salary: Money
  taxable_net: Money
  net_before_tax: Money
  pas_rate: string
  pas_amount: Money
  net_after_tax: Money
  bonuses: Money
  employer_contributions: Money
  employer_profit_sharing: Money
  hours_worked: string | null
  overtime_hours: string | null
  notes: string | null
  attachments: PaySlipAttachment[]
}

export interface PensionProfile {
  id: number
  birth_year: number
  birth_month: number
  target_retirement_age: number
  validated_quarters: number
  required_quarters: number
  estimated_monthly_pension: Money
  target_monthly_income: Money
  income_growth_scenario: 'none' | 'regular' | 'strong_early' | 'strong_late'
  future_annual_gross: Money | null
  future_work_percentage: number
  planned_unemployment_months: number
  notes: string | null
  payslip_quarters: number
  estimated_total_quarters: number
  quarter_calculation: PensionQuarterYear[]
  unsupported_payslip_years: number[]
  projection: PensionProjection | null
}

export interface PensionProjection {
  reference_annual_gross: Money
  payslip_count: number
  covered_years: number[]
  annual_social_security_ceiling: Money
  simulated_end_annual_gross: Money
  income_evolution: PensionIncomePoint[]
  scenarios: PensionProjectionScenario[]
  long_career: LongCareerAssessment
}

export interface PensionIncomePoint {
  age_years: number
  annual_gross: Money
}

export interface PensionProjectionScenario {
  kind: 'long_career' | 'target' | 'legal_age' | 'full_rate_automatic'
  age_years: number
  age_months: number
  projected_quarters: number
  base_monthly_pension: Money
  complementary_monthly_pension: Money
  total_monthly_pension: Money
}

export interface LongCareerAssessment {
  status: 'eligible' | 'insufficient_early_records' | 'insufficient_projected_quarters'
  cutoff_year: number
  required_early_quarters: number
  entered_early_quarters: number
  projected_quarters_at_63: number
  required_total_quarters: number
}

export interface PensionQuarterYear {
  year: number
  gross_salary: Money
  quarter_threshold: Money
  validated_quarters: number
  next_quarter_remaining: Money | null
}

export interface WorkSummary {
  active_contracts_count: number
  latest_net_after_tax: Money
  ytd_taxable_net: Money
  ytd_net_after_tax: Money
  ytd_gross: Money
  ytd_bonuses: Money
  ytd_profit_sharing: Money
  average_pas_rate: string
  estimated_pension: Money
  declared_validated_quarters: number
  payslip_quarters: number
  validated_quarters: number
  required_quarters: number
}
