"""Extended account management: metadata, pockets and monthly snapshots."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..common import money
from ..db import get_session
from ..models import Account, AccountPocket, BalanceSnapshot, Transaction
from ..schemas import (
    AccountDetail,
    AccountHistoryPoint,
    AccountPocketCreate,
    AccountPocketRead,
    AccountPocketUpdate,
    AccountRead,
    AccountUpdate,
    BalanceSnapshotCreate,
    BalanceSnapshotRead,
)

router = APIRouter(tags=["accounts"])


async def _require_account(session: AsyncSession, account_id: int) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return account


async def _balance(session: AsyncSession, account: Account) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.account_id == account.id
        )
    )
    return money(account.initial_balance + Decimal(total or 0))


def _account_read(account: Account, balance: Decimal) -> AccountRead:
    return AccountRead.model_validate(account).model_copy(update={"balance": balance})


@router.get("/accounts/{account_id}", response_model=AccountDetail)
async def get_account(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> AccountDetail:
    account = await _require_account(session, account_id)
    balance = await _balance(session, account)
    pockets = (
        await session.execute(
            select(AccountPocket)
            .where(AccountPocket.account_id == account_id)
            .order_by(AccountPocket.name)
        )
    ).scalars().all()
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
        balance=balance,
        pockets=[AccountPocketRead.model_validate(p) for p in pockets],
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
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(account, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    return _account_read(account, await _balance(session, account))


@router.post("/accounts/{account_id}/archive", response_model=AccountRead)
async def archive_account(
    account_id: int,
    archived: bool = True,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id)
    account.archived = archived
    await session.commit()
    await session.refresh(account)
    return _account_read(account, await _balance(session, account))


# --------------------------------------------------------------------------- #
# Pockets
# --------------------------------------------------------------------------- #
@router.get("/accounts/{account_id}/pockets", response_model=list[AccountPocketRead])
async def list_pockets(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> list[AccountPocketRead]:
    await _require_account(session, account_id)
    rows = (
        await session.execute(
            select(AccountPocket)
            .where(AccountPocket.account_id == account_id)
            .order_by(AccountPocket.name)
        )
    ).scalars().all()
    return [AccountPocketRead.model_validate(row) for row in rows]


@router.post("/accounts/{account_id}/pockets", response_model=AccountPocketRead, status_code=201)
async def create_pocket(
    account_id: int,
    payload: AccountPocketCreate,
    session: AsyncSession = Depends(get_session),
) -> AccountPocketRead:
    await _require_account(session, account_id)
    pocket = AccountPocket(account_id=account_id, **payload.model_dump())
    session.add(pocket)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Cette poche existe deja") from exc
    await session.refresh(pocket)
    return AccountPocketRead.model_validate(pocket)


@router.patch("/accounts/{account_id}/pockets/{pocket_id}", response_model=AccountPocketRead)
async def update_pocket(
    account_id: int,
    pocket_id: int,
    payload: AccountPocketUpdate,
    session: AsyncSession = Depends(get_session),
) -> AccountPocketRead:
    pocket = await session.get(AccountPocket, pocket_id)
    if pocket is None or pocket.account_id != account_id:
        raise HTTPException(status_code=404, detail="Poche introuvable")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(pocket, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Cette poche existe deja") from exc
    await session.refresh(pocket)
    return AccountPocketRead.model_validate(pocket)


@router.delete("/accounts/{account_id}/pockets/{pocket_id}", status_code=204)
async def delete_pocket(
    account_id: int,
    pocket_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    pocket = await session.get(AccountPocket, pocket_id)
    if pocket is None or pocket.account_id != account_id:
        raise HTTPException(status_code=404, detail="Poche introuvable")
    await session.delete(pocket)
    await session.commit()


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


@router.put("/accounts/{account_id}/snapshots", response_model=BalanceSnapshotRead)
async def upsert_snapshot(
    account_id: int,
    payload: BalanceSnapshotCreate,
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    """Create or overwrite the snapshot for a period (idempotent)."""
    await _require_account(session, account_id)
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


@router.post("/accounts/{account_id}/snapshots/generate", response_model=list[BalanceSnapshotRead])
async def generate_snapshots(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> list[BalanceSnapshotRead]:
    """Rebuild month-end cumulative snapshots from the ledger (idempotent)."""
    account = await _require_account(session, account_id)
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
    await session.commit()

    refreshed = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    return [BalanceSnapshotRead.model_validate(row) for row in refreshed]
