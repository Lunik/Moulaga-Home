"""Recurring series: CRUD, forecasting and deterministic detection.

Detection reads the locally-stored ledger only. It never writes speculative
transactions and it is idempotent: re-running does not duplicate series or the
pending change records it raises.
"""

from __future__ import annotations

import hashlib
import statistics
import unicodedata
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account
from ..common import add_month, money
from ..db import get_session
from ..models import Account, Category, RecurringChange, RecurringSeries, Transaction
from ..schemas import (
    DetectionProposal,
    DetectionSelection,
    DetectResult,
    ForecastPoint,
    RecurringChangeRead,
    RecurringCreate,
    RecurringRead,
    RecurringUpdate,
)

router = APIRouter(tags=["recurring"])

_FREQ_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 91, "yearly": 365}
_MIN_OCCURRENCES = 3
_AMOUNT_TOLERANCE = Decimal("0.01")


def _normalize_key(description: str, account_id: int) -> str:
    decomposed = unicodedata.normalize("NFKD", description.casefold())
    stripped = "".join(ch for ch in decomposed if ch.isalnum() or ch.isspace())
    collapsed = " ".join(stripped.split())
    raw = f"{account_id}|{collapsed}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 - non-security id


def _classify_frequency(intervals: list[int]) -> str | None:
    if not intervals:
        return None
    median = statistics.median(intervals)
    best = min(_FREQ_DAYS, key=lambda freq: abs(_FREQ_DAYS[freq] - median))
    # Reject patterns that are too irregular to be a real schedule.
    if abs(_FREQ_DAYS[best] - median) > _FREQ_DAYS[best] * 0.4:
        return None
    return best


def _advance(day: date, frequency: str) -> date:
    if frequency == "weekly":
        return date.fromordinal(day.toordinal() + 7)
    if frequency == "monthly":
        return add_month(day, 1)
    if frequency == "quarterly":
        return add_month(day, 3)
    return add_month(day, 12)


async def _require_account(session: AsyncSession, account_id: int) -> None:
    await require_account(session, account_id, writable=True)


async def _require_category(session: AsyncSession, category_id: int) -> None:
    if await session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")


async def _account_name(session: AsyncSession, account_id: int) -> str:
    account = await session.get(Account, account_id)
    return account.name if account else ""


async def _category_name(session: AsyncSession, category_id: int | None) -> str | None:
    if category_id is None:
        return None
    category = await session.get(Category, category_id)
    return category.name if category else None


async def _series_read(session: AsyncSession, series: RecurringSeries) -> RecurringRead:
    return RecurringRead(
        id=series.id,
        label=series.label,
        account_id=series.account_id,
        category_id=series.category_id,
        frequency=series.frequency,
        next_due=series.next_due,
        amount=series.amount,
        amount_type=series.amount_type,
        status=series.status,
        confidence=series.confidence,
        account_name=await _account_name(session, series.account_id),
        category_name=await _category_name(session, series.category_id),
    )


async def _change_read(session: AsyncSession, change: RecurringChange) -> RecurringChangeRead:
    series = await session.get(RecurringSeries, change.series_id)
    return RecurringChangeRead(
        id=change.id,
        series_id=change.series_id,
        change_type=change.change_type,
        detected_amount=change.detected_amount,
        detected_next_due=change.detected_next_due,
        status=change.status,
        note=change.note,
        series_label=series.label if series else "",
        series_status=series.status if series else "",
    )


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
@router.get("/recurring", response_model=list[RecurringRead])
async def list_series(session: AsyncSession = Depends(get_session)) -> list[RecurringRead]:
    rows = (
        await session.execute(select(RecurringSeries).order_by(RecurringSeries.next_due))
    ).scalars().all()
    accounts = {
        acc.id: acc.name for acc in (await session.execute(select(Account))).scalars().all()
    }
    categories = {
        cat.id: cat.name for cat in (await session.execute(select(Category))).scalars().all()
    }
    return [
        RecurringRead(
            id=row.id,
            label=row.label,
            account_id=row.account_id,
            category_id=row.category_id,
            frequency=row.frequency,
            next_due=row.next_due,
            amount=row.amount,
            amount_type=row.amount_type,
            status=row.status,
            confidence=row.confidence,
            account_name=accounts.get(row.account_id, ""),
            category_name=categories.get(row.category_id) if row.category_id else None,
        )
        for row in rows
    ]


@router.post("/recurring", response_model=RecurringRead, status_code=201)
async def create_series(
    payload: RecurringCreate, session: AsyncSession = Depends(get_session)
) -> RecurringRead:
    await _require_account(session, payload.account_id)
    if payload.category_id is not None:
        await _require_category(session, payload.category_id)
    series = RecurringSeries(
        **payload.model_dump(),
        match_key=_normalize_key(payload.label, payload.account_id),
    )
    session.add(series)
    await session.commit()
    await session.refresh(series)
    return await _series_read(session, series)


