"""Account balance calculations shared by API read models."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .common import add_month, local_today, money
from .models import Account, BalanceSnapshot


@dataclass(frozen=True)
class AccountBalanceShare:
    """The whole account balance and one profile's deterministic share."""

    total: Decimal
    profile_share: Decimal
    owner_ids: tuple[int, ...]


def missing_snapshot_periods(
    periods: Collection[str],
    *,
    through: date | None = None,
) -> list[str]:
    """Return missing statement months from the first statement to month N-1."""
    known_periods = set(periods)
    if not known_periods:
        return []

    cursor = date.fromisoformat(f"{min(known_periods)}-01")
    last_expected_month = add_month((through or local_today()).replace(day=1), -1)
    missing: list[str] = []
    while cursor <= last_expected_month:
        period = cursor.strftime("%Y-%m")
        if period not in known_periods:
            missing.append(period)
        cursor = add_month(cursor, 1)
    return missing


async def account_missing_snapshot_periods(
    session: AsyncSession,
    *,
    through: date | None = None,
    account_ids: Collection[int] | None = None,
) -> dict[int, list[str]]:
    ids = set(account_ids) if account_ids is not None else None
    if ids is not None and not ids:
        return {}

    statement = select(BalanceSnapshot.account_id, BalanceSnapshot.period).order_by(
        BalanceSnapshot.account_id,
        BalanceSnapshot.period,
    )
    if ids is not None:
        statement = statement.where(BalanceSnapshot.account_id.in_(ids))

    periods_by_account = {account_id: [] for account_id in ids or ()}
    for account_id, period in (await session.execute(statement)).all():
        periods_by_account.setdefault(account_id, []).append(period)

    return {
        account_id: missing_snapshot_periods(periods, through=through)
        for account_id, periods in periods_by_account.items()
    }


async def account_balances(
    session: AsyncSession,
    *,
    through: date | None = None,
    account_ids: Collection[int] | None = None,
) -> dict[int, Decimal]:
    """Return balances from the latest statement, falling back to opening balances."""
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


async def account_balance_shares(
    session: AsyncSession,
    profile_id: int,
    *,
    through: date | None = None,
    account_ids: Collection[int] | None = None,
) -> dict[int, AccountBalanceShare]:
    """Return total balances and the active profile's shares for owned accounts."""
    # Imported here to keep the low-level balance calculation independent from
    # request/session authentication.
    from .account_access import account_owner_ids, allocate_equal_shares, visible_account_ids

    visible_ids = await visible_account_ids(session, profile_id)
    ids = visible_ids if account_ids is None else visible_ids.intersection(account_ids)
    totals = await account_balances(session, through=through, account_ids=ids)
    result: dict[int, AccountBalanceShare] = {}
    for account_id, total in totals.items():
        owner_ids = tuple(await account_owner_ids(session, account_id))
        result[account_id] = AccountBalanceShare(
            total=total,
            profile_share=allocate_equal_shares(total, owner_ids)[profile_id],
            owner_ids=owner_ids,
        )
    return result
