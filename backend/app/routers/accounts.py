"""Extended account management: metadata and monthly snapshots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import ensure_account_writable, require_account
from ..common import money
from ..db import get_session
from ..models import (
    Account,
    BalanceSnapshot,
    Debt,
    Goal,
    Holding,
    RecurringSeries,
    SharedAccountLink,
    Transaction,
)
from ..schemas import (
    AccountDetail,
    AccountHistoryPoint,
    AccountRead,
    AccountUpdate,
    BalanceSnapshotCreate,
    BalanceSnapshotRead,
    BalanceSnapshotUpdate,
)

router = APIRouter(tags=["accounts"])


async def _require_account(session: AsyncSession, account_id: int) -> Account:
    return await require_account(session, account_id)


async def _balance(session: AsyncSession, account: Account) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.account_id == account.id
        )
    )
    return money(account.initial_balance + Decimal(total or 0))


async def _account_read(session: AsyncSession, account: Account) -> AccountRead:
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.account_id == account.id
        )
    )
    return AccountRead.model_validate(account).model_copy(
        update={
            "balance": await _balance(session, account),
            "transaction_count": int(count or 0),
        }
    )


async def _has_dependencies(session: AsyncSession, account_id: int) -> bool:
    for model in (
        Transaction,
        BalanceSnapshot,
        RecurringSeries,
        Debt,
        Holding,
        SharedAccountLink,
        Goal,
    ):
        dependency_id = await session.scalar(
            select(model.id).where(model.account_id == account_id).limit(1)
        )
        if dependency_id is not None:
            return True
    return False


@router.get("/accounts/{account_id}", response_model=AccountDetail)
async def get_account(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> AccountDetail:
    account = await _require_account(session, account_id)
    balance = await _balance(session, account)
    snapshots = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id)
    )
    detail = AccountDetail(
        id=account.id,
        name=account.name,
        type=account.type,
        currency=account.currency,
        initial_balance=account.initial_balance,
        institution=account.institution,
        color=account.color,
        archived=account.archived,
        savings_product=account.savings_product,
        annual_interest_rate=account.annual_interest_rate,
        legal_cap=account.legal_cap,
        balance=balance,
        history=[
            AccountHistoryPoint(period=s.period, balance=money(s.balance)) for s in snapshots
        ],
        transaction_count=int(count or 0),
    )
    return detail


@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(account, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    return await _account_read(session, account)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    if await _has_dependencies(session, account_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Ce compte contient un historique ou des liens. "
                "Archivez-le pour conserver vos donnees."
            ),
        )
    await session.delete(account)
    await session.commit()


@router.post("/accounts/{account_id}/archive", response_model=AccountRead)
async def archive_account(
    account_id: int,
    archived: bool = True,
    transfer_to_account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id)
    if transfer_to_account_id is not None:
        if not archived:
            raise HTTPException(
                status_code=422,
                detail="Un transfert est uniquement possible lors de l'archivage",
            )
        if transfer_to_account_id == account_id:
            raise HTTPException(
                status_code=422,
                detail="Le compte de destination doit etre different",
            )
        destination = await _require_account(session, transfer_to_account_id)
        if destination.archived:
            raise HTTPException(
                status_code=409,
                detail="Le compte de destination est archive",
            )
        if destination.currency != account.currency:
            raise HTTPException(
                status_code=409,
                detail="Les deux comptes doivent utiliser la meme devise",
            )
        balance = await _balance(session, account)
        if balance <= 0:
            raise HTTPException(
                status_code=409,
                detail="Seul un solde positif peut etre transfere avant archivage",
            )
        transfer_group = uuid4().hex
        session.add_all(
            [
                Transaction(
                    booked_at=date.today(),
                    description=f"Transfert vers {destination.name}",
                    amount=money(-balance),
                    account_id=account.id,
                    transfer_group=transfer_group,
                ),
                Transaction(
                    booked_at=date.today(),
                    description=f"Transfert depuis {account.name}",
                    amount=money(balance),
                    account_id=destination.id,
                    transfer_group=transfer_group,
                ),
            ]
        )
    account.archived = archived
    await session.commit()
    await session.refresh(account)
    return await _account_read(session, account)


# --------------------------------------------------------------------------- #
# Monthly balance snapshots
# --------------------------------------------------------------------------- #
@router.get("/accounts/{account_id}/snapshots", response_model=list[BalanceSnapshotRead])
async def list_snapshots(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> list[BalanceSnapshotRead]:
    await _require_account(session, account_id)
    rows = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    return [BalanceSnapshotRead.model_validate(row) for row in rows]


async def _require_snapshot(
    session: AsyncSession,
    account_id: int,
    snapshot_id: int,
) -> BalanceSnapshot:
    snapshot = await session.get(BalanceSnapshot, snapshot_id)
    if snapshot is None or snapshot.account_id != account_id:
        raise HTTPException(status_code=404, detail="Releve introuvable")
    return snapshot


@router.put("/accounts/{account_id}/snapshots", response_model=BalanceSnapshotRead)
async def upsert_snapshot(
    account_id: int,
    payload: BalanceSnapshotCreate,
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    """Create or overwrite the snapshot for a period (idempotent)."""
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    existing = await session.scalar(
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.period == payload.period,
        )
    )
    if existing is None:
        existing = BalanceSnapshot(account_id=account_id, period=payload.period)
        session.add(existing)
    existing.balance = money(payload.balance)
    await session.commit()
    await session.refresh(existing)
    return BalanceSnapshotRead.model_validate(existing)


@router.patch(
    "/accounts/{account_id}/snapshots/{snapshot_id}",
    response_model=BalanceSnapshotRead,
)
async def update_snapshot(
    account_id: int,
    snapshot_id: int,
    payload: BalanceSnapshotUpdate,
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    snapshot = await _require_snapshot(session, account_id, snapshot_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(snapshot, field, money(value) if field == "balance" else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Un releve existe deja pour cette periode",
        ) from exc
    await session.refresh(snapshot)
    return BalanceSnapshotRead.model_validate(snapshot)


@router.delete("/accounts/{account_id}/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(
    account_id: int,
    snapshot_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    snapshot = await _require_snapshot(session, account_id, snapshot_id)
    await session.delete(snapshot)
    await session.commit()


@router.post("/accounts/{account_id}/snapshots/generate", response_model=list[BalanceSnapshotRead])
async def generate_snapshots(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> list[BalanceSnapshotRead]:
    """Rebuild month-end cumulative snapshots from the ledger (idempotent)."""
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    month_expr = func.strftime("%Y-%m", Transaction.booked_at)
    rows = (
        await session.execute(
            select(month_expr, func.sum(Transaction.amount))
            .where(Transaction.account_id == account_id)
            .group_by(month_expr)
            .order_by(month_expr)
        )
    ).all()

    existing = {
        snap.period: snap
        for snap in (
            await session.execute(
                select(BalanceSnapshot).where(BalanceSnapshot.account_id == account_id)
            )
        ).scalars().all()
    }

    running = Decimal(account.initial_balance)
    for period, delta in rows:
        running += Decimal(delta or 0)
        snapshot = existing.get(period)
        if snapshot is None:
            snapshot = BalanceSnapshot(account_id=account_id, period=period)
            session.add(snapshot)
            existing[period] = snapshot
        snapshot.balance = money(running)
    generated_periods = {period for period, _delta in rows}
    for period, snapshot in existing.items():
        if period not in generated_periods:
            await session.delete(snapshot)
    await session.commit()

    refreshed = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    return [BalanceSnapshotRead.model_validate(row) for row in refreshed]