@router.patch("/recurring/{series_id}", response_model=RecurringRead)
async def update_series(
    series_id: int, payload: RecurringUpdate, session: AsyncSession = Depends(get_session)
) -> RecurringRead:
    series = await session.get(RecurringSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Serie introuvable")
    await require_account(session, series.account_id, writable=True)
    data = payload.model_dump(exclude_unset=True)
    if series.match_key is None:
        series.match_key = _normalize_key(series.label, series.account_id)
    if "account_id" in data:
        if data["account_id"] is None:
            raise HTTPException(status_code=422, detail="Compte requis")
        await _require_account(session, data["account_id"])
        if data["account_id"] != series.account_id:
            series.match_key = _normalize_key(data.get("label", series.label), data["account_id"])
    if data.get("category_id") is not None:
        await _require_category(session, data["category_id"])
    for field, value in data.items():
        setattr(series, field, value)
    await session.commit()
    await session.refresh(series)
    return await _series_read(session, series)


@router.delete("/recurring/{series_id}", status_code=204)
async def delete_series(series_id: int, session: AsyncSession = Depends(get_session)) -> None:
    series = await session.get(RecurringSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Serie introuvable")
    await require_account(session, series.account_id, writable=True)
    await session.delete(series)
    await session.commit()


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
@router.get("/recurring/forecast", response_model=list[ForecastPoint])
async def forecast(
    months: int = Query(default=3, ge=1, le=24),
    session: AsyncSession = Depends(get_session),
) -> list[ForecastPoint]:
    horizon = add_month(date.today(), months)
    series = (
        await session.execute(
            select(RecurringSeries).where(RecurringSeries.status == "active")
        )
    ).scalars().all()
    accounts = {
        acc.id: acc.name for acc in (await session.execute(select(Account))).scalars().all()
    }
    categories = {
        cat.id: cat.name for cat in (await session.execute(select(Category))).scalars().all()
    }
    points: list[ForecastPoint] = []
    for item in series:
        due = item.next_due
        guard = 0
        while due <= horizon and guard < 500:
            points.append(
                ForecastPoint(
                    series_id=item.id,
                    label=item.label,
                    due_date=due,
                    amount=money(item.amount),
                    account_name=accounts.get(item.account_id, ""),
                    category_name=categories.get(item.category_id) if item.category_id else None,
                    status=item.status,
                )
            )
            due = _advance(due, item.frequency)
            guard += 1
    points.sort(key=lambda point: (point.due_date, point.series_id))
    return points


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
async def _detection_proposals(session: AsyncSession) -> list[DetectionProposal]:
    transactions = (
        await session.execute(
            select(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .where(Account.archived.is_(False))
            .where(Transaction.transfer_group.is_(None))
            .order_by(Transaction.account_id, Transaction.booked_at)
        )
    ).scalars().all()

    groups: dict[str, list[Transaction]] = {}
    for transaction in transactions:
        key = _normalize_key(transaction.description, transaction.account_id)
        groups.setdefault(key, []).append(transaction)

    existing_rows = (await session.execute(select(RecurringSeries))).scalars().all()
    existing = {
        series.match_key or _normalize_key(series.label, series.account_id): series
        for series in existing_rows
    }
    accounts = {
        account.id: account.name
        for account in (await session.execute(select(Account))).scalars().all()
    }
    categories = {
        category.id: category.name
        for category in (await session.execute(select(Category))).scalars().all()
    }

    proposals: list[DetectionProposal] = []
    for key, items in groups.items():
        if len(items) < _MIN_OCCURRENCES:
            continue
        items.sort(key=lambda tx: tx.booked_at)
        intervals = [
            (items[i].booked_at - items[i - 1].booked_at).days for i in range(1, len(items))
        ]
        frequency = _classify_frequency(intervals)
        if frequency is None:
            continue

        amounts = [Decimal(item.amount) for item in items]
        is_fixed = max(amounts) - min(amounts) <= _AMOUNT_TOLERANCE
        detected_amount = money(amounts[-1] if is_fixed else sum(amounts) / len(amounts))
        next_due = _advance(items[-1].booked_at, frequency)
        confidence = min(Decimal("1.00"), Decimal(len(items)) / Decimal("6")).quantize(
            Decimal("0.01")
        )

        series = existing.get(key)
        if series is None:
            proposals.append(
                DetectionProposal(
                    proposal_key=key,
                    kind="series",
                    label=items[-1].description[:200],
                    account_id=items[-1].account_id,
                    account_name=accounts.get(items[-1].account_id, ""),
                    category_id=items[-1].category_id,
                    category_name=categories.get(items[-1].category_id)
                    if items[-1].category_id
                    else None,
                    frequency=frequency,
                    next_due=next_due,
                    amount=detected_amount,
                    amount_type="fixed" if is_fixed else "variable",
                    confidence=confidence,
                )
            )
            continue

        # Existing series: only propose a pending change, never overwrite silently.
        if (
            series.amount is not None
            and abs(Decimal(series.amount) - detected_amount) > _AMOUNT_TOLERANCE
            and not await _has_pending_change(session, series.id, detected_amount)
        ):
            proposals.append(
                DetectionProposal(
                    proposal_key=key,
                    kind="change",
                    series_id=series.id,
                    label=series.label,
                    account_id=series.account_id,
                    account_name=accounts.get(series.account_id, ""),
                    category_id=series.category_id,
                    category_name=categories.get(series.category_id) if series.category_id else None,
                    frequency=frequency,
                    next_due=next_due,
                    amount=detected_amount,
                    amount_type="fixed" if is_fixed else "variable",
                    confidence=confidence,
                )
            )

    return sorted(proposals, key=lambda proposal: (proposal.next_due, proposal.label.casefold()))


@router.get("/recurring/detect", response_model=list[DetectionProposal])
async def preview_detection(
    session: AsyncSession = Depends(get_session),
) -> list[DetectionProposal]:
    return await _detection_proposals(session)


@router.post("/recurring/detect", response_model=DetectResult)
async def detect(
    payload: DetectionSelection | None = None,
    session: AsyncSession = Depends(get_session),
) -> DetectResult:
    proposals = await _detection_proposals(session)
    proposals_by_key = {proposal.proposal_key: proposal for proposal in proposals}
    selected_keys = (
        set(proposals_by_key)
        if payload is None
        else set(payload.proposal_keys)
    )
    if selected_keys - proposals_by_key.keys():
        raise HTTPException(
            status_code=409,
            detail="Certaines propositions ne sont plus disponibles. Relancez la detection.",
        )

    created_series = 0
    created_changes = 0
    for proposal in proposals:
        if proposal.proposal_key not in selected_keys:
            continue
        await _require_account(session, proposal.account_id)
        if proposal.kind == "series":
            series = RecurringSeries(
                label=proposal.label,
                account_id=proposal.account_id,
                category_id=proposal.category_id,
                frequency=proposal.frequency,
                next_due=proposal.next_due,
                amount=proposal.amount,
                amount_type=proposal.amount_type,
                status="active",
                confidence=proposal.confidence,
                match_key=proposal.proposal_key,
            )
            session.add(series)
            created_series += 1
            continue

        if proposal.series_id is None:
            raise HTTPException(status_code=409, detail="Serie detectee introuvable")
        series = await session.get(RecurringSeries, proposal.series_id)
        if series is None:
            raise HTTPException(status_code=409, detail="Serie detectee introuvable")
        session.add(
            RecurringChange(
                series_id=series.id,
                change_type="amount",
                detected_amount=proposal.amount,
                detected_next_due=proposal.next_due,
                status="pending",
                note="Montant detecte different du montant enregistre",
            )
        )
        created_changes += 1

    await session.commit()
    return DetectResult(created_series=created_series, created_changes=created_changes)


async def _has_pending_change(
    session: AsyncSession, series_id: int, amount: Decimal
) -> bool:
    existing = (
        await session.execute(
            select(RecurringChange).where(
                RecurringChange.series_id == series_id,
                RecurringChange.status == "pending",
            )
        )
    ).scalars().all()
    return any(
        change.detected_amount is not None
        and abs(Decimal(change.detected_amount) - amount) <= _AMOUNT_TOLERANCE
        for change in existing
    )


# --------------------------------------------------------------------------- #
# Change records
# --------------------------------------------------------------------------- #
@router.get("/recurring/changes", response_model=list[RecurringChangeRead])
async def list_changes(
    status: str | None = Query(default=None, pattern="^(pending|accepted|rejected)$"),
    session: AsyncSession = Depends(get_session),
) -> list[RecurringChangeRead]:
    statement = select(RecurringChange).order_by(RecurringChange.id.desc())
    if status is not None:
        statement = statement.where(RecurringChange.status == status)
    rows = (await session.execute(statement)).scalars().all()
    series_map = {
        s.id: s for s in (await session.execute(select(RecurringSeries))).scalars().all()
    }
    return [
        RecurringChangeRead(
            id=row.id,
            series_id=row.series_id,
            change_type=row.change_type,
            detected_amount=row.detected_amount,
            detected_next_due=row.detected_next_due,
            status=row.status,
            note=row.note,
            series_label=series_map[row.series_id].label if row.series_id in series_map else "",
            series_status=series_map[row.series_id].status if row.series_id in series_map else "",
        )
        for row in rows
    ]


@router.post("/recurring/changes/{change_id}/action", response_model=RecurringChangeRead)
async def act_on_change(
    change_id: int,
    action: str = Query(pattern="^(accept|reject)$"),
    session: AsyncSession = Depends(get_session),
) -> RecurringChangeRead:
    change = await session.get(RecurringChange, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Changement introuvable")
    if change.status != "pending":
        raise HTTPException(status_code=409, detail="Changement deja traite")
    series = await session.get(RecurringSeries, change.series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Serie introuvable")
    await require_account(session, series.account_id, writable=True)

    if action == "accept":
        if change.detected_amount is not None:
            series.amount = money(change.detected_amount)
        if change.detected_next_due is not None:
            series.next_due = change.detected_next_due
        change.status = "accepted"
    else:
        # Reject performs no write to the series (no false writes).
        change.status = "rejected"

    await session.commit()
    await session.refresh(change)
    return await _change_read(session, change)
