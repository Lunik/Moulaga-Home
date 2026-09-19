"""Wealth: debts, investment holdings, contributions and net-worth analytics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import (
    account_owner_ids,
    allocate_equal_shares,
    require_account,
    require_holding_account,
    visible_account_ids,
)
from ..account_balances import account_balances
from ..attachments import attachment_path, remove_attachment, store_attachment
from ..common import local_today, money
from ..db import get_session
from ..debt_recurring import (
    build_debt_recurring_series_insurance,
    build_debt_recurring_series_repayment,
    debt_payment,
    recurring_amount,
)
from ..models import (
    BalanceSnapshot,
    Contribution,
    Debt,
    DebtAttachment,
    DebtOwner,
    Holding,
    HoldingOperation,
    PortfolioSnapshot,
    RealEstateAsset,
    RealEstateAssetOwner,
    RealEstateAttachment,
    RealEstateDebtLink,
    RecurringSeries,
)
from ..models import (
    HouseholdMember as Profile,
)
from ..profile_session import require_active_profile
from ..schemas import (
    AllocationSlice,
    AssetPerformancePoint,
    ContributionCreate,
    ContributionCreateAggregate,
    ContributionRead,
    DebtAttachmentRead,
    DebtCreate,
    DebtRead,
    DebtUpdate,
    HoldingCreate,
    HoldingOperationCreate,
    HoldingOperationRead,
    HoldingOperationResult,
    HoldingOperationUpdate,
    HoldingRead,
    HoldingUpdate,
    NetWorthOverview,
    NetWorthPoint,
    PerformancePoint,
    PortfolioSnapshotCreate,
    PortfolioSnapshotRead,
    PortfolioSummary,
    RealEstateAttachmentRead,
    RealEstateCreate,
    RealEstateDebtRead,
    RealEstateRead,
    RealEstateUpdate,
)

router = APIRouter(tags=["wealth"])

_CENT = Decimal("0.01")


class _ProfileReference(BaseModel):
    id: int
    name: str
    avatar: str | None
    color: str


class _DebtCreate(DebtCreate):
    owner_profile_ids: list[int] | None = Field(default=None, max_length=100)


class _DebtUpdate(DebtUpdate):
    owner_profile_ids: list[int] | None = Field(default=None, max_length=100)


class _DebtRead(DebtRead):
    owners: list[_ProfileReference]
    active_profile_balance: Decimal
    total_balance: Decimal
    active_profile_minimum_payment: Decimal
    total_minimum_payment: Decimal


class _RealEstateCreate(RealEstateCreate):
    owner_profile_ids: list[int] | None = Field(default=None, max_length=100)


class _RealEstateUpdate(RealEstateUpdate):
    owner_profile_ids: list[int] | None = Field(default=None, max_length=100)


class _RealEstateRead(RealEstateRead):
    owners: list[_ProfileReference]
    active_profile_purchase_price: Decimal
    active_profile_owned_value: Decimal
    active_profile_debt_balance: Decimal
    active_profile_gain: Decimal
    total_owned_value: Decimal
    active_profile_net_equity: Decimal
    total_net_equity: Decimal


def _equal_owner_shares(
    total: Decimal,
    owner_ids: Iterable[int],
) -> dict[int, Decimal]:
    """Split a stored monetary total without losing cents.

    Association tables guarantee unique owners in production; rejecting
    duplicates here keeps a malformed relationship from silently double
    counting a resource.
    """
    ordered_owner_ids = sorted(owner_ids)
    if not ordered_owner_ids:
        raise ValueError("Une ressource doit avoir au moins un proprietaire")
    if len(ordered_owner_ids) != len(set(ordered_owner_ids)):
        raise ValueError("Un proprietaire ne peut apparaitre qu'une fois")

    total = money(total)
    base_share = (total / len(ordered_owner_ids)).quantize(_CENT, rounding=ROUND_DOWN)
    remainder_cents = int((total - base_share * len(ordered_owner_ids)) / _CENT)
    increment = _CENT if remainder_cents > 0 else -_CENT
    shares = {owner_id: base_share for owner_id in ordered_owner_ids}
    for owner_id in ordered_owner_ids[: abs(remainder_cents)]:
        shares[owner_id] += increment
    return shares


def _equal_owner_quantity_shares(
    total: Decimal,
    owner_ids: Iterable[int],
) -> dict[int, Decimal]:
    ordered_owner_ids = sorted(owner_ids)
    if not ordered_owner_ids:
        raise ValueError("Une ressource doit avoir au moins un proprietaire")
    if len(ordered_owner_ids) != len(set(ordered_owner_ids)):
        raise ValueError("Un proprietaire ne peut apparaitre qu'une fois")
    quantum = Decimal("0.0000000001")
    total = total.quantize(quantum)
    base_share = (total / len(ordered_owner_ids)).quantize(quantum, rounding=ROUND_DOWN)
    remainder_units = int((total - base_share * len(ordered_owner_ids)) / quantum)
    shares = {owner_id: base_share for owner_id in ordered_owner_ids}
    for owner_id in ordered_owner_ids[:remainder_units]:
        shares[owner_id] += quantum
    return shares


def _real_estate_owner_values(
    asset: RealEstateAsset,
    owner_ids: Iterable[int],
) -> dict[int, tuple[Decimal, Decimal]]:
    """Allocate the household-owned part of a property among its profiles."""
    household_purchase, household_value = _real_estate_owned_values(asset)
    purchase_shares = _equal_owner_shares(household_purchase, owner_ids)
    value_shares = _equal_owner_shares(household_value, owner_ids)
    return {
        owner_id: (purchase_shares[owner_id], value_shares[owner_id])
        for owner_id in purchase_shares
    }


def _profile_reference(profile: Profile) -> dict[str, int | str | None]:
    return {
        "id": profile.id,
        "name": profile.name,
        "avatar": profile.avatar,
        "color": profile.color,
    }


async def _validate_owner_profile_ids(
    session: AsyncSession,
    owner_profile_ids: list[int] | None,
    *,
    default_profile_id: int,
) -> list[int]:
    owner_ids = owner_profile_ids if owner_profile_ids is not None else [default_profile_id]
    if not owner_ids:
        raise HTTPException(status_code=422, detail="Au moins un proprietaire est requis")
    if len(owner_ids) != len(set(owner_ids)):
        raise HTTPException(status_code=422, detail="Un proprietaire ne peut apparaitre qu'une fois")
    profiles = (
        await session.execute(
            select(Profile).where(Profile.id.in_(owner_ids), Profile.active.is_(True))
        )
    ).scalars().all()
    if len(profiles) != len(owner_ids):
        raise HTTPException(status_code=422, detail="Profil proprietaire introuvable ou archive")
    return sorted(owner_ids)


async def _replace_resource_owners(
    session: AsyncSession,
    resource: Debt | RealEstateAsset,
    owner_ids: list[int],
) -> None:
    if isinstance(resource, Debt):
        owner_type = DebtOwner
        foreign_key = "debt_id"
    else:
        owner_type = RealEstateAssetOwner
        foreign_key = "asset_id"
    await session.execute(
        sql_delete(owner_type).where(getattr(owner_type, foreign_key) == resource.id)
    )
    await session.flush()
    session.add_all(
        owner_type(**{foreign_key: resource.id, "member_id": profile_id})
        for profile_id in owner_ids
    )


async def _debt_owner_profiles(session: AsyncSession, debt_id: int) -> list[Profile]:
    return list(
        (
            await session.execute(
                select(Profile)
                .join(DebtOwner, DebtOwner.member_id == Profile.id)
                .where(DebtOwner.debt_id == debt_id)
                .order_by(Profile.id)
            )
        ).scalars().all()
    )


async def _real_estate_owner_profiles(
    session: AsyncSession,
    asset_id: int,
) -> list[Profile]:
    return list(
        (
            await session.execute(
                select(Profile)
                .join(RealEstateAssetOwner, RealEstateAssetOwner.member_id == Profile.id)
                .where(RealEstateAssetOwner.asset_id == asset_id)
                .order_by(Profile.id)
            )
        ).scalars().all()
    )


async def _portfolio_snapshots_are_single_profile_only(
    session: AsyncSession,
) -> bool:
    return (await session.scalar(select(func.count()).select_from(Profile))) == 1


@dataclass(slots=True)
class HoldingRealizedMetrics:
    realized_cost_basis: Decimal = Decimal("0")
    realized_gain: Decimal = Decimal("0")


@dataclass(slots=True)
class HoldingOperationMetrics:
    realized_cost_basis: Decimal | None
    realized_gain: Decimal | None


@dataclass(slots=True)
class HoldingPerformanceState:
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")
    last_price: Decimal = Decimal("0")
    realized_cost_basis: Decimal = Decimal("0")
    realized_gain: Decimal = Decimal("0")


def _holding_operation_sort_key(
    operation: HoldingOperation,
) -> tuple[date, str, int]:
    return (
        operation.occurred_on,
        operation.created_at.isoformat() if operation.created_at else "9999",
        operation.id or 0,
    )


def _holding_realized_metrics(
    operations: list[HoldingOperation],
) -> HoldingRealizedMetrics:
    quantity = Decimal("0")
    average_price = Decimal("0")
    realized_cost_basis = Decimal("0")
    realized_gain = Decimal("0")
    for operation in sorted(operations, key=_holding_operation_sort_key):
        operation_quantity = Decimal(operation.quantity)
        operation_price = Decimal(operation.unit_price)
        if operation.operation_type == "buy":
            next_quantity = quantity + operation_quantity
            total_cost = quantity * average_price + operation_quantity * operation_price
            quantity = next_quantity
            average_price = (total_cost / next_quantity).quantize(Decimal("0.000001"))
            continue
        if operation_quantity > quantity:
            raise ValueError("Une vente historique depasse la position disponible")
        sale_cost_basis = operation_quantity * average_price
        realized_cost_basis += sale_cost_basis
        realized_gain += operation_quantity * (operation_price - average_price)
        quantity -= operation_quantity
        if quantity == 0:
            average_price = Decimal("0")
    return HoldingRealizedMetrics(
        realized_cost_basis=realized_cost_basis,
        realized_gain=realized_gain,
    )


def _holding_operation_metrics(
    operations: list[HoldingOperation],
) -> dict[int, HoldingOperationMetrics]:
    quantity = Decimal("0")
    average_price = Decimal("0")
    metrics: dict[int, HoldingOperationMetrics] = {}
    for operation in sorted(operations, key=_holding_operation_sort_key):
        operation_quantity = Decimal(operation.quantity)
        operation_price = Decimal(operation.unit_price)
        if operation.operation_type == "buy":
            next_quantity = quantity + operation_quantity
            total_cost = quantity * average_price + operation_quantity * operation_price
            quantity = next_quantity
            average_price = (total_cost / next_quantity).quantize(Decimal("0.000001"))
            metrics[operation.id] = HoldingOperationMetrics(
                realized_cost_basis=None,
                realized_gain=None,
            )
            continue
        if operation_quantity > quantity:
            raise ValueError("Une vente historique depasse la position disponible")
        sale_cost_basis = operation_quantity * average_price
        realized_gain = operation_quantity * (operation_price - average_price)
        metrics[operation.id] = HoldingOperationMetrics(
            realized_cost_basis=money(sale_cost_basis),
            realized_gain=money(realized_gain),
        )
        quantity -= operation_quantity
        if quantity == 0:
            average_price = Decimal("0")
    return metrics


def _debt_read(
    debt: Debt,
    *,
    owners: list[Profile],
    active_profile_id: int,
    recurring_series_name_repayment: str | None = None,
    recurring_series_name_insurance: str | None = None,
    account_visible: bool = True,
    repayment_series_visible: bool = True,
    insurance_series_visible: bool = True,
    attachment_count: int = 0,
) -> _DebtRead:
    principal = Decimal(debt.principal)
    balance = Decimal(debt.balance)
    paid = money(principal - balance)
    progress = (paid / principal).quantize(Decimal("0.01")) if principal > 0 else Decimal("0.00")

    # Compute sum of the two associated budgets for display
    total_budget = Decimal("0.00")
    if debt.recurring_series_repayment_id is not None:
        total_budget += Decimal(debt.recurring_series_repayment.amount or 0)
    if debt.recurring_series_insurance_id is not None:
        total_budget += Decimal(debt.recurring_series_insurance.amount or 0)
    balance_shares = _equal_owner_shares(
        balance,
        [owner.id for owner in owners],
    )
    minimum_payment_shares = _equal_owner_shares(
        total_budget,
        [owner.id for owner in owners],
    )

    return _DebtRead(
        id=debt.id,
        name=debt.name,
        debt_type=debt.debt_type,
        principal=money(principal),
        balance=money(balance),
        interest_rate=debt.interest_rate,
        minimum_payment=total_budget,
        account_id=debt.account_id if account_visible else None,
        recurring_series_repayment_id=(
            debt.recurring_series_repayment_id if repayment_series_visible else None
        ),
        recurring_series_insurance_id=(
            debt.recurring_series_insurance_id if insurance_series_visible else None
        ),
        recurring_series_name_repayment=(
            recurring_series_name_repayment if repayment_series_visible else None
        ),
        recurring_series_name_insurance=(
            recurring_series_name_insurance if insurance_series_visible else None
        ),
        due_date=debt.due_date,
        color=debt.color,
        archived=debt.archived,
        paid=paid,
        progress=progress,
        attachment_count=attachment_count,
        owners=[_profile_reference(owner) for owner in owners],
        active_profile_balance=balance_shares.get(active_profile_id, Decimal("0.00")),
        total_balance=money(balance),
        active_profile_minimum_payment=minimum_payment_shares.get(
            active_profile_id, Decimal("0.00")
        ),
        total_minimum_payment=money(total_budget),
    )


async def _require_debt(
    session: AsyncSession,
    debt_id: int,
    profile_id: int,
) -> Debt:
    debt = await session.scalar(
        select(Debt)
        .join(DebtOwner)
        .where(Debt.id == debt_id, DebtOwner.member_id == profile_id)
    )
    if debt is None:
        raise HTTPException(status_code=404, detail="Dette introuvable")
    return debt


async def _require_recurring_series(
    session: AsyncSession,
    series_id: int,
) -> RecurringSeries:
    series = await session.get(RecurringSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Série récurrente introuvable")
    return series


async def _debt_response(
    session: AsyncSession,
    debt: Debt,
    active_profile_id: int,
) -> _DebtRead:
    repayment_series = (
        await session.get(RecurringSeries, debt.recurring_series_repayment_id)
        if debt.recurring_series_repayment_id is not None
        else None
    )
    insurance_series = (
        await session.get(RecurringSeries, debt.recurring_series_insurance_id)
        if debt.recurring_series_insurance_id is not None
        else None
    )
    visible_accounts = await visible_account_ids(session, active_profile_id)
    repayment_series_visible = (
        debt.recurring_series_repayment_id is None
        or repayment_series is not None
        and repayment_series.account_id in visible_accounts
    )
    insurance_series_visible = (
        debt.recurring_series_insurance_id is None
        or insurance_series is not None
        and insurance_series.account_id in visible_accounts
    )
    attachment_count = await session.scalar(
        select(func.count())
        .select_from(DebtAttachment)
        .where(DebtAttachment.debt_id == debt.id)
    )
    return _debt_read(
        debt,
        owners=await _debt_owner_profiles(session, debt.id),
        active_profile_id=active_profile_id,
        recurring_series_name_repayment=(
            repayment_series.label if repayment_series else None
        ),
        recurring_series_name_insurance=(
            insurance_series.label if insurance_series else None
        ),
        account_visible=debt.account_id is None or debt.account_id in visible_accounts,
        repayment_series_visible=repayment_series_visible,
        insurance_series_visible=insurance_series_visible,
        attachment_count=int(attachment_count or 0),
    )


@router.get("/debts", response_model=list[_DebtRead])
async def list_debts(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[_DebtRead]:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    rows = (
        await session.execute(
            select(Debt)
            .join(DebtOwner)
            .where(DebtOwner.member_id == active_profile.id)
            .order_by(Debt.name)
        )
    ).scalars().all()
    recurring_series = {
        series.id: series
        for series in (await session.execute(select(RecurringSeries))).scalars().all()
    }
    attachment_counts = {
        debt_id: count
        for debt_id, count in (
            await session.execute(
                select(DebtAttachment.debt_id, func.count(DebtAttachment.id))
                .group_by(DebtAttachment.debt_id)
            )
        ).all()
    }
    owners_by_debt = {
        debt_id: await _debt_owner_profiles(session, debt_id)
        for debt_id in (row.id for row in rows)
    }
    result: list[_DebtRead] = []
    for row in rows:
        rs_repayment = recurring_series.get(row.recurring_series_repayment_id)
        rs_insurance = recurring_series.get(row.recurring_series_insurance_id)
        result.append(
            _debt_read(
                row,
                owners=owners_by_debt[row.id],
                active_profile_id=active_profile.id,
                recurring_series_name_repayment=rs_repayment.label if rs_repayment else None,
                recurring_series_name_insurance=rs_insurance.label if rs_insurance else None,
                account_visible=(
                    row.account_id is None or row.account_id in visible_accounts
                ),
                repayment_series_visible=(
                    rs_repayment is None or rs_repayment.account_id in visible_accounts
                ),
                insurance_series_visible=(
                    rs_insurance is None or rs_insurance.account_id in visible_accounts
                ),
                attachment_count=int(attachment_counts.get(row.id, 0)),
            )
        )
    return result


@router.post("/debts", response_model=_DebtRead, status_code=201)
async def create_debt(
    payload: _DebtCreate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> _DebtRead:
    owner_ids = await _validate_owner_profile_ids(
        session,
        getattr(payload, "owner_profile_ids", None),
        default_profile_id=active_profile.id,
    )
    if active_profile.id not in owner_ids:
        raise HTTPException(
            status_code=422,
            detail="Le createur doit rester proprietaire de la dette",
        )
    if payload.account_id is not None:
        await require_account(
            session,
            payload.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
    series_repayment = None
    series_insurance = None
    if payload.recurring_series_repayment_id is not None:
        series_repayment = await _require_recurring_series(session, payload.recurring_series_repayment_id)
        await require_account(
            session,
            series_repayment.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
    if payload.recurring_series_insurance_id is not None:
        series_insurance = await _require_recurring_series(session, payload.recurring_series_insurance_id)
        await require_account(
            session,
            series_insurance.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
    if payload.balance > payload.principal:
        raise HTTPException(status_code=422, detail="Le solde ne peut pas exceder le principal")
    debt = Debt(**payload.model_dump(exclude={"owner_profile_ids"}))
    session.add(debt)
    await session.flush()
    await _replace_resource_owners(session, debt, owner_ids)
    if series_repayment is None and series_insurance is None:
        if payload.minimum_payment is not None and payload.minimum_payment > 0:
            try:
                series_repayment = build_debt_recurring_series_repayment(debt)
                series_insurance = build_debt_recurring_series_insurance(debt)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            session.add(series_repayment)
            session.add(series_insurance)
            await session.flush()
            debt.recurring_series_repayment_id = series_repayment.id
            debt.recurring_series_insurance_id = series_insurance.id
    elif series_repayment is not None and series_insurance is not None:
        if payload.minimum_payment is None:
            debt.minimum_payment = debt_payment(
                series_repayment.amount + series_insurance.amount
            )
        else:
            # Distribute the minimum_payment proportionally between the two series
            # based on their current amounts
            total_amount = abs(Decimal(series_repayment.amount or 0)) + abs(
                Decimal(series_insurance.amount or 0)
            )
            if total_amount > 0:
                repayment_share = abs(Decimal(series_repayment.amount or 0)) / total_amount
                insurance_share = abs(Decimal(series_insurance.amount or 0)) / total_amount
                series_repayment.amount = recurring_amount(
                    Decimal(payload.minimum_payment) * repayment_share
                )
                series_insurance.amount = recurring_amount(
                    Decimal(payload.minimum_payment) * insurance_share
                )
    elif series_repayment is not None:
        if payload.minimum_payment is None:
            debt.minimum_payment = debt_payment(series_repayment.amount)
        else:
            series_repayment.amount = recurring_amount(payload.minimum_payment)
    elif series_insurance is not None:
        if payload.minimum_payment is None:
            debt.minimum_payment = debt_payment(series_insurance.amount)
        else:
            series_insurance.amount = recurring_amount(payload.minimum_payment)
    await session.commit()
    await session.refresh(debt)
    return await _debt_response(session, debt, active_profile.id)


@router.patch("/debts/{debt_id}", response_model=_DebtRead)
async def update_debt(
    debt_id: int,
    payload: _DebtUpdate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> _DebtRead:
    debt = await _require_debt(session, debt_id, active_profile.id)
    data = payload.model_dump(exclude_unset=True)
    owner_profile_ids = data.pop("owner_profile_ids", None)
    if "account_id" in data and debt.account_id is not None:
        await require_account(
            session,
            debt.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
    if data.get("account_id") is not None:
        await require_account(
            session,
            data["account_id"],
            writable=True,
            profile_id=active_profile.id,
        )
    for series_field in (
        "recurring_series_repayment_id",
        "recurring_series_insurance_id",
    ):
        current_series_id = getattr(debt, series_field)
        if series_field in data and current_series_id is not None:
            current_series = await _require_recurring_series(session, current_series_id)
            await require_account(
                session,
                current_series.account_id,
                writable=True,
                profile_id=active_profile.id,
            )
    series_repayment = None
    series_insurance = None
    if data.get("recurring_series_repayment_id") is not None:
        series_repayment = await _require_recurring_series(session, data["recurring_series_repayment_id"])
        await require_account(
            session,
            series_repayment.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
    elif "recurring_series_repayment_id" not in data and debt.recurring_series_repayment_id is not None:
        series_repayment = await _require_recurring_series(session, debt.recurring_series_repayment_id)
    if data.get("recurring_series_insurance_id") is not None:
        series_insurance = await _require_recurring_series(session, data["recurring_series_insurance_id"])
        await require_account(
            session,
            series_insurance.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
    elif "recurring_series_insurance_id" not in data and debt.recurring_series_insurance_id is not None:
        series_insurance = await _require_recurring_series(session, debt.recurring_series_insurance_id)
    if {
        "minimum_payment",
        "recurring_series_repayment_id",
        "recurring_series_insurance_id",
    }.intersection(data):
        for series in (series_repayment, series_insurance):
            if series is not None:
                await require_account(
                    session,
                    series.account_id,
                    writable=True,
                    profile_id=active_profile.id,
                )
    for required_field in ("name", "debt_type", "principal", "balance", "color", "archived"):
        if required_field in data and data[required_field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Le champ {required_field} ne peut pas être nul",
            )
    for field, value in data.items():
        setattr(debt, field, value)
    if Decimal(debt.balance) > Decimal(debt.principal):
        raise HTTPException(status_code=422, detail="Le solde ne peut pas exceder le principal")
    if owner_profile_ids is not None:
        await _replace_resource_owners(
            session,
            debt,
            await _validate_owner_profile_ids(
                session,
                owner_profile_ids,
                default_profile_id=active_profile.id,
            ),
        )
    # Synchronize the two series with minimum_payment
    if series_repayment is not None or series_insurance is not None:
        if "minimum_payment" in data:
            if series_repayment is not None and series_insurance is not None:
                # Re-distribute minimum_payment proportionally between the two series
                total_amount = abs(Decimal(series_repayment.amount or 0)) + abs(
                    Decimal(series_insurance.amount or 0)
                )
                if total_amount > 0:
                    repayment_share = abs(Decimal(series_repayment.amount or 0)) / total_amount
                    insurance_share = abs(Decimal(series_insurance.amount or 0)) / total_amount
                    series_repayment.amount = recurring_amount(
                        Decimal(debt.minimum_payment) * repayment_share
                    )
                    series_insurance.amount = recurring_amount(
                        Decimal(debt.minimum_payment) * insurance_share
                    )
            elif series_repayment is not None:
                series_repayment.amount = recurring_amount(debt.minimum_payment)
            elif series_insurance is not None:
                series_insurance.amount = recurring_amount(debt.minimum_payment)
        elif "recurring_series_repayment_id" in data or "recurring_series_insurance_id" in data:
            if series_repayment is not None:
                debt.minimum_payment = debt_payment(series_repayment.amount)
            if series_insurance is not None:
                pass
    await session.commit()
    await session.refresh(debt)
    return await _debt_response(session, debt, active_profile.id)

@router.delete("/debts/{debt_id}", status_code=204)
async def delete_debt(
    debt_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    debt = await _require_debt(session, debt_id, active_profile.id)
    attachments = (
        await session.execute(
            select(DebtAttachment).where(DebtAttachment.debt_id == debt_id)
        )
    ).scalars().all()
    for attachment in attachments:
        remove_attachment(attachment.stored_path)
    await session.delete(debt)
    await session.commit()


def _debt_attachment_read(attachment: DebtAttachment) -> DebtAttachmentRead:
    return DebtAttachmentRead(
        id=attachment.id,
        debt_id=attachment.debt_id,
        original_name=attachment.original_name,
        storage_path=f"/{attachment.stored_path}",
        content_type=attachment.content_type,
        size=attachment.size,
    )


async def _require_debt_attachment(
    session: AsyncSession,
    debt_id: int,
    attachment_id: int,
    profile_id: int,
) -> DebtAttachment:
    attachment = await session.get(DebtAttachment, attachment_id)
    if attachment is None or attachment.debt_id != debt_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    await _require_debt(session, debt_id, profile_id)
    return attachment


@router.get(
    "/debts/{debt_id}/attachments",
    response_model=list[DebtAttachmentRead],
)
async def list_debt_attachments(
    debt_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[DebtAttachmentRead]:
    await _require_debt(session, debt_id, active_profile.id)
    rows = (
        await session.execute(
            select(DebtAttachment)
            .where(DebtAttachment.debt_id == debt_id)
            .order_by(DebtAttachment.created_at, DebtAttachment.id)
        )
    ).scalars().all()
    return [_debt_attachment_read(row) for row in rows]


@router.post(
    "/debts/{debt_id}/attachments",
    response_model=DebtAttachmentRead,
    status_code=201,
)
async def upload_debt_attachment(
    debt_id: int,
    file: UploadFile = File(...),
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> DebtAttachmentRead:
    await _require_debt(session, debt_id, active_profile.id)
    content_type = file.content_type
    original_name, stored_path, size = await store_attachment(file)
    attachment = DebtAttachment(
        debt_id=debt_id,
        original_name=original_name,
        stored_path=stored_path,
        content_type=content_type,
        size=size,
    )
    session.add(attachment)
    try:
        await session.commit()
    except SQLAlchemyError:
        remove_attachment(stored_path)
        raise
    await session.refresh(attachment)
    return _debt_attachment_read(attachment)


@router.get(
    "/debts/{debt_id}/attachments/{attachment_id}/download",
    response_model=None,
)
async def download_debt_attachment(
    debt_id: int,
    attachment_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_debt_attachment(
        session,
        debt_id,
        attachment_id,
        active_profile.id,
    )
    path = attachment_path(attachment.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier de piece jointe introuvable")
    return FileResponse(
        path,
        filename=attachment.original_name,
        media_type=attachment.content_type or "application/octet-stream",
        content_disposition_type="attachment",
    )


@router.delete(
    "/debts/{debt_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_debt_attachment(
    debt_id: int,
    attachment_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _require_debt(session, debt_id, active_profile.id)
    attachment = await _require_debt_attachment(
        session,
        debt_id,
        attachment_id,
        active_profile.id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


# --------------------------------------------------------------------------- #
# Real estate
# --------------------------------------------------------------------------- #
def _real_estate_owned_values(asset: RealEstateAsset) -> tuple[Decimal, Decimal]:
    share = Decimal(asset.ownership_share) / Decimal("100")
    current_value = (
        Decimal(asset.current_value)
        if asset.current_value is not None
        else Decimal(asset.purchase_price)
    )
    return (
        money(Decimal(asset.purchase_price) * share),
        money(current_value * share),
    )


def _real_estate_read(
    asset: RealEstateAsset,
    debts: list[tuple[Debt, str | None, str | None]],
    *,
    owners: list[Profile],
    active_profile_id: int,
    active_profile_debt_balance: Decimal,
    visible_recurring_series_ids: set[int],
    attachment_count: int = 0,
) -> _RealEstateRead:
    owned_purchase_price, owned_value = _real_estate_owned_values(asset)
    debt_balance = money(
        sum((Decimal(debt.balance) for debt, _, _ in debts), Decimal("0"))
    )
    active_purchase_price, active_owned_value = _real_estate_owner_values(
        asset,
        [owner.id for owner in owners],
    ).get(active_profile_id, (Decimal("0.00"), Decimal("0.00")))
    return _RealEstateRead(
        id=asset.id,
        name=asset.name,
        property_type=asset.property_type,
        address=asset.address,
        acquired_on=asset.acquired_on,
        purchase_price=money(Decimal(asset.purchase_price)),
        current_value=(
            money(Decimal(asset.current_value)) if asset.current_value is not None else None
        ),
        ownership_share=Decimal(asset.ownership_share),
        debt_ids=[debt.id for debt, _, _ in debts],
        debts=[
            RealEstateDebtRead(
                id=debt.id,
                name=debt.name,
                balance=money(Decimal(debt.balance)),
                recurring_series_repayment_id=(
                    debt.recurring_series_repayment_id
                    if debt.recurring_series_repayment_id in visible_recurring_series_ids
                    else None
                ),
                recurring_series_insurance_id=(
                    debt.recurring_series_insurance_id
                    if debt.recurring_series_insurance_id in visible_recurring_series_ids
                    else None
                ),
                recurring_series_name_repayment=(
                    repayment_label
                    if debt.recurring_series_repayment_id in visible_recurring_series_ids
                    else None
                ),
                recurring_series_name_insurance=(
                    insurance_label
                    if debt.recurring_series_insurance_id in visible_recurring_series_ids
                    else None
                ),
            )
            for debt, repayment_label, insurance_label in debts
        ],
        debt_balance=debt_balance,
        owned_purchase_price=owned_purchase_price,
        owned_value=owned_value,
        gain=money(owned_value - owned_purchase_price),
        net_equity=money(owned_value - debt_balance),
        attachment_count=attachment_count,
        icon_path=asset.icon_path,
        owners=[_profile_reference(owner) for owner in owners],
        active_profile_purchase_price=active_purchase_price,
        active_profile_owned_value=active_owned_value,
        active_profile_debt_balance=money(active_profile_debt_balance),
        active_profile_gain=money(active_owned_value - active_purchase_price),
        total_owned_value=owned_value,
        active_profile_net_equity=money(active_owned_value - active_profile_debt_balance),
        total_net_equity=money(owned_value - debt_balance),
    )


async def _require_real_estate(
    session: AsyncSession,
    asset_id: int,
    profile_id: int,
) -> RealEstateAsset:
    asset = await session.scalar(
        select(RealEstateAsset)
        .join(RealEstateAssetOwner)
        .where(
            RealEstateAsset.id == asset_id,
            RealEstateAssetOwner.member_id == profile_id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
    return asset


async def _load_real_estate_debts(
    session: AsyncSession,
    asset_id: int,
) -> list[tuple[Debt, str | None, str | None]]:
    debt_filters = [RealEstateDebtLink.asset_id == asset_id]
    # Get repayment series labels
    repayment_rows = (
        await session.execute(
            select(Debt.id, RecurringSeries.label)
            .join(RealEstateDebtLink, RealEstateDebtLink.debt_id == Debt.id)
            .outerjoin(
                RecurringSeries,
                RecurringSeries.id == Debt.recurring_series_repayment_id,
            )
            .where(*debt_filters)
            .order_by(Debt.name, Debt.id)
        )
    ).all()
    # Get insurance series labels
    insurance_rows = (
        await session.execute(
            select(Debt.id, RecurringSeries.label)
            .join(RealEstateDebtLink, RealEstateDebtLink.debt_id == Debt.id)
            .outerjoin(
                RecurringSeries,
                RecurringSeries.id == Debt.recurring_series_insurance_id,
            )
            .where(*debt_filters)
            .order_by(Debt.name, Debt.id)
        )
    ).all()
    repayment_labels = {row.id: row.label for row in repayment_rows}
    insurance_labels = {row.id: row.label for row in insurance_rows}
    debt_ids = set(row.id for row in repayment_rows) | set(row.id for row in insurance_rows)
    rows_by_debt = {}
    for debt_id in debt_ids:
        debt = await session.get(Debt, debt_id)
        if debt:
            rows_by_debt[debt_id] = debt
    result = []
    for debt_id in sorted(rows_by_debt):
        debt = rows_by_debt.get(debt_id)
        if debt:
            result.append((debt, repayment_labels.get(debt_id, ''), insurance_labels.get(debt_id, '')))
    return result


async def _real_estate_response(
    session: AsyncSession,
    asset: RealEstateAsset,
    active_profile_id: int,
    attachment_count: int = 0,
) -> _RealEstateRead:
    linked_debts = await _load_real_estate_debts(session, asset.id)
    visible_accounts = await visible_account_ids(session, active_profile_id)
    visible_recurring_series_ids = set(
        await session.scalars(
            select(RecurringSeries.id).where(
                RecurringSeries.account_id.in_(visible_accounts)
            )
        )
    )
    debts: list[tuple[Debt, str | None, str | None]] = []
    active_profile_debt_balance = Decimal("0")
    for debt, repayment_label, insurance_label in linked_debts:
        debt_owner_ids = [owner.id for owner in await _debt_owner_profiles(session, debt.id)]
        if active_profile_id not in debt_owner_ids:
            continue
        debts.append((debt, repayment_label, insurance_label))
        active_profile_debt_balance += _equal_owner_shares(
            Decimal(debt.balance),
            debt_owner_ids,
        ).get(active_profile_id, Decimal("0"))
    return _real_estate_read(
        asset,
        debts,
        owners=await _real_estate_owner_profiles(session, asset.id),
        active_profile_id=active_profile_id,
        active_profile_debt_balance=active_profile_debt_balance,
        visible_recurring_series_ids=visible_recurring_series_ids,
        attachment_count=attachment_count,
    )


async def _validate_real_estate_debts(
    session: AsyncSession,
    debt_ids: list[int],
    asset_id: int | None = None,
    profile_id: int | None = None,
) -> list[Debt]:
    if not debt_ids:
        return []
    debts = (
        await session.execute(
            select(Debt)
            .join(DebtOwner)
            .where(
                Debt.id.in_(debt_ids),
                *(
                    [DebtOwner.member_id == profile_id]
                    if profile_id is not None
                    else []
                ),
            )
        )
    ).scalars().all()
    debts_by_id = {debt.id: debt for debt in debts}
    if len(debts_by_id) != len(debt_ids):
        raise HTTPException(status_code=404, detail="Dette introuvable")
    statement = select(RealEstateDebtLink.debt_id).where(
        RealEstateDebtLink.debt_id.in_(debt_ids)
    )
    if asset_id is not None:
        statement = statement.where(RealEstateDebtLink.asset_id != asset_id)
    if await session.scalar(statement) is not None:
        raise HTTPException(
            status_code=409, detail="Cette dette est deja rattachee a un bien immobilier"
        )
    return [debts_by_id[debt_id] for debt_id in debt_ids]


async def _replace_real_estate_debts(
    session: AsyncSession,
    asset_id: int,
    debts: list[Debt],
) -> None:
    existing = (
        await session.execute(
            select(RealEstateDebtLink).where(RealEstateDebtLink.asset_id == asset_id)
        )
    ).scalars().all()
    for link in existing:
        await session.delete(link)
    await session.flush()
    session.add_all(
        RealEstateDebtLink(asset_id=asset_id, debt_id=debt.id)
        for debt in debts
    )


@router.get("/real-estate", response_model=list[_RealEstateRead])
async def list_real_estate(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[_RealEstateRead]:
    assets = (
        await session.execute(
            select(RealEstateAsset)
            .join(RealEstateAssetOwner)
            .where(RealEstateAssetOwner.member_id == active_profile.id)
            .order_by(RealEstateAsset.name)
        )
    ).scalars().all()
    attachment_counts = {
        asset_id: count
        for asset_id, count in (
            await session.execute(
                select(
                    RealEstateAttachment.asset_id,
                    func.count(RealEstateAttachment.id),
                ).group_by(RealEstateAttachment.asset_id)
            )
        ).all()
    }
    return [
        await _real_estate_response(
            session,
            asset,
            active_profile.id,
            attachment_count=int(attachment_counts.get(asset.id, 0)),
        )
        for asset in assets
    ]


@router.post("/real-estate", response_model=_RealEstateRead, status_code=201)
async def create_real_estate(
    payload: _RealEstateCreate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> _RealEstateRead:
    owner_ids = await _validate_owner_profile_ids(
        session,
        getattr(payload, "owner_profile_ids", None),
        default_profile_id=active_profile.id,
    )
    if active_profile.id not in owner_ids:
        raise HTTPException(
            status_code=422,
            detail="Le createur doit rester proprietaire du bien",
        )
    debts = await _validate_real_estate_debts(
        session,
        payload.debt_ids,
        profile_id=active_profile.id,
    )
    asset = RealEstateAsset(
        **payload.model_dump(exclude={"debt_ids", "owner_profile_ids"})
    )
    session.add(asset)
    await session.flush()
    await _replace_resource_owners(session, asset, owner_ids)
    await _replace_real_estate_debts(session, asset.id, debts)
    await session.commit()
    await session.refresh(asset)
    return await _real_estate_response(session, asset, active_profile.id)


@router.patch("/real-estate/{asset_id}", response_model=_RealEstateRead)
async def update_real_estate(
    asset_id: int,
    payload: _RealEstateUpdate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> _RealEstateRead:
    asset = await _require_real_estate(session, asset_id, active_profile.id)
    data = payload.model_dump(exclude_unset=True)
    debt_ids = data.pop("debt_ids", None)
    owner_profile_ids = data.pop("owner_profile_ids", None)
    debts = (
        await _validate_real_estate_debts(
            session,
            debt_ids,
            asset_id,
            active_profile.id,
        )
        if debt_ids is not None
        else None
    )
    if debts is not None:
        requested_debt_ids = {debt.id for debt in debts}
        for debt, _, _ in await _load_real_estate_debts(session, asset.id):
            debt_owner_ids = [
                owner.id for owner in await _debt_owner_profiles(session, debt.id)
            ]
            if active_profile.id not in debt_owner_ids and debt.id not in requested_debt_ids:
                debts.append(debt)
    for field, value in data.items():
        setattr(asset, field, value)
    if debts is not None:
        await _replace_real_estate_debts(session, asset.id, debts)
    if owner_profile_ids is not None:
        await _replace_resource_owners(
            session,
            asset,
            await _validate_owner_profile_ids(
                session,
                owner_profile_ids,
                default_profile_id=active_profile.id,
            ),
        )
    await session.commit()
    await session.refresh(asset)
    attachment_count = await session.scalar(
        select(func.count())
        .select_from(RealEstateAttachment)
        .where(RealEstateAttachment.asset_id == asset.id)
    )
    return await _real_estate_response(
        session,
        asset,
        active_profile.id,
        attachment_count=int(attachment_count or 0),
    )


@router.delete("/real-estate/{asset_id}", status_code=204)
async def delete_real_estate(
    asset_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    asset = await _require_real_estate(session, asset_id, active_profile.id)
    attachments = (
        await session.execute(
            select(RealEstateAttachment).where(RealEstateAttachment.asset_id == asset_id)
        )
    ).scalars().all()
    for attachment in attachments:
        remove_attachment(attachment.stored_path)
    await session.delete(asset)
    await session.commit()


@router.post("/real-estate/{asset_id}/icon", status_code=201)
async def upload_real_estate_icon(
    asset_id: int,
    file: UploadFile = File(...),
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    asset = await _require_real_estate(session, asset_id, active_profile.id)
    if asset.icon_path is not None:
        remove_attachment(asset.icon_path)
    original_name, stored_path, size = await store_attachment(file)
    asset.icon_path = stored_path
    await session.commit()
    await session.refresh(asset)
    return {"icon_path": stored_path}


@router.get("/real-estate/{asset_id}/icon/download", response_model=None)
async def download_real_estate_icon(
    asset_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    asset = await _require_real_estate(session, asset_id, active_profile.id)
    if asset.icon_path is None:
        raise HTTPException(status_code=404, detail="Icone introuvable")
    path = attachment_path(asset.icon_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier d'icone introuvable")
    return FileResponse(
        path,
        filename="icon",
        media_type="image/png",
        content_disposition_type="inline",
    )


@router.delete("/real-estate/{asset_id}/icon", status_code=204)
async def delete_real_estate_icon(
    asset_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    asset = await _require_real_estate(session, asset_id, active_profile.id)
    if asset.icon_path is not None:
        remove_attachment(asset.icon_path)
        asset.icon_path = None
        await session.commit()


def _real_estate_attachment_read(
    attachment: RealEstateAttachment,
) -> RealEstateAttachmentRead:
    return RealEstateAttachmentRead(
        id=attachment.id,
        asset_id=attachment.asset_id,
        original_name=attachment.original_name,
        storage_path=f"/{attachment.stored_path}",
        content_type=attachment.content_type,
        size=attachment.size,
    )


async def _require_real_estate_attachment(
    session: AsyncSession,
    asset_id: int,
    attachment_id: int,
    profile_id: int,
) -> RealEstateAttachment:
    attachment = await session.get(RealEstateAttachment, attachment_id)
    if attachment is None or attachment.asset_id != asset_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    await _require_real_estate(session, asset_id, profile_id)
    return attachment


@router.get(
    "/real-estate/{asset_id}/attachments",
    response_model=list[RealEstateAttachmentRead],
)
async def list_real_estate_attachments(
    asset_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[RealEstateAttachmentRead]:
    await _require_real_estate(session, asset_id, active_profile.id)
    rows = (
        await session.execute(
            select(RealEstateAttachment)
            .where(RealEstateAttachment.asset_id == asset_id)
            .order_by(RealEstateAttachment.created_at, RealEstateAttachment.id)
        )
    ).scalars().all()
    return [_real_estate_attachment_read(row) for row in rows]


@router.post(
    "/real-estate/{asset_id}/attachments",
    response_model=RealEstateAttachmentRead,
    status_code=201,
)
async def upload_real_estate_attachment(
    asset_id: int,
    file: UploadFile = File(...),
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> RealEstateAttachmentRead:
    await _require_real_estate(session, asset_id, active_profile.id)
    content_type = file.content_type
    original_name, stored_path, size = await store_attachment(file)
    attachment = RealEstateAttachment(
        asset_id=asset_id,
        original_name=original_name,
        stored_path=stored_path,
        content_type=content_type,
        size=size,
    )
    session.add(attachment)
    try:
        await session.commit()
    except SQLAlchemyError:
        remove_attachment(stored_path)
        raise
    await session.refresh(attachment)
    return _real_estate_attachment_read(attachment)


@router.get(
    "/real-estate/{asset_id}/attachments/{attachment_id}/download",
    response_model=None,
)
async def download_real_estate_attachment(
    asset_id: int,
    attachment_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_real_estate_attachment(
        session,
        asset_id,
        attachment_id,
        active_profile.id,
    )
    path = attachment_path(attachment.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier de piece jointe introuvable")
    return FileResponse(
        path,
        filename=attachment.original_name,
        media_type=attachment.content_type or "application/octet-stream",
        content_disposition_type="attachment",
    )


@router.delete(
    "/real-estate/{asset_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_real_estate_attachment(
    asset_id: int,
    attachment_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    attachment = await _require_real_estate_attachment(
        session,
        asset_id,
        attachment_id,
        active_profile.id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


# --------------------------------------------------------------------------- #
# Holdings
# --------------------------------------------------------------------------- #
async def _require_holding(
    session: AsyncSession,
    holding_id: int,
    profile_id: int,
) -> Holding:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, profile_id=profile_id)
    return holding


def _holding_read(
    holding: Holding,
    operation_count: int = 0,
    *,
    owner_ids: list[int],
    active_profile_id: int,
    realized_cost_basis: Decimal = Decimal("0"),
    realized_gain: Decimal = Decimal("0"),
) -> HoldingRead:
    quantity = Decimal(holding.quantity)
    cost_basis = money(quantity * Decimal(holding.average_price))
    market_value = money(quantity * Decimal(holding.current_price))
    unrealized_gain = money(market_value - cost_basis)
    realized_cost_basis = money(realized_cost_basis)
    realized_gain = money(realized_gain)
    total_cost_basis = money(cost_basis + realized_cost_basis)
    total_gain = money(unrealized_gain + realized_gain)
    quantity_shares = _equal_owner_quantity_shares(quantity, owner_ids)
    cost_basis_shares = _equal_owner_shares(cost_basis, owner_ids)
    realized_cost_basis_shares = _equal_owner_shares(realized_cost_basis, owner_ids)
    total_cost_basis_shares = _equal_owner_shares(total_cost_basis, owner_ids)
    market_value_shares = _equal_owner_shares(market_value, owner_ids)
    unrealized_gain_shares = _equal_owner_shares(unrealized_gain, owner_ids)
    realized_gain_shares = _equal_owner_shares(realized_gain, owner_ids)
    total_gain_shares = _equal_owner_shares(total_gain, owner_ids)
    return HoldingRead(
        id=holding.id,
        account_id=holding.account_id,
        name=holding.name,
        symbol=holding.symbol,
        asset_class=holding.asset_class,
        quantity=quantity,
        average_price=Decimal(holding.average_price),
        current_price=Decimal(holding.current_price),
        cost_basis=cost_basis,
        unrealized_cost_basis=cost_basis,
        realized_cost_basis=realized_cost_basis,
        total_cost_basis=total_cost_basis,
        market_value=market_value,
        unrealized_gain=unrealized_gain,
        realized_gain=realized_gain,
        total_gain=total_gain,
        gain=total_gain,
        operation_count=operation_count,
        active_profile_quantity=quantity_shares[active_profile_id],
        active_profile_cost_basis=cost_basis_shares[active_profile_id],
        active_profile_unrealized_cost_basis=cost_basis_shares[active_profile_id],
        active_profile_realized_cost_basis=realized_cost_basis_shares[
            active_profile_id
        ],
        active_profile_total_cost_basis=total_cost_basis_shares[active_profile_id],
        active_profile_market_value=market_value_shares[active_profile_id],
        active_profile_unrealized_gain=unrealized_gain_shares[active_profile_id],
        active_profile_realized_gain=realized_gain_shares[active_profile_id],
        active_profile_total_gain=total_gain_shares[active_profile_id],
    )


async def _holding_response(
    session: AsyncSession,
    holding: Holding,
    active_profile_id: int,
) -> HoldingRead:
    operations = (
        await session.execute(
            select(HoldingOperation).where(HoldingOperation.holding_id == holding.id)
        )
    ).scalars().all()
    realized = _holding_realized_metrics(operations)
    return _holding_read(
        holding,
        len(operations),
        owner_ids=await account_owner_ids(session, holding.account_id),
        active_profile_id=active_profile_id,
        realized_cost_basis=realized.realized_cost_basis,
        realized_gain=realized.realized_gain,
    )


def _holding_operation_read(
    operation: HoldingOperation,
    *,
    realized_cost_basis: Decimal | None = None,
    realized_gain: Decimal | None = None,
) -> HoldingOperationRead:
    quantity = Decimal(operation.quantity)
    total_value = money(quantity * Decimal(operation.unit_price))
    is_buy = operation.operation_type == "buy"
    return HoldingOperationRead(
        id=operation.id,
        holding_id=operation.holding_id,
        operation_type=operation.operation_type,
        quantity=quantity,
        unit_price=money(operation.unit_price),
        total_value=total_value,
        realized_cost_basis=realized_cost_basis,
        realized_gain=realized_gain,
        quantity_delta=quantity if is_buy else -quantity,
        cash_flow=-total_value if is_buy else total_value,
        occurred_on=operation.occurred_on,
        created_at=operation.created_at,
    )


def _holding_operation_reads(
    operations: list[HoldingOperation],
) -> list[HoldingOperationRead]:
    metrics = _holding_operation_metrics(operations)
    result: list[HoldingOperationRead] = []
    for operation in operations:
        operation_metrics = metrics.get(
            operation.id,
            HoldingOperationMetrics(realized_cost_basis=None, realized_gain=None),
        )
        result.append(
            _holding_operation_read(
                operation,
                realized_cost_basis=operation_metrics.realized_cost_basis,
                realized_gain=operation_metrics.realized_gain,
            )
        )
    return result


def _replayed_holding_position(
    operations: list[HoldingOperation],
    *,
    updated_operation_id: int | None = None,
    updated_operation_type: str | None = None,
    updated_quantity: Decimal | None = None,
    updated_unit_price: Decimal | None = None,
    updated_occurred_on: date | None = None,
) -> tuple[Decimal, Decimal]:
    quantity = Decimal("0")
    average_price = Decimal("0")
    ordered_operations = sorted(
        operations,
        key=lambda operation: (
            updated_occurred_on
            if operation.id == updated_operation_id and updated_occurred_on is not None
            else _holding_operation_sort_key(operation)[0],
            _holding_operation_sort_key(operation)[1],
            _holding_operation_sort_key(operation)[2],
        ),
    )
    for operation in ordered_operations:
        is_updated = operation.id == updated_operation_id
        operation_type = (
            updated_operation_type if is_updated and updated_operation_type else operation.operation_type
        )
        operation_quantity = (
            updated_quantity if is_updated and updated_quantity is not None else Decimal(operation.quantity)
        )
        unit_price = (
            updated_unit_price if is_updated and updated_unit_price is not None
            else Decimal(operation.unit_price)
        )
        if operation_type == "buy":
            new_quantity = quantity + operation_quantity
            total_cost = quantity * average_price + operation_quantity * unit_price
            quantity = new_quantity
            average_price = (total_cost / new_quantity).quantize(Decimal("0.000001"))
        else:
            if operation_quantity > quantity:
                raise HTTPException(
                    status_code=422,
                    detail="La quantite vendue depasse la position disponible a cette date",
                )
            quantity -= operation_quantity
            if quantity == 0:
                average_price = Decimal("0")
    return quantity, average_price


async def _holding_operations_chronological(
    session: AsyncSession,
    holding_id: int,
) -> list[HoldingOperation]:
    return list(
        (
            await session.execute(
                select(HoldingOperation)
                .where(HoldingOperation.holding_id == holding_id)
                .order_by(
                    HoldingOperation.occurred_on,
                    HoldingOperation.created_at,
                    HoldingOperation.id,
                )
            )
        ).scalars().all()
    )


async def _holding_for_account(
    session: AsyncSession,
    source: Holding,
    account_id: int,
) -> tuple[Holding, bool]:
    if source.account_id == account_id:
        return source, False
    existing = await session.scalar(
        select(Holding)
        .where(
            Holding.account_id == account_id,
            Holding.name == source.name,
            Holding.symbol == source.symbol,
            Holding.asset_class == source.asset_class,
        )
        .order_by(Holding.id)
    )
    if existing is not None:
        return existing, False
    return (
        Holding(
            account_id=account_id,
            name=source.name,
            symbol=source.symbol,
            asset_class=source.asset_class,
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            current_price=Decimal(source.current_price),
        ),
        True,
    )


@router.get("/holdings", response_model=list[HoldingRead])
async def list_holdings(
    account_id: int | None = None,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[HoldingRead]:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    statement = select(Holding).where(Holding.account_id.in_(visible_accounts)).order_by(Holding.name)
    if account_id is not None:
        await require_account(session, account_id, profile_id=active_profile.id)
        statement = statement.where(Holding.account_id == account_id)
    rows = (await session.execute(statement)).scalars().all()
    operations_by_holding: dict[int, list[HoldingOperation]] = defaultdict(list)
    holding_ids = [row.id for row in rows]
    if holding_ids:
        for operation in (
            await session.execute(
                select(HoldingOperation)
                .where(HoldingOperation.holding_id.in_(holding_ids))
                .order_by(
                    HoldingOperation.holding_id,
                    HoldingOperation.occurred_on,
                    HoldingOperation.created_at,
                    HoldingOperation.id,
                )
            )
        ).scalars().all():
            operations_by_holding[operation.holding_id].append(operation)
    result: list[HoldingRead] = []
    for row in rows:
        operations = operations_by_holding[row.id]
        realized = _holding_realized_metrics(operations)
        result.append(
            _holding_read(
                row,
                len(operations),
                owner_ids=await account_owner_ids(session, row.account_id),
                active_profile_id=active_profile.id,
                realized_cost_basis=realized.realized_cost_basis,
                realized_gain=realized.realized_gain,
            )
        )
    return result


@router.post("/holdings", response_model=HoldingRead, status_code=201)
async def create_holding(
    payload: HoldingCreate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> HoldingRead:
    await require_holding_account(
        session,
        payload.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    holding = Holding(**payload.model_dump())
    session.add(holding)
    await session.flush()
    if Decimal(holding.quantity) > 0:
        session.add(
            HoldingOperation(
                holding_id=holding.id,
                operation_type="buy",
                quantity=Decimal(holding.quantity),
                unit_price=money(holding.average_price),
                occurred_on=local_today(),
            )
        )
    await session.commit()
    await session.refresh(holding)
    return await _holding_response(session, holding, active_profile.id)


@router.patch("/holdings/{holding_id}", response_model=HoldingRead)
async def update_holding(
    holding_id: int,
    payload: HoldingUpdate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> HoldingRead:
    holding = await _require_holding(session, holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    data = payload.model_dump(exclude_unset=True)
    target_account_id = data.pop("account_id", holding.account_id)
    if target_account_id != holding.account_id:
        await require_holding_account(
            session,
            target_account_id,
            writable=True,
            profile_id=active_profile.id,
        )
        destination, is_new_destination = await _holding_for_account(
            session,
            holding,
            target_account_id,
        )
        if is_new_destination:
            holding.account_id = target_account_id
        else:
            source_operations = await _holding_operations_chronological(
                session,
                holding.id,
            )
            destination_operations = await _holding_operations_chronological(
                session,
                destination.id,
            )
            for operation in source_operations:
                operation.holding_id = destination.id
            quantity, average_price = _replayed_holding_position(
                sorted(
                    [*source_operations, *destination_operations],
                    key=lambda row: (row.created_at, row.id),
                )
            )
            contributions = (
                await session.execute(
                    select(Contribution).where(Contribution.holding_id == holding.id)
                )
            ).scalars().all()
            for contribution in contributions:
                contribution.holding_id = destination.id
            destination.quantity = quantity
            destination.average_price = average_price
            for field, value in data.items():
                setattr(destination, field, value)
            await session.delete(holding)
            await session.commit()
            await session.refresh(destination)
            return await _holding_response(session, destination, active_profile.id)
    for field, value in data.items():
        setattr(holding, field, value)
    await session.commit()
    await session.refresh(holding)
    return await _holding_response(session, holding, active_profile.id)


@router.delete("/holdings/{holding_id}", status_code=204)
async def delete_holding(
    holding_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    holding = await _require_holding(session, holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    await session.delete(holding)
    await session.commit()


@router.get(
    "/holdings/{holding_id}/operations",
    response_model=list[HoldingOperationRead],
)
async def list_holding_operations(
    holding_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[HoldingOperationRead]:
    await _require_holding(session, holding_id, active_profile.id)
    rows = (
        await session.execute(
            select(HoldingOperation)
            .where(HoldingOperation.holding_id == holding_id)
            .order_by(
                HoldingOperation.occurred_on.desc(),
                HoldingOperation.created_at.desc(),
                HoldingOperation.id.desc(),
            )
        )
    ).scalars().all()
    chronological = sorted(rows, key=_holding_operation_sort_key)
    reads_by_id = {
        operation.id: operation
        for operation in _holding_operation_reads(chronological)
    }
    return [reads_by_id[row.id] for row in rows]


@router.get(
    "/holding-operations",
    response_model=list[HoldingOperationRead],
)
async def list_all_holding_operations(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[HoldingOperationRead]:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    rows = (
        await session.execute(
            select(HoldingOperation)
            .join(Holding)
            .where(Holding.account_id.in_(visible_accounts))
            .order_by(
                HoldingOperation.occurred_on.desc(),
                HoldingOperation.created_at.desc(),
                HoldingOperation.id.desc(),
            )
        )
    ).scalars().all()
    operations_by_holding: dict[int, list[HoldingOperation]] = defaultdict(list)
    for row in sorted(
        rows,
        key=lambda operation: (
            operation.holding_id,
            *_holding_operation_sort_key(operation),
        ),
    ):
        operations_by_holding[row.holding_id].append(row)
    reads_by_id: dict[int, HoldingOperationRead] = {}
    for operations in operations_by_holding.values():
        for operation_read in _holding_operation_reads(operations):
            reads_by_id[operation_read.id] = operation_read
    return [reads_by_id[row.id] for row in rows]


@router.post(
    "/holding-operations",
    response_model=HoldingOperationResult,
    status_code=201,
)
async def create_holding_operation(
    payload: HoldingOperationCreate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> HoldingOperationResult:
    if payload.holding_id is not None:
        source_holding = await _require_holding(
            session,
            payload.holding_id,
            active_profile.id,
        )
        await require_account(
            session,
            source_holding.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
        target_account_id = (
            payload.target_account_id
            if payload.target_account_id is not None
            else source_holding.account_id
        )
        await require_holding_account(
            session,
            target_account_id,
            writable=True,
            profile_id=active_profile.id,
        )
        holding, is_new_holding = await _holding_for_account(
            session,
            source_holding,
            target_account_id,
        )
    else:
        new_holding = payload.new_holding
        if new_holding is None:
            raise HTTPException(status_code=422, detail="Nouvel actif manquant")
        await require_holding_account(
            session,
            new_holding.account_id,
            writable=True,
            profile_id=active_profile.id,
        )
        holding = Holding(
            **new_holding.model_dump(),
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            current_price=money(payload.unit_price),
        )
        is_new_holding = True

    current_quantity = Decimal(holding.quantity)
    operation_quantity = Decimal(payload.quantity)
    if payload.operation_type == "sell" and operation_quantity > current_quantity:
        raise HTTPException(
            status_code=422,
            detail="La quantite vendue depasse la position disponible",
        )

    if is_new_holding:
        session.add(holding)
        await session.flush()

    if payload.operation_type == "buy":
        new_quantity = current_quantity + operation_quantity
        total_cost = (
            current_quantity * Decimal(holding.average_price)
            + operation_quantity * Decimal(payload.unit_price)
        )
        holding.quantity = new_quantity
        holding.average_price = (total_cost / new_quantity).quantize(Decimal("0.000001"))
    else:
        holding.quantity = current_quantity - operation_quantity
        if Decimal(holding.quantity) == 0:
            holding.average_price = Decimal("0")

    operation = HoldingOperation(
        holding_id=holding.id,
        operation_type=payload.operation_type,
        quantity=operation_quantity,
        unit_price=money(payload.unit_price),
        occurred_on=payload.occurred_on,
    )
    operations = await _holding_operations_chronological(session, holding.id)
    operations.append(operation)
    holding.quantity, holding.average_price = _replayed_holding_position(operations)
    session.add(operation)
    await session.commit()
    await session.refresh(holding)
    await session.refresh(operation)
    persisted_operations = await _holding_operations_chronological(session, holding.id)
    operation_reads = {
        item.id: item for item in _holding_operation_reads(persisted_operations)
    }
    return HoldingOperationResult(
        holding=await _holding_response(session, holding, active_profile.id),
        operation=operation_reads[operation.id],
    )


@router.patch(
    "/holdings/{holding_id}/operations/{operation_id}",
    response_model=HoldingOperationResult,
)
async def update_holding_operation(
    holding_id: int,
    operation_id: int,
    payload: HoldingOperationUpdate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> HoldingOperationResult:
    holding = await _require_holding(session, holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    operation = await session.get(HoldingOperation, operation_id)
    if operation is None or operation.holding_id != holding_id:
        raise HTTPException(status_code=404, detail="Operation introuvable")

    target_account_id = (
        payload.target_account_id
        if payload.target_account_id is not None
        else holding.account_id
    )
    await require_holding_account(
        session,
        target_account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    destination, is_new_destination = await _holding_for_account(
        session,
        holding,
        target_account_id,
    )
    source_operations = await _holding_operations_chronological(session, holding_id)
    occurred_on = payload.occurred_on or operation.occurred_on
    if destination is holding:
        source_quantity, source_average_price = _replayed_holding_position(
            source_operations,
            updated_operation_id=operation_id,
            updated_operation_type=payload.operation_type,
            updated_quantity=Decimal(payload.quantity),
            updated_unit_price=money(payload.unit_price),
            updated_occurred_on=occurred_on,
        )
        destination_quantity = source_quantity
        destination_average_price = source_average_price
    else:
        source_quantity, source_average_price = _replayed_holding_position(
            [row for row in source_operations if row.id != operation_id]
        )
        destination_operations = await _holding_operations_chronological(
            session,
            destination.id,
        ) if not is_new_destination else []
        destination_operations.append(operation)
        destination_operations.sort(key=lambda row: (row.created_at, row.id))
        destination_quantity, destination_average_price = _replayed_holding_position(
            destination_operations,
            updated_operation_id=operation_id,
            updated_operation_type=payload.operation_type,
            updated_quantity=Decimal(payload.quantity),
            updated_unit_price=money(payload.unit_price),
            updated_occurred_on=occurred_on,
        )

    if is_new_destination:
        session.add(destination)
        await session.flush()
    operation.operation_type = payload.operation_type
    operation.quantity = Decimal(payload.quantity)
    operation.unit_price = money(payload.unit_price)
    operation.occurred_on = occurred_on
    operation.holding_id = destination.id
    holding.quantity = source_quantity
    holding.average_price = source_average_price
    destination.quantity = destination_quantity
    destination.average_price = destination_average_price
    await session.commit()
    await session.refresh(destination)
    await session.refresh(operation)
    destination_operations = await _holding_operations_chronological(session, destination.id)
    operation_reads = {
        item.id: item for item in _holding_operation_reads(destination_operations)
    }
    return HoldingOperationResult(
        holding=await _holding_response(session, destination, active_profile.id),
        operation=operation_reads[operation.id],
    )


@router.delete(
    "/holdings/{holding_id}/operations/{operation_id}",
    response_model=HoldingRead,
)
async def delete_holding_operation(
    holding_id: int,
    operation_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> HoldingRead:
    holding = await _require_holding(session, holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    operation = await session.get(HoldingOperation, operation_id)
    if operation is None or operation.holding_id != holding_id:
        raise HTTPException(status_code=404, detail="Operation introuvable")

    quantity, average_price = _replayed_holding_position(
        [
            row
            for row in await _holding_operations_chronological(session, holding_id)
            if row.id != operation_id
        ]
    )
    holding.quantity = quantity
    holding.average_price = average_price
    await session.delete(operation)
    await session.commit()
    await session.refresh(holding)
    return await _holding_response(session, holding, active_profile.id)


# --------------------------------------------------------------------------- #
# Contributions
# --------------------------------------------------------------------------- #
@router.get("/holdings/{holding_id}/contributions", response_model=list[ContributionRead])
async def list_contributions(
    holding_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[ContributionRead]:
    await _require_holding(session, holding_id, active_profile.id)
    rows = (
        await session.execute(
            select(Contribution)
            .where(Contribution.holding_id == holding_id)
            .order_by(Contribution.occurred_on)
        )
    ).scalars().all()
    return [ContributionRead.model_validate(row) for row in rows]


@router.post(
    "/holdings/{holding_id}/contributions", response_model=ContributionRead, status_code=201
)
async def create_contribution(
    holding_id: int,
    payload: ContributionCreate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> ContributionRead:
    holding = await _require_holding(session, holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    contribution = Contribution(holding_id=holding_id, **payload.model_dump())
    session.add(contribution)
    await session.commit()
    await session.refresh(contribution)
    return ContributionRead.model_validate(contribution)


@router.delete("/holdings/{holding_id}/contributions/{contribution_id}", status_code=204)
async def delete_contribution(
    holding_id: int,
    contribution_id: int,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    contribution = await session.get(Contribution, contribution_id)
    if contribution is None or contribution.holding_id != holding_id:
        raise HTTPException(status_code=404, detail="Versement introuvable")
    holding = await _require_holding(session, holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    await session.delete(contribution)
    await session.commit()


@router.get("/contributions", response_model=list[ContributionRead])
async def list_all_contributions(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[ContributionRead]:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    rows = (
        await session.execute(
            select(Contribution)
            .join(Holding)
            .where(Holding.account_id.in_(visible_accounts))
            .order_by(Contribution.occurred_on, Contribution.id)
        )
    ).scalars().all()
    return [ContributionRead.model_validate(row) for row in rows]


@router.post("/contributions", response_model=ContributionRead, status_code=201)
async def create_aggregate_contribution(
    payload: ContributionCreateAggregate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> ContributionRead:
    holding = await _require_holding(session, payload.holding_id, active_profile.id)
    await require_account(
        session,
        holding.account_id,
        writable=True,
        profile_id=active_profile.id,
    )
    contribution = Contribution(**payload.model_dump())
    session.add(contribution)
    await session.commit()
    await session.refresh(contribution)
    return ContributionRead.model_validate(contribution)


# --------------------------------------------------------------------------- #
# Portfolio analytics
# --------------------------------------------------------------------------- #
@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PortfolioSummary:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    holdings = (
        await session.execute(
            select(Holding).where(Holding.account_id.in_(visible_accounts))
        )
    ).scalars().all()
    properties = (
        await session.execute(
            select(RealEstateAsset)
            .join(RealEstateAssetOwner)
            .where(RealEstateAssetOwner.member_id == active_profile.id)
        )
    ).scalars().all()
    holding_operations = (
        await session.execute(
            select(HoldingOperation).order_by(
                HoldingOperation.holding_id,
                HoldingOperation.occurred_on,
                HoldingOperation.created_at,
                HoldingOperation.id,
            )
        )
    ).scalars().all()
    operations_by_holding: dict[int, list[HoldingOperation]] = defaultdict(list)
    for operation in holding_operations:
        operations_by_holding[operation.holding_id].append(operation)
    holdings_unrealized_cost_basis = Decimal("0")
    holdings_market_value = Decimal("0")
    holdings_realized_cost_basis = Decimal("0")
    holdings_realized_gain = Decimal("0")
    for holding in holdings:
        holdings_unrealized_cost_basis += await _account_owned_amount(
            session,
            holding.account_id,
            active_profile.id,
            Decimal(holding.quantity) * Decimal(holding.average_price),
        )
        holdings_market_value += await _account_owned_amount(
            session,
            holding.account_id,
            active_profile.id,
            Decimal(holding.quantity) * Decimal(holding.current_price),
        )
        realized = _holding_realized_metrics(operations_by_holding[holding.id])
        holdings_realized_cost_basis += await _account_owned_amount(
            session,
            holding.account_id,
            active_profile.id,
            realized.realized_cost_basis,
        )
        holdings_realized_gain += await _account_owned_amount(
            session,
            holding.account_id,
            active_profile.id,
            realized.realized_gain,
        )
    property_values = [
        _real_estate_owner_values(
            asset,
            [owner.id for owner in await _real_estate_owner_profiles(session, asset.id)],
        )[active_profile.id]
        for asset in properties
    ]
    properties_cost_basis = sum((purchase_price for purchase_price, _ in property_values), Decimal("0"))
    properties_market_value = sum((current_value for _, current_value in property_values), Decimal("0"))
    unrealized_cost_basis = holdings_unrealized_cost_basis + properties_cost_basis
    realized_cost_basis = holdings_realized_cost_basis
    total_cost_basis = unrealized_cost_basis + realized_cost_basis
    market_value = holdings_market_value + properties_market_value
    unrealized_gain = (holdings_market_value - holdings_unrealized_cost_basis) + (
        properties_market_value - properties_cost_basis
    )
    realized_gain = holdings_realized_gain
    total_gain = unrealized_gain + realized_gain
    contributions = (
        await session.execute(
            select(Contribution, Holding.account_id)
            .join(Holding)
            .where(Holding.account_id.in_(visible_accounts))
        )
    ).all()
    contributions_total = Decimal("0")
    for contribution, account_id in contributions:
        contributions_total += await _account_owned_amount(
            session,
            account_id,
            active_profile.id,
            Decimal(contribution.amount),
        )
    return PortfolioSummary(
        cost_basis=money(total_cost_basis),
        unrealized_cost_basis=money(unrealized_cost_basis),
        realized_cost_basis=money(realized_cost_basis),
        total_cost_basis=money(total_cost_basis),
        market_value=money(market_value),
        unrealized_gain=money(unrealized_gain),
        realized_gain=money(realized_gain),
        total_gain=money(total_gain),
        gain=money(total_gain),
        contributions_total=money(contributions_total),
        holdings=len(holdings),
        properties=len(properties),
    )


@router.get("/portfolio/allocation", response_model=list[AllocationSlice])
async def portfolio_allocation(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[AllocationSlice]:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    holdings = (
        await session.execute(
            select(Holding).where(Holding.account_id.in_(visible_accounts))
        )
    ).scalars().all()
    properties = (
        await session.execute(
            select(RealEstateAsset)
            .join(RealEstateAssetOwner)
            .where(RealEstateAssetOwner.member_id == active_profile.id)
        )
    ).scalars().all()
    by_class: dict[str, Decimal] = {}
    for holding in holdings:
        value = await _account_owned_amount(
            session,
            holding.account_id,
            active_profile.id,
            Decimal(holding.quantity) * Decimal(holding.current_price),
        )
        if value <= 0:
            continue
        by_class[holding.asset_class] = by_class.get(holding.asset_class, Decimal("0")) + value
    for asset in properties:
        _, value = _real_estate_owner_values(
            asset,
            [owner.id for owner in await _real_estate_owner_profiles(session, asset.id)],
        )[active_profile.id]
        if value <= 0:
            continue
        by_class["real_estate"] = by_class.get("real_estate", Decimal("0")) + value
    total = sum(by_class.values(), Decimal("0"))
    slices = []
    for asset_class, value in sorted(by_class.items(), key=lambda item: item[1], reverse=True):
        weight = (value / total).quantize(Decimal("0.0001")) if total > 0 else Decimal("0")
        slices.append(
            AllocationSlice(asset_class=asset_class, market_value=money(value), weight=weight)
        )
    return slices


@router.get("/portfolio/snapshots", response_model=list[PortfolioSnapshotRead])
async def list_portfolio_snapshots(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[PortfolioSnapshotRead]:
    del active_profile
    if not await _portfolio_snapshots_are_single_profile_only(session):
        return []
    rows = (
        await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.period))
    ).scalars().all()
    return [PortfolioSnapshotRead.model_validate(row) for row in rows]


@router.put("/portfolio/snapshots", response_model=PortfolioSnapshotRead)
async def upsert_portfolio_snapshot(
    payload: PortfolioSnapshotCreate,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PortfolioSnapshotRead:
    del active_profile
    if not await _portfolio_snapshots_are_single_profile_only(session):
        raise HTTPException(
            status_code=409,
            detail="Les snapshots de portefeuille ne sont pas disponibles par profil",
        )
    snapshot = await session.scalar(
        select(PortfolioSnapshot).where(PortfolioSnapshot.period == payload.period)
    )
    if snapshot is None:
        snapshot = PortfolioSnapshot(period=payload.period)
        session.add(snapshot)
    snapshot.market_value = money(payload.market_value)
    snapshot.cost_basis = money(payload.cost_basis)
    await session.commit()
    await session.refresh(snapshot)
    return PortfolioSnapshotRead.model_validate(snapshot)


@router.post("/portfolio/snapshots/generate", response_model=PortfolioSnapshotRead)
async def generate_portfolio_snapshot(
    period: str | None = None,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PortfolioSnapshotRead:
    """Idempotently record the current portfolio valuation for a month (YYYY-MM)."""
    del active_profile
    if not await _portfolio_snapshots_are_single_profile_only(session):
        raise HTTPException(
            status_code=409,
            detail="Les snapshots de portefeuille ne sont pas disponibles par profil",
        )
    reference = period or local_today().strftime("%Y-%m")
    if len(reference) != 7 or reference[4] != "-":
        raise HTTPException(status_code=422, detail="Periode invalide (attendu AAAA-MM)")
    holdings = (await session.execute(select(Holding))).scalars().all()
    properties = (await session.execute(select(RealEstateAsset))).scalars().all()
    cost_basis = sum(
        (Decimal(h.quantity) * Decimal(h.average_price) for h in holdings), Decimal("0")
    )
    holding_operations = (
        await session.execute(
            select(HoldingOperation).order_by(
                HoldingOperation.holding_id,
                HoldingOperation.occurred_on,
                HoldingOperation.created_at,
                HoldingOperation.id,
            )
        )
    ).scalars().all()
    operations_by_holding: dict[int, list[HoldingOperation]] = defaultdict(list)
    for operation in holding_operations:
        operations_by_holding[operation.holding_id].append(operation)
    cost_basis += sum(
        (
            _holding_realized_metrics(operations_by_holding[holding.id]).realized_cost_basis
            for holding in holdings
        ),
        Decimal("0"),
    )
    market_value = sum(
        (Decimal(h.quantity) * Decimal(h.current_price) for h in holdings), Decimal("0")
    )
    for asset in properties:
        property_cost, property_value = _real_estate_owned_values(asset)
        cost_basis += property_cost
        market_value += property_value
    snapshot = await session.scalar(
        select(PortfolioSnapshot).where(PortfolioSnapshot.period == reference)
    )
    if snapshot is None:
        snapshot = PortfolioSnapshot(period=reference)
        session.add(snapshot)
    snapshot.market_value = money(market_value)
    snapshot.cost_basis = money(cost_basis)
    await session.commit()
    await session.refresh(snapshot)
    return PortfolioSnapshotRead.model_validate(snapshot)


async def _holding_performance(
    session: AsyncSession,
    profile_id: int,
) -> list[AssetPerformancePoint]:
    visible_accounts = await visible_account_ids(session, profile_id)
    holdings = (
        await session.execute(
            select(Holding).where(Holding.account_id.in_(visible_accounts))
        )
    ).scalars().all()
    holding_accounts = {holding.id: holding.account_id for holding in holdings}
    operations = (
        await session.execute(
            select(HoldingOperation)
            .join(Holding)
            .where(Holding.account_id.in_(visible_accounts))
            .order_by(
                HoldingOperation.occurred_on,
                HoldingOperation.created_at,
                HoldingOperation.id,
            )
        )
    ).scalars().all()
    if not holdings and not operations:
        return []

    operations_by_period: dict[str, list[HoldingOperation]] = {}
    for operation in operations:
        period = operation.occurred_on.strftime("%Y-%m")
        operations_by_period.setdefault(period, []).append(operation)

    current_period = local_today().strftime("%Y-%m")
    periods = sorted(set(operations_by_period) | {current_period})
    positions: dict[int, HoldingPerformanceState] = {}
    points: list[AssetPerformancePoint] = []
    for period in periods:
        for operation in operations_by_period.get(period, []):
            state = positions.get(operation.holding_id, HoldingPerformanceState())
            operation_quantity = Decimal(operation.quantity)
            operation_price = Decimal(operation.unit_price)
            if operation.operation_type == "buy":
                next_quantity = state.quantity + operation_quantity
                state.average_price = (
                    (state.quantity * state.average_price + operation_quantity * operation_price)
                    / next_quantity
                )
                state.quantity = next_quantity
            else:
                next_quantity = state.quantity - operation_quantity
                if next_quantity < 0:
                    raise ValueError("Une vente historique depasse la position disponible")
                sale_cost_basis = operation_quantity * state.average_price
                state.realized_cost_basis += sale_cost_basis
                state.realized_gain += operation_quantity * (
                    operation_price - state.average_price
                )
                if next_quantity == 0:
                    state.average_price = Decimal("0")
                state.quantity = next_quantity
            state.last_price = operation_price
            positions[operation.holding_id] = state

        market_value = Decimal("0")
        unrealized_cost_basis = Decimal("0")
        realized_cost_basis = Decimal("0")
        realized_gain = Decimal("0")
        for holding_id, state in positions.items():
            account_id = holding_accounts[holding_id]
            market_value += await _account_owned_amount(
                session,
                account_id,
                profile_id,
                state.quantity * state.last_price,
            )
            unrealized_cost_basis += await _account_owned_amount(
                session,
                account_id,
                profile_id,
                state.quantity * state.average_price,
            )
            realized_cost_basis += await _account_owned_amount(
                session,
                account_id,
                profile_id,
                state.realized_cost_basis,
            )
            realized_gain += await _account_owned_amount(
                session,
                account_id,
                profile_id,
                state.realized_gain,
            )
        if period == current_period:
            market_value = Decimal("0")
            unrealized_cost_basis = Decimal("0")
            for holding in holdings:
                market_value += await _account_owned_amount(
                    session,
                    holding.account_id,
                    profile_id,
                    Decimal(holding.quantity) * Decimal(holding.current_price),
                )
                unrealized_cost_basis += await _account_owned_amount(
                    session,
                    holding.account_id,
                    profile_id,
                    Decimal(holding.quantity) * Decimal(holding.average_price),
                )
        unrealized_gain = market_value - unrealized_cost_basis
        total_cost_basis = unrealized_cost_basis + realized_cost_basis
        total_gain = unrealized_gain + realized_gain
        points.append(
            AssetPerformancePoint(
                period=period,
                market_value=money(market_value),
                cost_basis=money(total_cost_basis),
                unrealized_cost_basis=money(unrealized_cost_basis),
                realized_cost_basis=money(realized_cost_basis),
                total_cost_basis=money(total_cost_basis),
                unrealized_gain=money(unrealized_gain),
                realized_gain=money(realized_gain),
                total_gain=money(total_gain),
                gain=money(total_gain),
            )
        )
    return points


@router.get("/holdings/performance", response_model=list[AssetPerformancePoint])
async def holding_performance(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[AssetPerformancePoint]:
    return await _holding_performance(session, active_profile.id)


@router.get("/portfolio/performance", response_model=list[PerformancePoint])
async def portfolio_performance(
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[PerformancePoint]:
    visible_accounts = await visible_account_ids(session, active_profile.id)
    contributions = (
        await session.execute(
            select(Contribution, Holding.account_id)
            .join(Holding)
            .where(Holding.account_id.in_(visible_accounts))
            .order_by(Contribution.occurred_on)
        )
    ).all()
    contrib_by_period: dict[str, Decimal] = {}
    for contribution, account_id in contributions:
        period = contribution.occurred_on.strftime("%Y-%m")
        contrib_by_period[period] = contrib_by_period.get(period, Decimal("0")) + (
            await _account_owned_amount(
                session,
                account_id,
                active_profile.id,
                Decimal(contribution.amount),
            )
        )

    active_profiles = await session.scalar(
        select(func.count()).select_from(Profile).where(Profile.active.is_(True))
    )
    snapshots = (
        (
            await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.period))
        ).scalars().all()
        if active_profiles == 1
        else []
    )
    snapshot_by_period = {s.period: s for s in snapshots}
    if not snapshot_by_period:
        asset_points = await _holding_performance(session, active_profile.id)
        asset_by_period = {point.period: point for point in asset_points}
        periods = sorted(set(contrib_by_period) | set(asset_by_period))
        points: list[PerformancePoint] = []
        cumulative = Decimal("0")
        latest_market_value = Decimal("0")
        latest_cost_basis = Decimal("0")
        latest_unrealized_cost_basis = Decimal("0")
        latest_realized_cost_basis = Decimal("0")
        latest_unrealized_gain = Decimal("0")
        latest_realized_gain = Decimal("0")
        latest_total_gain = Decimal("0")
        for period in periods:
            contributed = contrib_by_period.get(period, Decimal("0"))
            cumulative += contributed
            asset_point = asset_by_period.get(period)
            if asset_point is not None:
                latest_market_value = asset_point.market_value
                latest_cost_basis = asset_point.cost_basis
                latest_unrealized_cost_basis = asset_point.unrealized_cost_basis
                latest_realized_cost_basis = asset_point.realized_cost_basis
                latest_unrealized_gain = asset_point.unrealized_gain
                latest_realized_gain = asset_point.realized_gain
                latest_total_gain = asset_point.total_gain
            points.append(
                PerformancePoint(
                    period=period,
                    market_value=money(latest_market_value),
                    cost_basis=money(latest_cost_basis),
                    unrealized_cost_basis=money(latest_unrealized_cost_basis),
                    realized_cost_basis=money(latest_realized_cost_basis),
                    total_cost_basis=money(latest_cost_basis),
                    unrealized_gain=money(latest_unrealized_gain),
                    realized_gain=money(latest_realized_gain),
                    total_gain=money(latest_total_gain),
                    gain=money(latest_total_gain),
                    contributions=money(contributed),
                    cumulative_contributions=money(cumulative),
                )
            )
        return points

    periods = sorted(set(contrib_by_period) | set(snapshot_by_period))
    points: list[PerformancePoint] = []
    cumulative = Decimal("0")
    latest_market_value = Decimal("0")
    latest_cost_basis = Decimal("0")
    latest_unrealized_cost_basis = Decimal("0")
    latest_realized_cost_basis = Decimal("0")
    latest_unrealized_gain = Decimal("0")
    latest_realized_gain = Decimal("0")
    for period in periods:
        contributed = contrib_by_period.get(period, Decimal("0"))
        cumulative += contributed
        snapshot = snapshot_by_period.get(period)
        if snapshot is not None:
            latest_market_value = Decimal(snapshot.market_value)
            latest_cost_basis = Decimal(snapshot.cost_basis)
        latest_unrealized_cost_basis = latest_cost_basis
        latest_realized_cost_basis = Decimal("0")
        latest_unrealized_gain = latest_market_value - latest_cost_basis
        latest_realized_gain = Decimal("0")
        latest_total_gain = latest_unrealized_gain
        points.append(
            PerformancePoint(
                period=period,
                market_value=money(latest_market_value),
                cost_basis=money(latest_cost_basis),
                unrealized_cost_basis=money(latest_unrealized_cost_basis),
                realized_cost_basis=money(latest_realized_cost_basis),
                total_cost_basis=money(latest_cost_basis),
                unrealized_gain=money(latest_unrealized_gain),
                realized_gain=money(latest_realized_gain),
                total_gain=money(latest_total_gain),
                gain=money(latest_total_gain),
                contributions=money(contributed),
                cumulative_contributions=money(cumulative),
            )
        )
    return points


# --------------------------------------------------------------------------- #
# Net worth
# --------------------------------------------------------------------------- #
async def _investment_account_ids(session: AsyncSession) -> set[int]:
    rows = (await session.execute(select(Holding.account_id).distinct())).scalars().all()
    return set(rows)


async def _account_owned_amount(
    session: AsyncSession,
    account_id: int,
    profile_id: int,
    amount: Decimal,
) -> Decimal:
    return allocate_equal_shares(
        amount,
        await account_owner_ids(session, account_id),
    ).get(profile_id, Decimal("0.00"))


async def _current_net_worth_components(
    session: AsyncSession,
    through: date,
    profile_id: int,
) -> tuple[Decimal, Decimal, Decimal, Decimal, set[int]]:
    visible_accounts = await visible_account_ids(session, profile_id)
    investment_accounts = (await _investment_account_ids(session)) & visible_accounts
    balances = await account_balances(session, through=through)
    cash = Decimal("0")
    for account_id, balance in balances.items():
        if account_id in visible_accounts and account_id not in investment_accounts:
            cash += await _account_owned_amount(session, account_id, profile_id, balance)

    holdings = (
        await session.execute(
            select(Holding).where(Holding.account_id.in_(visible_accounts))
        )
    ).scalars().all()
    investments = Decimal("0")
    for holding in holdings:
        investments += await _account_owned_amount(
            session,
            holding.account_id,
            profile_id,
            Decimal(holding.quantity) * Decimal(holding.current_price),
        )
    properties = (
        await session.execute(
            select(RealEstateAsset)
            .join(RealEstateAssetOwner)
            .where(RealEstateAssetOwner.member_id == profile_id)
        )
    ).scalars().all()
    real_estate = Decimal("0")
    for asset in properties:
        real_estate += _real_estate_owner_values(
            asset,
            [owner.id for owner in await _real_estate_owner_profiles(session, asset.id)],
        )[profile_id][1]
    debts = (
        await session.execute(
            select(Debt)
            .join(DebtOwner)
            .where(DebtOwner.member_id == profile_id)
        )
    ).scalars().all()
    debts_total = Decimal("0")
    for debt in debts:
        debts_total += _equal_owner_shares(
            Decimal(debt.balance),
            [owner.id for owner in await _debt_owner_profiles(session, debt.id)],
        )[profile_id]
    return cash, investments, real_estate, debts_total, investment_accounts


@router.get("/networth/overview", response_model=NetWorthOverview)
async def net_worth_overview(
    as_of: date | None = None,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> NetWorthOverview:
    through = as_of or local_today()
    cash, investments, real_estate, debts_total, _ = (
        await _current_net_worth_components(session, through, active_profile.id)
    )

    return NetWorthOverview(
        cash=money(cash),
        investments=money(investments),
        real_estate=money(real_estate),
        debts=money(debts_total),
        net_worth=money(cash + investments + real_estate - debts_total),
    )


@router.get("/networth/history", response_model=list[NetWorthPoint])
async def net_worth_history(
    as_of: date | None = None,
    active_profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[NetWorthPoint]:
    """Historical net worth from account and portfolio valuation snapshots.

    Missing account snapshots carry their last known balance forward. Before a
    portfolio valuation exists, contributions and owned property values provide
    a conservative fallback. The current point always uses live values so it
    reconciles with ``/networth/overview``. Current debt is subtracted from every
    period because debt history is not persisted yet.
    """
    today = as_of or local_today()
    current_period = today.strftime("%Y-%m")
    cash, investments, real_estate, debts_total, investment_accounts = (
        await _current_net_worth_components(session, today, active_profile.id)
    )
    visible_accounts = await visible_account_ids(session, active_profile.id)
    snapshots = (
        await session.execute(
            select(BalanceSnapshot)
            .where(
                BalanceSnapshot.period <= current_period,
                BalanceSnapshot.account_id.in_(visible_accounts),
            )
            .order_by(BalanceSnapshot.period, BalanceSnapshot.account_id)
        )
    ).scalars().all()

    cash_snapshots_by_period: dict[str, list[BalanceSnapshot]] = {}
    for snapshot in snapshots:
        if snapshot.account_id in investment_accounts:
            continue
        cash_snapshots_by_period.setdefault(snapshot.period, []).append(snapshot)

    contributions = (
        await session.execute(
            select(Contribution, Holding.account_id)
            .join(Holding)
            .where(
                Contribution.occurred_on <= today,
                Holding.account_id.in_(visible_accounts),
            )
            .order_by(Contribution.occurred_on)
        )
    ).all()
    contrib_by_period: dict[str, Decimal] = {}
    for contribution, account_id in contributions:
        period = contribution.occurred_on.strftime("%Y-%m")
        contrib_by_period[period] = contrib_by_period.get(period, Decimal("0")) + (
            await _account_owned_amount(
                session,
                account_id,
                active_profile.id,
                Decimal(contribution.amount),
            )
        )
    portfolio_snapshots = (
        await session.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.period <= current_period)
            .order_by(PortfolioSnapshot.period)
        )
    ).scalars().all()
    portfolio_by_period = (
        {
            snapshot.period: Decimal(snapshot.market_value)
            for snapshot in portfolio_snapshots
        }
        if await _portfolio_snapshots_are_single_profile_only(session)
        else {}
    )

    properties = (
        await session.execute(
            select(RealEstateAsset)
            .join(RealEstateAssetOwner)
            .where(RealEstateAssetOwner.member_id == active_profile.id)
        )
    ).scalars().all()
    property_changes: dict[str, Decimal] = {}
    for asset in properties:
        purchase_price, current_value = _real_estate_owner_values(
            asset,
            [owner.id for owner in await _real_estate_owner_profiles(session, asset.id)],
        )[active_profile.id]
        acquired_on = asset.acquired_on or asset.created_at.date()
        acquisition_period = acquired_on.strftime("%Y-%m")
        property_changes[acquisition_period] = (
            property_changes.get(acquisition_period, Decimal("0")) + purchase_price
        )
        property_changes[current_period] = (
            property_changes.get(current_period, Decimal("0"))
            + current_value
            - purchase_price
        )

    periods = sorted(
        set(cash_snapshots_by_period)
        | set(contrib_by_period)
        | set(portfolio_by_period)
        | set(property_changes)
        | {current_period}
    )
    points: list[NetWorthPoint] = []
    cumulative_contrib = Decimal("0")
    cumulative_real_estate = Decimal("0")
    latest_cash_by_account: dict[int, Decimal] = {}
    latest_portfolio_value: Decimal | None = None
    for period in periods:
        for snapshot in cash_snapshots_by_period.get(period, []):
            latest_cash_by_account[snapshot.account_id] = await _account_owned_amount(
                session,
                snapshot.account_id,
                active_profile.id,
                Decimal(snapshot.balance),
            )
        cumulative_contrib += contrib_by_period.get(period, Decimal("0"))
        cumulative_real_estate += property_changes.get(period, Decimal("0"))
        if period in portfolio_by_period:
            latest_portfolio_value = portfolio_by_period[period]

        cash_value = sum(latest_cash_by_account.values(), Decimal("0"))
        invested_assets = (
            latest_portfolio_value
            if latest_portfolio_value is not None
            else cumulative_contrib + cumulative_real_estate
        )
        if period == current_period:
            cash_value = cash
            invested_assets = investments + real_estate
        points.append(
            NetWorthPoint(
                period=period,
                net_worth=money(cash_value + invested_assets - debts_total),
            )
        )
    return points
