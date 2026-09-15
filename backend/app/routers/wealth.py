"""Wealth: debts, investment holdings, contributions and net-worth analytics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account, require_holding_account
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
    Account,
    BalanceSnapshot,
    Contribution,
    Debt,
    DebtAttachment,
    Holding,
    HoldingOperation,
    PortfolioSnapshot,
    RealEstateAsset,
    RealEstateAttachment,
    RealEstateDebtLink,
    RecurringSeries,
)
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
    recurring_series_name_repayment: str | None = None,
    recurring_series_name_insurance: str | None = None,
    attachment_count: int = 0,
) -> DebtRead:
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

    return DebtRead(
        id=debt.id,
        name=debt.name,
        debt_type=debt.debt_type,
        principal=money(principal),
        balance=money(balance),
        interest_rate=debt.interest_rate,
        minimum_payment=total_budget,
        account_id=debt.account_id,
        recurring_series_repayment_id=debt.recurring_series_repayment_id,
        recurring_series_insurance_id=debt.recurring_series_insurance_id,
        recurring_series_name_repayment=recurring_series_name_repayment,
        recurring_series_name_insurance=recurring_series_name_insurance,
        due_date=debt.due_date,
        color=debt.color,
        archived=debt.archived,
        paid=paid,
        progress=progress,
        attachment_count=attachment_count,
    )


async def _require_debt(session: AsyncSession, debt_id: int) -> Debt:
    debt = await session.get(Debt, debt_id)
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


async def _debt_response(session: AsyncSession, debt: Debt) -> DebtRead:
    recurring_series_name_repayment = None
    recurring_series_name_insurance = None
    if debt.recurring_series_repayment_id is not None:
        series = await session.get(RecurringSeries, debt.recurring_series_repayment_id)
        recurring_series_name_repayment = series.label if series else None
    if debt.recurring_series_insurance_id is not None:
        series = await session.get(RecurringSeries, debt.recurring_series_insurance_id)
        recurring_series_name_insurance = series.label if series else None
    attachment_count = await session.scalar(
        select(func.count())
        .select_from(DebtAttachment)
        .where(DebtAttachment.debt_id == debt.id)
    )
    return _debt_read(
        debt,
        recurring_series_name_repayment=recurring_series_name_repayment,
        recurring_series_name_insurance=recurring_series_name_insurance,
        attachment_count=int(attachment_count or 0),
    )


@router.get("/debts", response_model=list[DebtRead])
async def list_debts(session: AsyncSession = Depends(get_session)) -> list[DebtRead]:
    rows = (await session.execute(select(Debt).order_by(Debt.name))).scalars().all()
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
    result: list[DebtRead] = []
    for row in rows:
        rs_repayment = recurring_series.get(row.recurring_series_repayment_id)
        rs_insurance = recurring_series.get(row.recurring_series_insurance_id)
        result.append(
            _debt_read(
                row,
                recurring_series_name_repayment=rs_repayment.label if rs_repayment else None,
                recurring_series_name_insurance=rs_insurance.label if rs_insurance else None,
                attachment_count=int(attachment_counts.get(row.id, 0)),
            )
        )
    return result


@router.post("/debts", response_model=DebtRead, status_code=201)
async def create_debt(payload: DebtCreate, session: AsyncSession = Depends(get_session)) -> DebtRead:
    if payload.account_id is not None:
        await require_account(session, payload.account_id, writable=True)
    series_repayment = None
    series_insurance = None
    if payload.recurring_series_repayment_id is not None:
        series_repayment = await _require_recurring_series(session, payload.recurring_series_repayment_id)
        await require_account(session, series_repayment.account_id, writable=True)
    if payload.recurring_series_insurance_id is not None:
        series_insurance = await _require_recurring_series(session, payload.recurring_series_insurance_id)
        await require_account(session, series_insurance.account_id, writable=True)
    if payload.balance > payload.principal:
        raise HTTPException(status_code=422, detail="Le solde ne peut pas exceder le principal")
    debt = Debt(**payload.model_dump())
    session.add(debt)
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
    return await _debt_response(session, debt)


@router.patch("/debts/{debt_id}", response_model=DebtRead)
async def update_debt(
    debt_id: int, payload: DebtUpdate, session: AsyncSession = Depends(get_session)
) -> DebtRead:
    debt = await _require_debt(session, debt_id)
    if debt.account_id is not None:
        await require_account(session, debt.account_id, writable=True)
    data = payload.model_dump(exclude_unset=True)
    if data.get("account_id") is not None:
        await require_account(session, data["account_id"], writable=True)
    series_repayment = None
    series_insurance = None
    if data.get("recurring_series_repayment_id") is not None:
        series_repayment = await _require_recurring_series(session, data["recurring_series_repayment_id"])
        await require_account(session, series_repayment.account_id, writable=True)
    elif "recurring_series_repayment_id" not in data and debt.recurring_series_repayment_id is not None:
        series_repayment = await _require_recurring_series(session, debt.recurring_series_repayment_id)
    if data.get("recurring_series_insurance_id") is not None:
        series_insurance = await _require_recurring_series(session, data["recurring_series_insurance_id"])
        await require_account(session, series_insurance.account_id, writable=True)
    elif "recurring_series_insurance_id" not in data and debt.recurring_series_insurance_id is not None:
        series_insurance = await _require_recurring_series(session, debt.recurring_series_insurance_id)
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
    return await _debt_response(session, debt)

@router.delete("/debts/{debt_id}", status_code=204)
async def delete_debt(debt_id: int, session: AsyncSession = Depends(get_session)) -> None:
    debt = await _require_debt(session, debt_id)
    if debt.account_id is not None:
        await require_account(session, debt.account_id, writable=True)
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
) -> DebtAttachment:
    attachment = await session.get(DebtAttachment, attachment_id)
    if attachment is None or attachment.debt_id != debt_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    return attachment


@router.get(
    "/debts/{debt_id}/attachments",
    response_model=list[DebtAttachmentRead],
)
async def list_debt_attachments(
    debt_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[DebtAttachmentRead]:
    await _require_debt(session, debt_id)
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
    session: AsyncSession = Depends(get_session),
) -> DebtAttachmentRead:
    debt = await _require_debt(session, debt_id)
    if debt.account_id is not None:
        await require_account(session, debt.account_id, writable=True)
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
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_debt_attachment(session, debt_id, attachment_id)
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
    session: AsyncSession = Depends(get_session),
) -> None:
    debt = await _require_debt(session, debt_id)
    if debt.account_id is not None:
        await require_account(session, debt.account_id, writable=True)
    attachment = await _require_debt_attachment(session, debt_id, attachment_id)
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
    attachment_count: int = 0,
) -> RealEstateRead:
    owned_purchase_price, owned_value = _real_estate_owned_values(asset)
    debt_balance = money(
        sum((Decimal(debt.balance) for debt, _, _ in debts), Decimal("0"))
    )
    return RealEstateRead(
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
                recurring_series_repayment_id=debt.recurring_series_repayment_id,
                recurring_series_insurance_id=debt.recurring_series_insurance_id,
                recurring_series_name_repayment=repayment_label,
                recurring_series_name_insurance=insurance_label,
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
    )


async def _load_real_estate_debts(
    session: AsyncSession,
    asset_id: int,
) -> list[tuple[Debt, str | None, str | None]]:
    # Get repayment series labels
    repayment_rows = (
        await session.execute(
            select(Debt.id, RecurringSeries.label)
            .join(RealEstateDebtLink, RealEstateDebtLink.debt_id == Debt.id)
            .outerjoin(
                RecurringSeries,
                RecurringSeries.id == Debt.recurring_series_repayment_id,
            )
            .where(RealEstateDebtLink.asset_id == asset_id)
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
            .where(RealEstateDebtLink.asset_id == asset_id)
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


async def _validate_real_estate_debts(
    session: AsyncSession,
    debt_ids: list[int],
    asset_id: int | None = None,
) -> list[Debt]:
    if not debt_ids:
        return []
    debts = (
        await session.execute(select(Debt).where(Debt.id.in_(debt_ids)))
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


@router.get("/real-estate", response_model=list[RealEstateRead])
async def list_real_estate(
    session: AsyncSession = Depends(get_session),
) -> list[RealEstateRead]:
    assets = (
        await session.execute(
            select(RealEstateAsset).order_by(RealEstateAsset.name)
        )
    ).scalars().all()
    debts_by_asset: dict[int, list[tuple[Debt, str | None, str | None]]] = {}
    linked_debts = (
        await session.execute(
            select(
                RealEstateDebtLink.asset_id,
                Debt,
                RecurringSeries.label.label("repayment_label"),
            )
            .join(Debt, Debt.id == RealEstateDebtLink.debt_id)
            .outerjoin(
                RecurringSeries,
                RecurringSeries.id == Debt.recurring_series_repayment_id,
            )
            .order_by(RealEstateDebtLink.asset_id, Debt.name, Debt.id)
        )
    ).all()
    # Also get insurance labels
    insurance_labels = {
        row.id: row.label
        for row in (
            await session.execute(
                select(Debt.id, RecurringSeries.label)
                .join(RecurringSeries, RecurringSeries.id == Debt.recurring_series_insurance_id)
            )
        ).all()
    }
    for asset_id, debt, repayment_label in linked_debts:
        insurance_label = insurance_labels.get(debt.id)
        debts_by_asset.setdefault(asset_id, []).append((debt, repayment_label, insurance_label))
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
        _real_estate_read(
            asset,
            debts_by_asset.get(asset.id, []),
            attachment_count=int(attachment_counts.get(asset.id, 0)),
        )
        for asset in assets
    ]


@router.post("/real-estate", response_model=RealEstateRead, status_code=201)
async def create_real_estate(
    payload: RealEstateCreate, session: AsyncSession = Depends(get_session)
) -> RealEstateRead:
    debts = await _validate_real_estate_debts(session, payload.debt_ids)
    asset = RealEstateAsset(**payload.model_dump(exclude={"debt_ids"}))
    session.add(asset)
    await session.flush()
    await _replace_real_estate_debts(session, asset.id, debts)
    await session.commit()
    await session.refresh(asset)
    return _real_estate_read(asset, await _load_real_estate_debts(session, asset.id))


@router.patch("/real-estate/{asset_id}", response_model=RealEstateRead)
async def update_real_estate(
    asset_id: int,
    payload: RealEstateUpdate,
    session: AsyncSession = Depends(get_session),
) -> RealEstateRead:
    asset = await session.get(RealEstateAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
    data = payload.model_dump(exclude_unset=True)
    debt_ids = data.pop("debt_ids", None)
    debts = (
        await _validate_real_estate_debts(session, debt_ids, asset_id)
        if debt_ids is not None
        else None
    )
    for field, value in data.items():
        setattr(asset, field, value)
    if debts is not None:
        await _replace_real_estate_debts(session, asset.id, debts)
    await session.commit()
    await session.refresh(asset)
    attachment_count = await session.scalar(
        select(func.count())
        .select_from(RealEstateAttachment)
        .where(RealEstateAttachment.asset_id == asset.id)
    )
    return _real_estate_read(
        asset,
        await _load_real_estate_debts(session, asset.id),
        int(attachment_count or 0),
    )


@router.delete("/real-estate/{asset_id}", status_code=204)
async def delete_real_estate(
    asset_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    asset = await session.get(RealEstateAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    asset = await session.get(RealEstateAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    asset = await session.get(RealEstateAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> None:
    asset = await session.get(RealEstateAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
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
) -> RealEstateAttachment:
    attachment = await session.get(RealEstateAttachment, attachment_id)
    if attachment is None or attachment.asset_id != asset_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    return attachment


@router.get(
    "/real-estate/{asset_id}/attachments",
    response_model=list[RealEstateAttachmentRead],
)
async def list_real_estate_attachments(
    asset_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[RealEstateAttachmentRead]:
    if await session.get(RealEstateAsset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> RealEstateAttachmentRead:
    if await session.get(RealEstateAsset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_real_estate_attachment(
        session,
        asset_id,
        attachment_id,
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
    session: AsyncSession = Depends(get_session),
) -> None:
    if await session.get(RealEstateAsset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Bien immobilier introuvable")
    attachment = await _require_real_estate_attachment(
        session,
        asset_id,
        attachment_id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


# --------------------------------------------------------------------------- #
# Holdings
# --------------------------------------------------------------------------- #
def _holding_read(
    holding: Holding,
    operation_count: int = 0,
    *,
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
    )


async def _holding_response(session: AsyncSession, holding: Holding) -> HoldingRead:
    operations = (
        await session.execute(
            select(HoldingOperation).where(HoldingOperation.holding_id == holding.id)
        )
    ).scalars().all()
    realized = _holding_realized_metrics(operations)
    return _holding_read(
        holding,
        len(operations),
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
    session: AsyncSession = Depends(get_session),
) -> list[HoldingRead]:
    statement = select(Holding).order_by(Holding.name)
    if account_id is not None:
        if await session.get(Account, account_id) is None:
            raise HTTPException(status_code=404, detail="Compte introuvable")
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
                realized_cost_basis=realized.realized_cost_basis,
                realized_gain=realized.realized_gain,
            )
        )
    return result


@router.post("/holdings", response_model=HoldingRead, status_code=201)
async def create_holding(
    payload: HoldingCreate, session: AsyncSession = Depends(get_session)
) -> HoldingRead:
    await require_holding_account(session, payload.account_id, writable=True)
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
    return await _holding_response(session, holding)


@router.patch("/holdings/{holding_id}", response_model=HoldingRead)
async def update_holding(
    holding_id: int, payload: HoldingUpdate, session: AsyncSession = Depends(get_session)
) -> HoldingRead:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    data = payload.model_dump(exclude_unset=True)
    target_account_id = data.pop("account_id", holding.account_id)
    if target_account_id != holding.account_id:
        await require_holding_account(session, target_account_id, writable=True)
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
            return await _holding_response(session, destination)
    for field, value in data.items():
        setattr(holding, field, value)
    await session.commit()
    await session.refresh(holding)
    return await _holding_response(session, holding)


@router.delete("/holdings/{holding_id}", status_code=204)
async def delete_holding(holding_id: int, session: AsyncSession = Depends(get_session)) -> None:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    await session.delete(holding)
    await session.commit()


@router.get(
    "/holdings/{holding_id}/operations",
    response_model=list[HoldingOperationRead],
)
async def list_holding_operations(
    holding_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[HoldingOperationRead]:
    if await session.get(Holding, holding_id) is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> list[HoldingOperationRead]:
    rows = (
        await session.execute(
            select(HoldingOperation).order_by(
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
    session: AsyncSession = Depends(get_session),
) -> HoldingOperationResult:
    if payload.holding_id is not None:
        source_holding = await session.get(Holding, payload.holding_id)
        if source_holding is None:
            raise HTTPException(status_code=404, detail="Actif introuvable")
        await require_account(session, source_holding.account_id, writable=True)
        target_account_id = (
            payload.target_account_id
            if payload.target_account_id is not None
            else source_holding.account_id
        )
        await require_holding_account(session, target_account_id, writable=True)
        holding, is_new_holding = await _holding_for_account(
            session,
            source_holding,
            target_account_id,
        )
    else:
        new_holding = payload.new_holding
        if new_holding is None:
            raise HTTPException(status_code=422, detail="Nouvel actif manquant")
        await require_holding_account(session, new_holding.account_id, writable=True)
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
        holding=await _holding_response(session, holding),
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
    session: AsyncSession = Depends(get_session),
) -> HoldingOperationResult:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    operation = await session.get(HoldingOperation, operation_id)
    if operation is None or operation.holding_id != holding_id:
        raise HTTPException(status_code=404, detail="Operation introuvable")

    target_account_id = (
        payload.target_account_id
        if payload.target_account_id is not None
        else holding.account_id
    )
    await require_holding_account(session, target_account_id, writable=True)
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
        holding=await _holding_response(session, destination),
        operation=operation_reads[operation.id],
    )


@router.delete(
    "/holdings/{holding_id}/operations/{operation_id}",
    response_model=HoldingRead,
)
async def delete_holding_operation(
    holding_id: int,
    operation_id: int,
    session: AsyncSession = Depends(get_session),
) -> HoldingRead:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
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
    return await _holding_response(session, holding)


# --------------------------------------------------------------------------- #
# Contributions
# --------------------------------------------------------------------------- #
@router.get("/holdings/{holding_id}/contributions", response_model=list[ContributionRead])
async def list_contributions(
    holding_id: int, session: AsyncSession = Depends(get_session)
) -> list[ContributionRead]:
    if await session.get(Holding, holding_id) is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
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
    session: AsyncSession = Depends(get_session),
) -> ContributionRead:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    contribution = Contribution(holding_id=holding_id, **payload.model_dump())
    session.add(contribution)
    await session.commit()
    await session.refresh(contribution)
    return ContributionRead.model_validate(contribution)


@router.delete("/holdings/{holding_id}/contributions/{contribution_id}", status_code=204)
async def delete_contribution(
    holding_id: int,
    contribution_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    contribution = await session.get(Contribution, contribution_id)
    if contribution is None or contribution.holding_id != holding_id:
        raise HTTPException(status_code=404, detail="Versement introuvable")
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    await session.delete(contribution)
    await session.commit()


@router.get("/contributions", response_model=list[ContributionRead])
async def list_all_contributions(
    session: AsyncSession = Depends(get_session),
) -> list[ContributionRead]:
    rows = (
        await session.execute(
            select(Contribution).order_by(Contribution.occurred_on, Contribution.id)
        )
    ).scalars().all()
    return [ContributionRead.model_validate(row) for row in rows]


@router.post("/contributions", response_model=ContributionRead, status_code=201)
async def create_aggregate_contribution(
    payload: ContributionCreateAggregate,
    session: AsyncSession = Depends(get_session),
) -> ContributionRead:
    holding = await session.get(Holding, payload.holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    contribution = Contribution(**payload.model_dump())
    session.add(contribution)
    await session.commit()
    await session.refresh(contribution)
    return ContributionRead.model_validate(contribution)


# --------------------------------------------------------------------------- #
# Portfolio analytics
# --------------------------------------------------------------------------- #
@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary(session: AsyncSession = Depends(get_session)) -> PortfolioSummary:
    holdings = (await session.execute(select(Holding))).scalars().all()
    properties = (await session.execute(select(RealEstateAsset))).scalars().all()
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
    holdings_unrealized_cost_basis = sum(
        (Decimal(h.quantity) * Decimal(h.average_price) for h in holdings), Decimal("0")
    )
    holdings_market_value = sum(
        (Decimal(h.quantity) * Decimal(h.current_price) for h in holdings), Decimal("0")
    )
    holdings_realized = [
        _holding_realized_metrics(operations_by_holding[holding.id]) for holding in holdings
    ]
    holdings_realized_cost_basis = sum(
        (item.realized_cost_basis for item in holdings_realized),
        Decimal("0"),
    )
    holdings_realized_gain = sum(
        (item.realized_gain for item in holdings_realized),
        Decimal("0"),
    )
    property_values = [_real_estate_owned_values(asset) for asset in properties]
    properties_cost_basis = sum(
        (purchase_price for purchase_price, _ in property_values), Decimal("0")
    )
    properties_market_value = sum(
        (current_value for _, current_value in property_values), Decimal("0")
    )
    unrealized_cost_basis = holdings_unrealized_cost_basis + properties_cost_basis
    realized_cost_basis = holdings_realized_cost_basis
    total_cost_basis = unrealized_cost_basis + realized_cost_basis
    market_value = holdings_market_value + properties_market_value
    unrealized_gain = (holdings_market_value - holdings_unrealized_cost_basis) + (
        properties_market_value - properties_cost_basis
    )
    realized_gain = holdings_realized_gain
    total_gain = unrealized_gain + realized_gain
    contributions_total = await session.scalar(
        select(func.coalesce(func.sum(Contribution.amount), 0))
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
async def portfolio_allocation(session: AsyncSession = Depends(get_session)) -> list[AllocationSlice]:
    holdings = (await session.execute(select(Holding))).scalars().all()
    properties = (await session.execute(select(RealEstateAsset))).scalars().all()
    by_class: dict[str, Decimal] = {}
    for holding in holdings:
        value = Decimal(holding.quantity) * Decimal(holding.current_price)
        if value <= 0:
            continue
        by_class[holding.asset_class] = by_class.get(holding.asset_class, Decimal("0")) + value
    for asset in properties:
        _, value = _real_estate_owned_values(asset)
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
    session: AsyncSession = Depends(get_session),
) -> list[PortfolioSnapshotRead]:
    rows = (
        await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.period))
    ).scalars().all()
    return [PortfolioSnapshotRead.model_validate(row) for row in rows]


@router.put("/portfolio/snapshots", response_model=PortfolioSnapshotRead)
async def upsert_portfolio_snapshot(
    payload: PortfolioSnapshotCreate, session: AsyncSession = Depends(get_session)
) -> PortfolioSnapshotRead:
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
    period: str | None = None, session: AsyncSession = Depends(get_session)
) -> PortfolioSnapshotRead:
    """Idempotently record the current portfolio valuation for a month (YYYY-MM)."""
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
) -> list[AssetPerformancePoint]:
    holdings = (await session.execute(select(Holding))).scalars().all()
    operations = (
        await session.execute(
            select(HoldingOperation).order_by(
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

        market_value = sum(
            (state.quantity * state.last_price for state in positions.values()),
            Decimal("0"),
        )
        unrealized_cost_basis = sum(
            (state.quantity * state.average_price for state in positions.values()),
            Decimal("0"),
        )
        realized_cost_basis = sum(
            (state.realized_cost_basis for state in positions.values()),
            Decimal("0"),
        )
        realized_gain = sum(
            (state.realized_gain for state in positions.values()),
            Decimal("0"),
        )
        if period == current_period:
            market_value = sum(
                (Decimal(row.quantity) * Decimal(row.current_price) for row in holdings),
                Decimal("0"),
            )
            unrealized_cost_basis = sum(
                (Decimal(row.quantity) * Decimal(row.average_price) for row in holdings),
                Decimal("0"),
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
    session: AsyncSession = Depends(get_session),
) -> list[AssetPerformancePoint]:
    return await _holding_performance(session)


@router.get("/portfolio/performance", response_model=list[PerformancePoint])
async def portfolio_performance(session: AsyncSession = Depends(get_session)) -> list[PerformancePoint]:
    month_expr = func.strftime("%Y-%m", Contribution.occurred_on)
    contrib_rows = (
        await session.execute(
            select(month_expr, func.sum(Contribution.amount))
            .group_by(month_expr)
            .order_by(month_expr)
        )
    ).all()
    contrib_by_period = {period: Decimal(amount or 0) for period, amount in contrib_rows}

    snapshots = (
        await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.period))
    ).scalars().all()
    snapshot_by_period = {s.period: s for s in snapshots}
    if not snapshot_by_period:
        asset_points = await _holding_performance(session)
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


async def _current_net_worth_components(
    session: AsyncSession,
    through: date,
) -> tuple[Decimal, Decimal, Decimal, Decimal, set[int]]:
    investment_accounts = await _investment_account_ids(session)
    balances = await account_balances(session, through=through)
    cash = sum(
        (
            balance
            for account_id, balance in balances.items()
            if account_id not in investment_accounts
        ),
        Decimal("0"),
    )

    holdings = (await session.execute(select(Holding))).scalars().all()
    investments = sum(
        (Decimal(h.quantity) * Decimal(h.current_price) for h in holdings), Decimal("0")
    )
    properties = (await session.execute(select(RealEstateAsset))).scalars().all()
    real_estate = sum(
        (_real_estate_owned_values(asset)[1] for asset in properties), Decimal("0")
    )
    debts = await session.scalar(select(func.coalesce(func.sum(Debt.balance), 0)))
    debts_total = Decimal(debts or 0)
    return cash, investments, real_estate, debts_total, investment_accounts


@router.get("/networth/overview", response_model=NetWorthOverview)
async def net_worth_overview(
    as_of: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> NetWorthOverview:
    through = as_of or local_today()
    cash, investments, real_estate, debts_total, _ = (
        await _current_net_worth_components(session, through)
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
        await _current_net_worth_components(session, today)
    )
    snapshots = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.period <= current_period)
            .order_by(BalanceSnapshot.period, BalanceSnapshot.account_id)
        )
    ).scalars().all()

    cash_snapshots_by_period: dict[str, list[BalanceSnapshot]] = {}
    for snapshot in snapshots:
        if snapshot.account_id in investment_accounts:
            continue
        cash_snapshots_by_period.setdefault(snapshot.period, []).append(snapshot)

    contrib_rows = (
        await session.execute(
            select(
                func.strftime("%Y-%m", Contribution.occurred_on), func.sum(Contribution.amount)
            )
            .where(Contribution.occurred_on <= today)
            .group_by(func.strftime("%Y-%m", Contribution.occurred_on))
            .order_by(func.strftime("%Y-%m", Contribution.occurred_on))
        )
    ).all()
    contrib_by_period = {period: Decimal(amount or 0) for period, amount in contrib_rows}
    portfolio_snapshots = (
        await session.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.period <= current_period)
            .order_by(PortfolioSnapshot.period)
        )
    ).scalars().all()
    portfolio_by_period = {
        snapshot.period: Decimal(snapshot.market_value)
        for snapshot in portfolio_snapshots
    }

    properties = (await session.execute(select(RealEstateAsset))).scalars().all()
    property_changes: dict[str, Decimal] = {}
    for asset in properties:
        purchase_price, current_value = _real_estate_owned_values(asset)
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
            latest_cash_by_account[snapshot.account_id] = Decimal(snapshot.balance)
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
