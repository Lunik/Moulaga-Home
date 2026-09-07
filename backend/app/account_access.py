"""Shared guards for account-backed mutations."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Account

READ_ONLY_DETAIL = "Ce compte est archive et accessible en lecture seule"
UNSUPPORTED_HOLDING_ACCOUNT_DETAIL = (
    "Ce type de compte ne prend pas en charge les actifs"
)
HOLDING_ACCOUNT_TYPES = frozenset(
    {
        # Preserve support for accounts created before the generic type was removed.
        "investment",
        "pea",
        "peg",
        "percol",
        "securities",
        "life_insurance",
        "wallet",
    }
)


def ensure_account_writable(account: Account) -> None:
    if account.archived:
        raise HTTPException(status_code=409, detail=READ_ONLY_DETAIL)


async def require_account(
    session: AsyncSession,
    account_id: int,
    *,
    writable: bool = False,
) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if writable:
        ensure_account_writable(account)
    return account


async def require_holding_account(
    session: AsyncSession,
    account_id: int,
    *,
    writable: bool = False,
) -> Account:
    account = await require_account(session, account_id, writable=writable)
    if account.type not in HOLDING_ACCOUNT_TYPES:
        raise HTTPException(status_code=422, detail=UNSUPPORTED_HOLDING_ACCOUNT_DETAIL)
    return account
