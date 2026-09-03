"""Database models for Moulaga.

The persistent schema is the single source of truth after the one-shot
Banque_v3 migration. Every column stores validated, non-sensitive data and
monetary amounts always use ``Numeric(12, 2)`` (two decimals).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


ZERO = Decimal("0.00")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32), default="checking")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#4f46e5")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    pockets: Mapped[list[AccountPocket]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    snapshots: Mapped[list[BalanceSnapshot]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class AccountPocket(Base):
    """A named sub-allocation (enveloppe/pot) inside an account."""

    __tablename__ = "account_pockets"
    __table_args__ = (UniqueConstraint("account_id", "name", name="uq_pocket_account_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    allocated: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    target: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#0ea5e9")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship(back_populates="pockets")


class BalanceSnapshot(Base):
    """Monthly closing balance snapshot for an account."""

    __tablename__ = "balance_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "period", name="uq_snapshot_account_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship(back_populates="snapshots")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("name", "kind", name="uq_categories_name_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(16), default="#4f46e5")
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")
    parent: Mapped[Category | None] = relationship(remote_side="Category.id")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("source_hash", name="uq_transactions_source_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booked_at: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship(back_populates="transactions")


class Preferences(Base):
    """Application-wide singleton preferences (row id fixed to 1)."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme: Mapped[str] = mapped_column(String(16), default="system")
    language: Mapped[str] = mapped_column(String(8), default="fr")
    date_format: Mapped[str] = mapped_column(String(20), default="localized")
    navigation_style: Mapped[str] = mapped_column(String(16), default="sidebar")
    budget_cycle_start_day: Mapped[int] = mapped_column(Integer, default=1)
    local_merchant_identities: Mapped[bool] = mapped_column(Boolean, default=False)
    private_categorization_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    private_categorization_mode: Mapped[str] = mapped_column(String(16), default="off")
    private_categorization_confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.60")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CategorizationRule(Base):
    """Deterministic rule mapping a description/beneficiary to a category."""

    __tablename__ = "categorization_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    match_type: Mapped[str] = mapped_column(String(16), default="keyword")  # keyword|beneficiary
    pattern: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    category: Mapped[Category] = relationship()


class RecurringSeries(Base):
    __tablename__ = "recurring_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    frequency: Mapped[str] = mapped_column(String(16), default="monthly")
    next_due: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    amount_type: Mapped[str] = mapped_column(String(16), default="fixed")  # fixed|variable
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("1.00"))
    match_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    changes: Mapped[list[RecurringChange]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )


class RecurringChange(Base):
    """A detected drift in a recurring series awaiting accept/reject."""

    __tablename__ = "recurring_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="CASCADE"), index=True
    )
    change_type: Mapped[str] = mapped_column(String(16), default="amount")  # amount|schedule
    detected_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    detected_next_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    series: Mapped[RecurringSeries] = relationship(back_populates="changes")


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    principal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    minimum_payment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#ef4444")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32), default="equity")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    average_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    current_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship()
    contributions: Mapped[list[Contribution]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )


class Contribution(Base):
    """A cash contribution into a holding (investment deposit)."""

    __tablename__ = "contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    holding: Mapped[Holding] = relationship(back_populates="contributions")


class PortfolioSnapshot(Base):
    """A persisted monthly valuation of the whole portfolio."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("period", name="uq_portfolio_snapshot_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    market_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MerchantIdentity(Base):
    """A fully-local merchant label. No external logo/URL is ever stored or
    fetched: only a user-provided monogram and color."""

    __tablename__ = "merchant_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    pattern: Mapped[str] = mapped_column(String(200), index=True)
    monogram: Mapped[str] = mapped_column(String(4), default="")
    color: Mapped[str] = mapped_column(String(16), default="#64748b")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    members: Mapped[list[HouseholdMember]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )


class HouseholdMember(Base):
    """A local profile inside a household. There is no remote auth: mutations
    must supply an ``actor_id`` matching a member; roles gate what is allowed."""

    __tablename__ = "household_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner|admin|member|viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    household: Mapped[Household] = relationship(back_populates="members")


class SharedAccountLink(Base):
    __tablename__ = "shared_account_links"
    __table_args__ = (
        UniqueConstraint("household_id", "account_id", name="uq_shared_household_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    permission: Mapped[str] = mapped_column(String(8), default="view")  # view|edit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int | None] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    contributions: Mapped[list[GoalContribution]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class GoalContribution(Base):
    __tablename__ = "goal_contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("household_members.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    goal: Mapped[Goal] = relationship(back_populates="contributions")
