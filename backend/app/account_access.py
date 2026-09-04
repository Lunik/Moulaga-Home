"""Shared guards for account-backed mutations."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Account

READ_ONLY_DETAIL = "Ce compte est archive et accessible en lecture seule"


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
