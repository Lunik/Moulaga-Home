"""Database models for Moulaga.

The persistent SQLite schema stores validated local data, and monetary amounts
always use ``Numeric(12, 2)`` (two decimals).
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
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, synonym


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


ZERO = Decimal("0.00")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    type: Mapped[str] = mapped_column(String(32), default="checking")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    regional_entity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#4f46e5")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    savings_product: Mapped[str | None] = mapped_column(String(64), nullable=True)
    annual_interest_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    legal_cap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    snapshots: Mapped[list[BalanceSnapshot]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    owners: Mapped[list[AccountOwner]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


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
    document_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account] = relationship(back_populates="snapshots")
    attachments: Mapped[list[BalanceSnapshotAttachment]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class BalanceSnapshotAttachment(Base):
    __tablename__ = "balance_snapshot_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("balance_snapshots.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    snapshot: Mapped[BalanceSnapshot] = relationship(back_populates="attachments")


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

    parent: Mapped[Category | None] = relationship(remote_side="Category.id")


class Preferences(Base):
    """Application-wide singleton preferences (row id fixed to 1)."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme: Mapped[str] = mapped_column(String(16), default="system")
    date_format: Mapped[str] = mapped_column(String(20), default="localized")
    navigation_style: Mapped[str] = mapped_column(String(16), default="sidebar")
    budget_cycle_start_day: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


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
    recurring_type: Mapped[str] = mapped_column(String(32), default="uncategorized", index=True)
    custom_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    credit_insurance_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    document_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    amount_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    attachments: Mapped[list[RecurringSeriesAttachment]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )


class RecurringSeriesAttachment(Base):
    __tablename__ = "recurring_series_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    series: Mapped[RecurringSeries] = relationship(back_populates="attachments")


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    debt_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    principal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    minimum_payment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    recurring_series_repayment_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recurring_series_insurance_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#ef4444")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    document_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    balance_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    recurring_series_repayment: Mapped[RecurringSeries | None] = relationship(
        foreign_keys=[recurring_series_repayment_id]
    )
    recurring_series_insurance: Mapped[RecurringSeries | None] = relationship(
        foreign_keys=[recurring_series_insurance_id]
    )
    attachments: Mapped[list[DebtAttachment]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )
    owners: Mapped[list[DebtOwner]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )


class DebtAttachment(Base):
    __tablename__ = "debt_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(
        ForeignKey("debts.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    debt: Mapped[Debt] = relationship(back_populates="attachments")


class RealEstateAsset(Base):
    __tablename__ = "real_estate_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    property_type: Mapped[str] = mapped_column(String(32), default="primary_residence")
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ownership_share: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100.00")
    )
    icon_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    value_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    debt_links: Mapped[list[RealEstateDebtLink]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )
    attachments: Mapped[list[RealEstateAttachment]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    owners: Mapped[list[RealEstateAssetOwner]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class RealEstateDebtLink(Base):
    __tablename__ = "real_estate_debt_links"
    __table_args__ = (
        UniqueConstraint("debt_id", name="uq_real_estate_debt_links_debt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("real_estate_assets.id", ondelete="CASCADE"), index=True
    )
    debt_id: Mapped[int] = mapped_column(
        ForeignKey("debts.id", ondelete="CASCADE"), index=True
    )

    asset: Mapped[RealEstateAsset] = relationship(back_populates="debt_links")
    debt: Mapped[Debt] = relationship()


class RealEstateAttachment(Base):
    __tablename__ = "real_estate_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("real_estate_assets.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[RealEstateAsset] = relationship(back_populates="attachments")


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32), default="equity")
    quantity: Mapped[Decimal] = mapped_column(Numeric(22, 10), default=Decimal("0"))
    average_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    current_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    price_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    account: Mapped[Account] = relationship()
    contributions: Mapped[list[Contribution]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )
    operations: Mapped[list[HoldingOperation]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )


class HoldingOperation(Base):
    __tablename__ = "holding_operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), index=True
    )
    operation_type: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(22, 10))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    occurred_on: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    holding: Mapped[Holding] = relationship(back_populates="operations")


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


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    members: Mapped[list[HouseholdMember]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )

    @property
    def profiles(self) -> list[HouseholdMember]:
        """Profile-oriented alias for the established household-member model."""
        return self.members


