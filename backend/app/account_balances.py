"""Account balance calculations shared by API read models."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .common import money
from .models import Account, BalanceSnapshot, Transaction


async def account_balances(
    session: AsyncSession,
    *,
    through: date | None = None,
    account_ids: Collection[int] | None = None,
) -> dict[int, Decimal]:
    """Return balances based on the latest statement and later movements."""
    ids = set(account_ids) if account_ids is not None else None
    if ids is not None and not ids:
        return {}

    account_statement = select(Account.id, Account.initial_balance)
    if ids is not None:
        account_statement = account_statement.where(Account.id.in_(ids))
    account_rows = (await session.execute(account_statement)).all()
    balances = {
        account_id: Decimal(initial_balance)
        for account_id, initial_balance in account_rows
    }
    if not balances:
        return {}

    cutoff_period = through.strftime("%Y-%m") if through is not None else None
    snapshot_statement = select(
        BalanceSnapshot.account_id,
        BalanceSnapshot.period,
        BalanceSnapshot.balance,
    ).order_by(BalanceSnapshot.account_id, BalanceSnapshot.period.desc())
    if ids is not None:
        snapshot_statement = snapshot_statement.where(
            BalanceSnapshot.account_id.in_(ids)
        )
    if cutoff_period is not None:
        snapshot_statement = snapshot_statement.where(
            BalanceSnapshot.period <= cutoff_period
        )

    latest_periods: dict[int, str] = {}
    for account_id, period, balance in (
        await session.execute(snapshot_statement)
    ).all():
        if account_id in latest_periods:
            continue
        latest_periods[account_id] = period
        balances[account_id] = Decimal(balance)

    transaction_period = func.strftime("%Y-%m", Transaction.booked_at)
    transaction_statement = select(
        Transaction.account_id,
        transaction_period,
        func.sum(Transaction.amount),
    ).group_by(Transaction.account_id, transaction_period)
    if ids is not None:
        transaction_statement = transaction_statement.where(
            Transaction.account_id.in_(ids)
        )
    if through is not None:
        transaction_statement = transaction_statement.where(
            Transaction.booked_at <= through
        )

    for account_id, period, total in (
        await session.execute(transaction_statement)
    ).all():
        latest_period = latest_periods.get(account_id)
        if latest_period is None or period > latest_period:
            balances[account_id] += Decimal(total or 0)

    return {
        account_id: money(balance)
        for account_id, balance in balances.items()
    }


async def account_balance(
    session: AsyncSession,
    account: Account,
    *,
    through: date | None = None,
) -> Decimal:
    balances = await account_balances(
        session,
        through=through,
        account_ids={account.id},
    )
    return balances.get(account.id, money(account.initial_balance))
