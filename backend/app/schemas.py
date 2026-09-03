"""Pydantic request/response schemas for the Moulaga API.

All monetary fields are serialized as strings with two decimals by the router
layer, and every request model performs strict server-side validation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
_MONEY = {"max_digits": 12, "decimal_places": 2}


def _strip_required(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Champ obligatoire")
    return cleaned


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="checking", min_length=1, max_length=32)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    initial_balance: Decimal = Decimal("0.00")
    institution: str | None = Field(default=None, max_length=120)
    color: str = Field(default="#4f46e5", pattern=HEX_COLOR)

    @field_validator("name", "type", "currency")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class AccountRead(AccountCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived: bool = False
    balance: Decimal = Decimal("0.00")


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, min_length=1, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    initial_balance: Decimal | None = None
    institution: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    archived: bool | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class AccountPocketCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allocated: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    target: Decimal | None = Field(default=None, ge=0, **_MONEY)
    color: str = Field(default="#0ea5e9", pattern=HEX_COLOR)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class AccountPocketUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    allocated: Decimal | None = Field(default=None, **_MONEY)
    target: Decimal | None = Field(default=None, ge=0, **_MONEY)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class AccountPocketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    name: str
    allocated: Decimal
    target: Decimal | None
    color: str


class BalanceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    period: str
    balance: Decimal


class BalanceSnapshotCreate(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    balance: Decimal = Field(**_MONEY)


class AccountHistoryPoint(BaseModel):
    period: str
    balance: Decimal


class AccountDetail(AccountRead):
    pockets: list[AccountPocketRead] = Field(default_factory=list)
    history: list[AccountHistoryPoint] = Field(default_factory=list)
    transaction_count: int = 0


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(income|expense)$")
    color: str = Field(default="#4f46e5", pattern=HEX_COLOR)
    monthly_budget: Decimal | None = Field(default=None, ge=0, **_MONEY)
    parent_id: int | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class CategoryRead(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived: bool = False
    is_default: bool = False
    spent_this_month: Decimal = Decimal("0.00")


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    monthly_budget: Decimal | None = Field(default=None, ge=0, **_MONEY)
    parent_id: int | None = None
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None


class CategoryBudgetUpdate(BaseModel):
    monthly_budget: Decimal | None = Field(default=None, ge=0, **_MONEY)


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
class TransactionCreate(BaseModel):
    booked_at: date
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(**_MONEY)
    account_id: int
    category_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return _strip_required(value)


class TransactionUpdate(BaseModel):
    booked_at: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount: Decimal | None = Field(default=None, **_MONEY)
    account_id: int | None = None
    category_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None


class TransactionRead(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_name: str = ""
    category_name: str | None = None
    category_kind: str | None = None


class TransactionCount(BaseModel):
    count: int


# --------------------------------------------------------------------------- #
# Dashboard / stats (existing contract)
# --------------------------------------------------------------------------- #
class Overview(BaseModel):
    balance: Decimal
    income_current_month: Decimal
    expenses_current_month: Decimal
    net_current_month: Decimal
    budget_current_month: Decimal
    budget_remaining: Decimal
    uncategorized_count: int


class MonthlyPoint(BaseModel):
    month: str
    income: Decimal
    expenses: Decimal
    net: Decimal


class CategoryBreakdown(BaseModel):
    category_id: int | None
    category_name: str
    amount: Decimal
    budget: Decimal | None = None


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: str
    language: str
    date_format: str
    navigation_style: str
    budget_cycle_start_day: int
    local_merchant_identities: bool
    private_categorization_enabled: bool
    private_categorization_mode: str
    private_categorization_confidence: Decimal


class PreferencesUpdate(BaseModel):
    theme: str | None = Field(default=None, pattern="^(system|light|dark)$")
    language: str | None = Field(default=None, min_length=2, max_length=8)
    date_format: str | None = Field(
        default=None, pattern="^(localized|day-month-year|YYYY-MM-DD)$"
    )
    navigation_style: str | None = Field(default=None, pattern="^(sidebar|topbar|compact)$")
    budget_cycle_start_day: int | None = Field(default=None, ge=1, le=28)
    local_merchant_identities: bool | None = None
    private_categorization_enabled: bool | None = None
    private_categorization_mode: str | None = Field(
        default=None, pattern="^(off|suggest|auto)$"
    )
    private_categorization_confidence: Decimal | None = Field(default=None, ge=0, le=1)


# --------------------------------------------------------------------------- #
# Budget cycles
# --------------------------------------------------------------------------- #
class CycleBounds(BaseModel):
    start: date
    end: date
    start_day: int


class BudgetCycleOverview(BaseModel):
    cycle: CycleBounds
    income: Decimal
    expenses: Decimal
    net: Decimal
    budget_total: Decimal
    budget_remaining: Decimal
    uncategorized_count: int
    envelope_spent: Decimal
    envelope_remaining: Decimal
    upcoming_recurring_amount: Decimal
    upcoming_recurring_count: int
    savings_contributions: Decimal


class EnvelopeRead(BaseModel):
    category_id: int
    category_name: str
    color: str
    budget: Decimal
    spent: Decimal
    remaining: Decimal


class CashflowFlow(BaseModel):
    key: str
    label: str
    inflow: Decimal
    outflow: Decimal
    net: Decimal


class HierarchicalSpendingNode(BaseModel):
    category_id: int | None
    category_name: str
    amount: Decimal
    transaction_count: int
    children: list[HierarchicalSpendingNode] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Categorization rules / inbox / suggestions
# --------------------------------------------------------------------------- #
class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    match_type: str = Field(default="keyword", pattern="^(keyword|beneficiary)$")
    pattern: str = Field(min_length=1, max_length=200)
    category_id: int
    priority: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True

    @field_validator("name", "pattern")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _strip_required(value)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    match_type: str | None = Field(default=None, pattern="^(keyword|beneficiary)$")
    pattern: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    match_type: str
    pattern: str
    category_id: int
    priority: int
    enabled: bool


class RuleApplyResult(BaseModel):
    updated: int
    scanned: int


class InboxItem(BaseModel):
    transaction_id: int
    booked_at: date
    description: str
    amount: Decimal
    account_id: int


class SuggestionResult(BaseModel):
    transaction_id: int
    category_id: int | None
    category_name: str | None
    confidence: Decimal
    explanation: str
    source: str  # rule|history|none
    applied: bool = False


# --------------------------------------------------------------------------- #
# Recurring series
# --------------------------------------------------------------------------- #
_FREQ = "^(weekly|monthly|quarterly|yearly)$"


class RecurringCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    account_id: int
    category_id: int | None = None
    frequency: str = Field(default="monthly", pattern=_FREQ)
    next_due: date
    amount: Decimal | None = Field(default=None, **_MONEY)
    amount_type: str = Field(default="fixed", pattern="^(fixed|variable)$")
    status: str = Field(default="active", pattern="^(active|paused|ended)$")
    confidence: Decimal = Field(default=Decimal("1.00"), ge=0, le=1)

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        return _strip_required(value)


class RecurringUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    frequency: str | None = Field(default=None, pattern=_FREQ)
    next_due: date | None = None
    amount: Decimal | None = Field(default=None, **_MONEY)
    amount_type: str | None = Field(default=None, pattern="^(fixed|variable)$")
    status: str | None = Field(default=None, pattern="^(active|paused|ended)$")
    confidence: Decimal | None = Field(default=None, ge=0, le=1)


class RecurringRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    account_id: int
    category_id: int | None
    frequency: str
    next_due: date
    amount: Decimal | None
    amount_type: str
    status: str
    confidence: Decimal
    account_name: str = ""
    category_name: str | None = None


class ForecastPoint(BaseModel):
    series_id: int
    label: str
    due_date: date
    amount: Decimal
    account_name: str = ""
    category_name: str | None = None
    status: str = "active"


class RecurringChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    series_id: int
    change_type: str
    detected_amount: Decimal | None
    detected_next_due: date | None
    status: str
    note: str | None
    series_label: str = ""
    series_status: str = ""


class DetectResult(BaseModel):
    created_series: int
    created_changes: int


# --------------------------------------------------------------------------- #
# Wealth: debts, holdings, contributions, net worth
# --------------------------------------------------------------------------- #
class DebtCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    principal: Decimal = Field(ge=0, **_MONEY)
    balance: Decimal = Field(ge=0, **_MONEY)
    interest_rate: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    minimum_payment: Decimal | None = Field(default=None, ge=0, **_MONEY)
    account_id: int | None = None
    due_date: date | None = None
    color: str = Field(default="#ef4444", pattern=HEX_COLOR)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class DebtUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    principal: Decimal | None = Field(default=None, ge=0, **_MONEY)
    balance: Decimal | None = Field(default=None, ge=0, **_MONEY)
    interest_rate: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    minimum_payment: Decimal | None = Field(default=None, ge=0, **_MONEY)
    account_id: int | None = None
    due_date: date | None = None
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    archived: bool | None = None


class DebtRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    principal: Decimal
    balance: Decimal
    interest_rate: Decimal | None
    minimum_payment: Decimal | None
    account_id: int | None
    due_date: date | None
    color: str
    archived: bool
    paid: Decimal
    progress: Decimal


class HoldingCreate(BaseModel):
    account_id: int
    name: str = Field(min_length=1, max_length=120)
    symbol: str | None = Field(default=None, max_length=32)
    asset_class: str = Field(default="equity", max_length=32)
    quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    average_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    current_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class HoldingUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    symbol: str | None = Field(default=None, max_length=32)
    asset_class: str | None = Field(default=None, max_length=32)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    average_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    current_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)


class HoldingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    name: str
    symbol: str | None
    asset_class: str
    quantity: Decimal
    average_price: Decimal
    current_price: Decimal
    cost_basis: Decimal
    market_value: Decimal
    gain: Decimal


class ContributionCreate(BaseModel):
    amount: Decimal = Field(**_MONEY)
    occurred_on: date
    note: str | None = Field(default=None, max_length=200)


class ContributionCreateAggregate(ContributionCreate):
    holding_id: int


class ContributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    holding_id: int
    amount: Decimal
    occurred_on: date
    note: str | None


class AllocationSlice(BaseModel):
    asset_class: str
    market_value: Decimal
    weight: Decimal


class PortfolioSummary(BaseModel):
    cost_basis: Decimal
    market_value: Decimal
    gain: Decimal
    contributions_total: Decimal
    holdings: int


class PortfolioSnapshotCreate(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    market_value: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    cost_basis: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class PortfolioSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    market_value: Decimal
    cost_basis: Decimal


class PerformancePoint(BaseModel):
    period: str
    market_value: Decimal
    cost_basis: Decimal
    gain: Decimal
    contributions: Decimal
    cumulative_contributions: Decimal


class NetWorthOverview(BaseModel):
    cash: Decimal
    investments: Decimal
    debts: Decimal
    net_worth: Decimal


class NetWorthPoint(BaseModel):
    period: str
    net_worth: Decimal


# --------------------------------------------------------------------------- #
# Household / local sharing
# --------------------------------------------------------------------------- #
_ROLE = "^(owner|admin|member|viewer)$"


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_name: str = Field(min_length=1, max_length=120)

    @field_validator("name", "owner_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _strip_required(value)


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int
    name: str
    role: str


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    members: list[MemberRead] = Field(default_factory=list)


class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="member", pattern=_ROLE)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class MemberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, pattern=_ROLE)


class SharedLinkCreate(BaseModel):
    account_id: int
    permission: str = Field(default="view", pattern="^(view|edit)$")


class SharedLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int
    account_id: int
    permission: str
    account_name: str = ""
    balance: Decimal = Decimal("0.00")


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal = Field(gt=0, **_MONEY)
    current_amount: Decimal = Field(default=Decimal("0.00"), ge=0, **_MONEY)
    due_date: date | None = None
    account_id: int | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: Decimal | None = Field(default=None, gt=0, **_MONEY)
    due_date: date | None = None
    account_id: int | None = None


class GoalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int | None
    name: str
    target_amount: Decimal
    current_amount: Decimal
    due_date: date | None
    account_id: int | None
    progress: Decimal


class GoalContributionCreate(BaseModel):
    amount: Decimal = Field(gt=0, **_MONEY)
    occurred_on: date
    member_id: int | None = None
    note: str | None = Field(default=None, max_length=200)


# --------------------------------------------------------------------------- #
# Merchant identities (fully local; never fetched from any network service)
# --------------------------------------------------------------------------- #
class MerchantIdentityCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    pattern: str = Field(min_length=1, max_length=200)
    monogram: str = Field(default="", max_length=4)
    color: str = Field(default="#64748b", pattern=HEX_COLOR)

    @field_validator("label", "pattern")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _strip_required(value)


class MerchantIdentityUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    pattern: str | None = Field(default=None, min_length=1, max_length=200)
    monogram: str | None = Field(default=None, max_length=4)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class MerchantIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    pattern: str
    monogram: str
    color: str


class GoalContributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    amount: Decimal
    occurred_on: date
    member_id: int | None
    note: str | None
    member_name: str | None = None


HierarchicalSpendingNode.model_rebuild()
