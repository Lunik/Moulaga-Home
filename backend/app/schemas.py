"""Pydantic request/response schemas for the Moulaga API.

All monetary fields are serialized as strings with two decimals by the router
layer, and every request model performs strict server-side validation.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
_MONEY = {"max_digits": 12, "decimal_places": 2}
DEPRECATED_ACCOUNT_TYPES = frozenset({"investment"})


def _strip_required(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Champ obligatoire")
    return cleaned


def _validate_period(value: str) -> str:
    try:
        date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValueError("Periode invalide") from exc
    return value


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="checking", min_length=1, max_length=32)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    initial_balance: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    institution: str | None = Field(default=None, max_length=120)
    regional_entity: str | None = Field(default=None, max_length=120)
    account_number: str | None = Field(default=None, max_length=120)
    color: str = Field(default="#4f46e5", pattern=HEX_COLOR)
    savings_product: str | None = Field(default=None, max_length=64)
    annual_interest_rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=6, decimal_places=3
    )
    legal_cap: Decimal | None = Field(default=None, ge=0, **_MONEY)

    @field_validator("name", "type", "currency")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator(
        "institution",
        "regional_entity",
        "account_number",
        "savings_product",
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def require_institution_for_regional_entity(self) -> AccountCreate:
        if self.regional_entity is not None and self.institution is None:
            raise ValueError(
                "Une entite regionale necessite un etablissement"
            )
        return self


class AccountRead(AccountCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived: bool = False
    balance: Decimal = Decimal("0.00")
    missing_snapshot_periods: list[str] = Field(default_factory=list)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, min_length=1, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    initial_balance: Decimal | None = Field(default=None, **_MONEY)
    balance: Decimal | None = Field(default=None, **_MONEY)
    institution: str | None = Field(default=None, max_length=120)
    regional_entity: str | None = Field(default=None, max_length=120)
    account_number: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    archived: bool | None = None
    savings_product: str | None = Field(default=None, max_length=64)
    annual_interest_rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=6, decimal_places=3
    )
    legal_cap: Decimal | None = Field(default=None, ge=0, **_MONEY)

    @field_validator("name", "type", "currency")
    @classmethod
    def strip_required(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Champ obligatoire")
        return _strip_required(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator(
        "institution",
        "regional_entity",
        "account_number",
        "savings_product",
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("initial_balance", "balance", "color", "archived")
    @classmethod
    def reject_null(
        cls, value: Decimal | str | bool | None
    ) -> Decimal | str | bool:
        if value is None:
            raise ValueError("Ce champ ne peut pas etre nul")
        return value

    @model_validator(mode="after")
    def reject_ambiguous_balance_update(self) -> AccountUpdate:
        if self.initial_balance is not None and self.balance is not None:
            raise ValueError(
                "Le solde initial et le solde actuel ne peuvent pas etre modifies ensemble"
            )
        return self


class BalanceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    period: str
    balance: Decimal
    attachment_count: int = 0


class BalanceSnapshotImportRequest(BaseModel):
    content: str = Field(max_length=100_000)


class BalanceSnapshotImportResult(BaseModel):
    imported_count: int
    created_count: int
    updated_count: int
    snapshots: list[BalanceSnapshotRead]


class BalanceSnapshotAttachmentRead(BaseModel):
    id: int
    snapshot_id: int
    original_name: str
    storage_path: str
    content_type: str | None
    size: int


class BalanceSnapshotCreate(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    balance: Decimal = Field(**_MONEY)

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        try:
            date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise ValueError("Periode invalide") from exc
        return value


class BalanceSnapshotUpdate(BaseModel):
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    balance: Decimal | None = Field(default=None, **_MONEY)

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("La periode ne peut pas etre nulle")
        try:
            date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise ValueError("Periode invalide") from exc
        return value

    @field_validator("balance")
    @classmethod
    def reject_null_balance(cls, value: Decimal | None) -> Decimal:
        if value is None:
            raise ValueError("Le solde ne peut pas etre nul")
        return value


class AccountHistoryPoint(BaseModel):
    period: str
    balance: Decimal


class InstitutionHistoryPoint(BaseModel):
    period: str
    institution: str
    balance: Decimal


class AccountDetail(AccountRead):
    history: list[AccountHistoryPoint] = Field(default_factory=list)


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
    planned_this_month: Decimal = Decimal("0.00")


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


class CategoryRemovalResult(BaseModel):
    action: str = Field(pattern="^(archived|deleted)$")


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


class PreferencesUpdate(BaseModel):
    theme: str | None = Field(default=None, pattern="^(system|light|dark)$")
    language: str | None = Field(default=None, min_length=2, max_length=8)
    date_format: str | None = Field(
        default=None, pattern="^(localized|day-month-year|YYYY-MM-DD)$"
    )
    navigation_style: str | None = Field(default=None, pattern="^(sidebar|topbar|compact)$")
    budget_cycle_start_day: int | None = Field(default=None, ge=1, le=28)


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
    envelope_planned: Decimal
    envelope_available: Decimal
    upcoming_recurring_amount: Decimal
    upcoming_recurring_count: int
    savings_contributions: Decimal


class EnvelopeRead(BaseModel):
    category_id: int
    category_name: str
    color: str
    parent_id: int | None = None
    budget: Decimal | None
    direct_planned: Decimal = Decimal("0.00")
    planned: Decimal
    available: Decimal | None
    children_budget: Decimal = Decimal("0.00")
    remainder_budget: Decimal | None = None


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
    occurrence_count: int
    children: list[HierarchicalSpendingNode] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Recurring series
# --------------------------------------------------------------------------- #
_FREQ = "^(weekly|monthly|quarterly|yearly)$"
_RECURRING_TYPE = (
    "^(uncategorized|subscription|rent|energy|telecom|auto_insurance|"
    "home_insurance|health_insurance|credit_insurance|loan_payment|tax|"
    "salary|transfer|other)$"
)


class RecurringCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    account_id: int
    category_id: int | None = None
    frequency: str = Field(default="monthly", pattern=_FREQ)
    next_due: date
    amount: Decimal | None = Field(default=None, **_MONEY)
    amount_type: str = Field(default="fixed", pattern="^(fixed|variable)$")
    status: str = Field(default="active", pattern="^(active|paused|ended)$")
    recurring_type: str = Field(default="uncategorized", pattern=_RECURRING_TYPE)
    custom_type: str | None = Field(default=None, max_length=120)
    credit_insurance_rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=6, decimal_places=3
    )

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("custom_type")
    @classmethod
    def strip_custom_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_type_details(self) -> RecurringCreate:
        if self.recurring_type == "other" and self.custom_type is None:
            raise ValueError("Le type libre est requis lorsque le type « Autre » est sélectionné")
        if self.recurring_type != "credit_insurance" and self.credit_insurance_rate is not None:
            raise ValueError("Le taux est réservé aux assurances crédit")
        return self


class RecurringUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    account_id: int | None = None
    category_id: int | None = None
    frequency: str | None = Field(default=None, pattern=_FREQ)
    next_due: date | None = None
    amount: Decimal | None = Field(default=None, **_MONEY)
    amount_type: str | None = Field(default=None, pattern="^(fixed|variable)$")
    status: str | None = Field(default=None, pattern="^(active|paused|ended)$")
    recurring_type: str | None = Field(default=None, pattern=_RECURRING_TYPE)
    custom_type: str | None = Field(default=None, max_length=120)
    credit_insurance_rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=6, decimal_places=3
    )

    @field_validator("label")
    @classmethod
    def strip_optional_label(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("custom_type")
    @classmethod
    def strip_optional_custom_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


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
    recurring_type: str
    custom_type: str | None
    credit_insurance_rate: Decimal | None
    account_name: str = ""
    category_name: str | None = None
    attachment_count: int = 0


class RecurringSeriesAttachmentRead(BaseModel):
    id: int
    series_id: int
    original_name: str
    storage_path: str
    content_type: str | None
    size: int


class ForecastPoint(BaseModel):
    series_id: int
    label: str
    due_date: date
    amount: Decimal
    account_name: str = ""
    category_name: str | None = None
    status: str = "active"


# --------------------------------------------------------------------------- #
# Wealth: debts, real estate, holdings, contributions, net worth
# --------------------------------------------------------------------------- #
_DEBT_TYPE = "^(consumer_credit|mortgage|other)$"


class DebtCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    debt_type: str = Field(default="other", pattern=_DEBT_TYPE)
    principal: Decimal = Field(ge=0, **_MONEY)
    balance: Decimal = Field(ge=0, **_MONEY)
    interest_rate: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    minimum_payment: Decimal | None = Field(default=None, ge=0, **_MONEY)
    account_id: int | None = None
    recurring_series_repayment_id: int | None = None
    recurring_series_insurance_id: int | None = None
    due_date: date | None = None
    color: str = Field(default="#ef4444", pattern=HEX_COLOR)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class DebtUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    debt_type: str | None = Field(default=None, pattern=_DEBT_TYPE)
    principal: Decimal | None = Field(default=None, ge=0, **_MONEY)
    balance: Decimal | None = Field(default=None, ge=0, **_MONEY)
    interest_rate: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    minimum_payment: Decimal | None = Field(default=None, ge=0, **_MONEY)
    account_id: int | None = None
    recurring_series_repayment_id: int | None = None
    recurring_series_insurance_id: int | None = None
    due_date: date | None = None
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None


class DebtRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    debt_type: str
    principal: Decimal
    balance: Decimal
    interest_rate: Decimal | None
    minimum_payment: Decimal | None
    account_id: int | None
    recurring_series_repayment_id: int | None
    recurring_series_insurance_id: int | None
    recurring_series_name_repayment: str | None = None
    recurring_series_name_insurance: str | None = None
    due_date: date | None
    color: str
    archived: bool
    paid: Decimal
    progress: Decimal
    attachment_count: int = 0


class DebtAttachmentRead(BaseModel):
    id: int
    debt_id: int
    original_name: str
    storage_path: str
    content_type: str | None
    size: int


_PROPERTY_TYPE = (
    "^(primary_residence|secondary_residence|rental|commercial|land|other)$"
)


def _validate_acquired_on(value: date | None) -> date | None:
    if value is not None and value > date.today():
        raise ValueError("La date d'acquisition ne peut pas etre future")
    return value


def _validate_debt_ids(value: list[int]) -> list[int]:
    if any(debt_id <= 0 for debt_id in value):
        raise ValueError("Les identifiants de dette doivent être positifs")
    if len(value) != len(set(value)):
        raise ValueError("Une dette ne peut être associée qu'une seule fois")
    return value


class RealEstateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    property_type: str = Field(default="primary_residence", pattern=_PROPERTY_TYPE)
    address: str | None = Field(default=None, max_length=200)
    acquired_on: date | None = None
    purchase_price: Decimal = Field(ge=0, **_MONEY)
    current_value: Decimal | None = Field(default=None, ge=0, **_MONEY)
    ownership_share: Decimal = Field(
        default=Decimal("100.00"), gt=0, le=100, max_digits=5, decimal_places=2
    )
    debt_ids: list[int] = Field(default_factory=list, max_length=100)
    icon_path: str | None = Field(default=None, max_length=512)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("address")
    @classmethod
    def strip_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("acquired_on")
    @classmethod
    def validate_acquired_on(cls, value: date | None) -> date | None:
        return _validate_acquired_on(value)

    @field_validator("debt_ids")
    @classmethod
    def validate_debt_ids(cls, value: list[int]) -> list[int]:
        return _validate_debt_ids(value)


class RealEstateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    property_type: str | None = Field(default=None, pattern=_PROPERTY_TYPE)
    address: str | None = Field(default=None, max_length=200)
    acquired_on: date | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, **_MONEY)
    current_value: Decimal | None = Field(default=None, ge=0, **_MONEY)
    ownership_share: Decimal | None = Field(
        default=None, gt=0, le=100, max_digits=5, decimal_places=2
    )
    debt_ids: list[int] = Field(default_factory=list, max_length=100)
    icon_path: str | None = Field(default=None, max_length=512)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("address")
    @classmethod
    def strip_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("acquired_on")
    @classmethod
    def validate_acquired_on(cls, value: date | None) -> date | None:
        return _validate_acquired_on(value)

    @field_validator("debt_ids")
    @classmethod
    def validate_debt_ids(cls, value: list[int]) -> list[int]:
        return _validate_debt_ids(value)

class RealEstateDebtRead(BaseModel):
    id: int
    name: str
    balance: Decimal
    recurring_series_repayment_id: int | None
    recurring_series_insurance_id: int | None
    recurring_series_name_repayment: str | None
    recurring_series_name_insurance: str | None


class RealEstateRead(BaseModel):
    id: int
    name: str
    property_type: str
    address: str | None
    acquired_on: date | None
    purchase_price: Decimal
    current_value: Decimal | None
    ownership_share: Decimal
    debt_ids: list[int]
    debts: list[RealEstateDebtRead]
    debt_balance: Decimal
    owned_purchase_price: Decimal
    owned_value: Decimal
    gain: Decimal
    net_equity: Decimal
    attachment_count: int = 0
    icon_path: str | None = None


class RealEstateAttachmentRead(BaseModel):
    id: int
    asset_id: int
    original_name: str
    storage_path: str
    content_type: str | None
    size: int


DocumentKind = Literal[
    "snapshot",
    "recurring",
    "debt",
    "real_estate",
    "work_contract",
    "payslip",
]


class DocumentRead(BaseModel):
    id: int
    kind: DocumentKind
    resource_id: int
    account_id: int | None
    resource_label: str
    resource_context: str
    reference: str | None
    original_name: str
    content_type: str | None
    size: int
    created_at: datetime
    download_url: str


class DocumentResourceRead(BaseModel):
    kind: DocumentKind
    resource_id: int
    account_id: int | None
    label: str
    context: str
    reference: str | None
    can_upload: bool


class DocumentKindSummary(BaseModel):
    kind: DocumentKind
    label: str
    total_resources: int
    covered_resources: int
    missing_resources: int
    document_count: int


class DocumentCenterStats(BaseModel):
    total_documents: int
    total_size: int
    total_resources: int
    covered_resources: int
    missing_resources: int


class DocumentCenterRead(BaseModel):
    stats: DocumentCenterStats
    kinds: list[DocumentKindSummary]
    documents: list[DocumentRead]
    resources_without_documents: list[DocumentResourceRead]
    ignored_resources: list[DocumentResourceRead]


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
    current_price: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None


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
    operation_count: int


class NewHoldingForOperation(BaseModel):
    account_id: int
    name: str = Field(min_length=1, max_length=120)
    symbol: str | None = Field(default=None, max_length=32)
    asset_class: str = Field(default="equity", max_length=32)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required(value)


class HoldingOperationCreate(BaseModel):
    holding_id: int | None = None
    new_holding: NewHoldingForOperation | None = None
    operation_type: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    @model_validator(mode="after")
    def validate_target(self) -> HoldingOperationCreate:
        if (self.holding_id is None) == (self.new_holding is None):
            raise ValueError("Choisissez un actif existant ou renseignez un nouvel actif")
        if self.new_holding is not None and self.operation_type == "sell":
            raise ValueError("Un nouvel actif doit commencer par un achat")
        return self


class HoldingOperationUpdate(BaseModel):
    operation_type: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class HoldingOperationRead(BaseModel):
    id: int
    holding_id: int
    operation_type: Literal["buy", "sell"]
    quantity: Decimal
    unit_price: Decimal
    total_value: Decimal
    quantity_delta: Decimal
    cash_flow: Decimal
    created_at: datetime


class HoldingOperationResult(BaseModel):
    holding: HoldingRead
    operation: HoldingOperationRead


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
    properties: int


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
    real_estate: Decimal
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
# Work module schemas
# --------------------------------------------------------------------------- #
class WorkContractCreate(BaseModel):
    employer: str = Field(min_length=1, max_length=120)
    position: str = Field(min_length=1, max_length=120)
    contract_type: str = Field(default="CDI", max_length=32)
    start_date: date
    end_date: date | None = None
    gross_annual_salary: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    payment_period_months: int = Field(default=12, ge=1, le=24)
    work_percentage: int = Field(default=100, ge=1, le=100)
    recurring_series_id: int | None = None
    status: str = Field(default="active", pattern="^(active|ended)$")
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("employer", "position", "contract_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip_required(value)


class WorkContractUpdate(BaseModel):
    employer: str | None = Field(default=None, min_length=1, max_length=120)
    position: str | None = Field(default=None, min_length=1, max_length=120)
    contract_type: str | None = Field(default=None, max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    gross_annual_salary: Decimal | None = Field(default=None, **_MONEY)
    payment_period_months: int | None = Field(default=None, ge=1, le=24)
    work_percentage: int | None = Field(default=None, ge=1, le=100)
    recurring_series_id: int | None = None
    status: str | None = Field(default=None, pattern="^(active|ended)$")
    notes: str | None = Field(default=None, max_length=500)


class WorkContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employer: str
    position: str
    contract_type: str
    start_date: date
    end_date: date | None
    gross_annual_salary: Decimal
    payment_period_months: int
    work_percentage: int
    recurring_series_id: int | None
    status: str
    notes: str | None
    attachment_count: int = 0


class WorkContractAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int
    original_name: str
    stored_path: str
    content_type: str | None
    size: int


class PaySlipAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payslip_id: int
    original_name: str
    stored_path: str
    content_type: str | None
    size: int


class PaySlipCreate(BaseModel):
    contract_id: int | None = None
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    gross_salary: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    taxable_net: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    net_before_tax: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    pas_rate: Decimal = Field(default=Decimal("0.00"), ge=0, le=100, max_digits=5, decimal_places=2)
    pas_amount: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    net_after_tax: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    bonuses: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    employer_contributions: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    employer_profit_sharing: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    hours_worked: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    overtime_hours: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        return _validate_period(value)


class PaySlipUpdate(BaseModel):
    contract_id: int | None = None
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    gross_salary: Decimal | None = Field(default=None, **_MONEY)
    taxable_net: Decimal | None = Field(default=None, **_MONEY)
    net_before_tax: Decimal | None = Field(default=None, **_MONEY)
    pas_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    pas_amount: Decimal | None = Field(default=None, **_MONEY)
    net_after_tax: Decimal | None = Field(default=None, **_MONEY)
    bonuses: Decimal | None = Field(default=None, **_MONEY)
    employer_contributions: Decimal | None = Field(default=None, **_MONEY)
    employer_profit_sharing: Decimal | None = Field(default=None, **_MONEY)
    hours_worked: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    overtime_hours: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str | None) -> str | None:
        return _validate_period(value) if value is not None else None


class PaySlipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int | None
    period: str
    gross_salary: Decimal
    taxable_net: Decimal
    net_before_tax: Decimal
    pas_rate: Decimal
    pas_amount: Decimal
    net_after_tax: Decimal
    bonuses: Decimal
    employer_contributions: Decimal
    employer_profit_sharing: Decimal
    hours_worked: Decimal | None
    overtime_hours: Decimal | None
    notes: str | None
    attachments: list[PaySlipAttachmentRead] = Field(default_factory=list)


class PensionProfileCreateOrUpdate(BaseModel):
    birth_year: int = Field(default=1990, ge=1930, le=2020)
    target_retirement_age: int = Field(default=64, ge=50, le=75)
    validated_quarters: int = Field(default=40, ge=0, le=300)
    required_quarters: int = Field(default=172, ge=1, le=300)
    estimated_monthly_pension: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    target_monthly_income: Decimal = Field(default=Decimal("0.00"), **_MONEY)
    notes: str | None = Field(default=None, max_length=500)


class PensionProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    birth_year: int
    target_retirement_age: int
    validated_quarters: int
    required_quarters: int
    estimated_monthly_pension: Decimal
    target_monthly_income: Decimal
    notes: str | None


class WorkSummary(BaseModel):
    active_contracts_count: int
    latest_net_after_tax: Decimal
    ytd_taxable_net: Decimal
    ytd_net_after_tax: Decimal
    ytd_gross: Decimal
    ytd_bonuses: Decimal
    ytd_profit_sharing: Decimal
    average_pas_rate: Decimal
    estimated_pension: Decimal
    validated_quarters: int
    required_quarters: int



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