class HouseholdMember(Base):
    """A person using the local singleton household."""

    __tablename__ = "household_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default="member")  # admin|member
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#4f46e5")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    pin_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pin_failed_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    pin_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    household: Mapped[Household] = relationship(back_populates="members")
    account_ownerships: Mapped[list[AccountOwner]] = relationship(back_populates="member")
    real_estate_ownerships: Mapped[list[RealEstateAssetOwner]] = relationship(
        back_populates="member"
    )
    debt_ownerships: Mapped[list[DebtOwner]] = relationship(back_populates="member")
    sessions: Mapped[list[ProfileSession]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


# ``Profile`` describes the API concept while retaining the long-lived model
# name/table used by existing household and goal references.
Profile = HouseholdMember


class AccountOwner(Base):
    """A profile's share of an account; equal weights are the current policy."""

    __tablename__ = "account_owners"
    __table_args__ = (UniqueConstraint("account_id", "member_id", name="uq_account_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="RESTRICT"), index=True
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))

    account: Mapped[Account] = relationship(back_populates="owners")
    member: Mapped[HouseholdMember] = relationship(back_populates="account_ownerships")
    profile_id = synonym("member_id")


class RealEstateAssetOwner(Base):
    """A profile's share of the household portion of a real-estate asset."""

    __tablename__ = "real_estate_owners"
    __table_args__ = (UniqueConstraint("asset_id", "member_id", name="uq_real_estate_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("real_estate_assets.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="RESTRICT"), index=True
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))

    asset: Mapped[RealEstateAsset] = relationship(back_populates="owners")
    member: Mapped[HouseholdMember] = relationship(back_populates="real_estate_ownerships")
    profile_id = synonym("member_id")


# Compatibility while wealth routes migrate to the explicit asset owner name.
RealEstateOwner = RealEstateAssetOwner


class DebtOwner(Base):
    """A profile's share of a debt independently from its repayment account."""

    __tablename__ = "debt_owners"
    __table_args__ = (UniqueConstraint("debt_id", "member_id", name="uq_debt_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="RESTRICT"), index=True
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))

    debt: Mapped[Debt] = relationship(back_populates="owners")
    member: Mapped[HouseholdMember] = relationship(back_populates="debt_ownerships")
    profile_id = synonym("member_id")


class ProfileSession(Base):
    """Opaque browser-session tokens, stored only as SHA-256 digests."""

    __tablename__ = "profile_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    profile: Mapped[Profile] = relationship(back_populates="sessions")


class UpdatePromptDismissal(Base):
    __tablename__ = "update_prompt_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "prompt_id",
            name="uq_update_prompt_dismissal_profile_prompt",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="CASCADE"), index=True
    )
    prompt_id: Mapped[str] = mapped_column(String(255))
    snoozed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


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


class WorkContract(Base):
    __tablename__ = "work_contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    employer: Mapped[str] = mapped_column(String(120))
    position: Mapped[str] = mapped_column(String(120))
    contract_type: Mapped[str] = mapped_column(String(32), default="CDI")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gross_annual_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    payment_period_months: Mapped[int] = mapped_column(Integer, default=12)
    work_percentage: Mapped[int] = mapped_column(Integer, default=100)
    recurring_series_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )

    slips: Mapped[list[PaySlip]] = relationship(
        back_populates="contract", passive_deletes=True
    )
    attachments: Mapped[list[WorkContractAttachment]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    recurring_series: Mapped[RecurringSeries | None] = relationship()
    profile: Mapped[Profile] = relationship()


class WorkContractAttachment(Base):
    __tablename__ = "work_contract_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("work_contracts.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    contract: Mapped[WorkContract] = relationship(back_populates="attachments")


class PaySlip(Base):
    __tablename__ = "pay_slips"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    gross_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    taxable_net: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    net_before_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    pas_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=ZERO)
    pas_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    net_after_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    bonuses: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    employer_contributions: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    employer_profit_sharing: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    hours_worked: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    overtime_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    contract: Mapped[WorkContract | None] = relationship(back_populates="slips")
    profile: Mapped[Profile] = relationship()
    attachments: Mapped[list[PaySlipAttachment]] = relationship(
        back_populates="payslip", cascade="all, delete-orphan"
    )


class PaySlipAttachment(Base):
    __tablename__ = "pay_slip_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    payslip_id: Mapped[int] = mapped_column(
        ForeignKey("pay_slips.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    payslip: Mapped[PaySlip] = relationship(back_populates="attachments")


class PensionProfile(Base):
    __tablename__ = "pension_profiles"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_pension_profile_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("household_members.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    birth_year: Mapped[int] = mapped_column(Integer, default=1990)
    birth_month: Mapped[int] = mapped_column(Integer, default=1)
    target_retirement_age: Mapped[int] = mapped_column(Integer, default=64)
    validated_quarters: Mapped[int] = mapped_column(Integer, default=40)
    required_quarters: Mapped[int] = mapped_column(Integer, default=172)
    estimated_monthly_pension: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    target_monthly_income: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=ZERO)
    income_growth_scenario: Mapped[str] = mapped_column(
        String(24), default="regular"
    )
    future_work_percentage: Mapped[int] = mapped_column(Integer, default=100)
    planned_unemployment_months: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    profile: Mapped[Profile] = relationship()
