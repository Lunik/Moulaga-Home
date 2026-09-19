"""Shared guards for account-backed mutations."""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .common import money
from .models import Account, AccountOwner
from .profile_session import require_active_profile

__all__ = ["require_active_profile"]

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


def allocate_equal_shares(
    amount: Decimal | int | float | str,
    profile_ids: list[int] | tuple[int, ...] | set[int],
) -> dict[int, Decimal]:
    """Split a monetary amount equally, assigning residual cents by profile id."""
    owners = sorted(set(profile_ids))
    if not owners:
        raise ValueError("Une ressource doit avoir au moins un proprietaire")

    cents = int((money(amount) * 100).to_integral_exact())
    sign = -1 if cents < 0 else 1
    quotient, remainder = divmod(abs(cents), len(owners))
    return {
        profile_id: money(
            Decimal(sign * (quotient + (index < remainder))) / Decimal("100")
        )
        for index, profile_id in enumerate(owners)
    }


def account_owner_member_column():
    """Return the association column during the profile-id → member-id transition."""
    return (
        AccountOwner.member_id
        if hasattr(AccountOwner, "member_id")
        else AccountOwner.profile_id
    )


def account_owner(account_id: int, member_id: int) -> AccountOwner:
    """Create an owner association using the integration contract's member id."""
    column_name = (
        "member_id" if hasattr(AccountOwner, "member_id") else "profile_id"
    )
    return AccountOwner(account_id=account_id, **{column_name: member_id})


async def account_owner_ids(session: AsyncSession, account_id: int) -> list[int]:
    """Return account owners in the stable order used to allocate residual cents."""
    return list(
        (
            await session.scalars(
                select(account_owner_member_column())
                .where(AccountOwner.account_id == account_id)
                .order_by(account_owner_member_column())
            )
        ).all()
    )


async def account_share(
    session: AsyncSession,
    account_id: int,
    profile_id: int,
    amount: Decimal | int | float | str,
) -> Decimal:
    """Return ``profile_id``'s deterministic equal share of an account amount."""
    return allocate_equal_shares(amount, await account_owner_ids(session, account_id)).get(
        profile_id,
        Decimal("0.00"),
    )


async def visible_account_ids(
    session: AsyncSession,
    profile_id: int,
) -> set[int]:
    """Return accounts owned by the active profile, including archived accounts."""
    return set(
        (
            await session.scalars(
                select(AccountOwner.account_id).where(
                    account_owner_member_column() == profile_id
                )
            )
        ).all()
    )


async def require_account(
    session: AsyncSession,
    account_id: int,
    *,
    writable: bool = False,
    profile_id: int | None = None,
) -> Account:
    account = await session.get(Account, account_id)
    if account is None or (
        profile_id is not None
        and profile_id not in await account_owner_ids(session, account_id)
    ):
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if writable:
        ensure_account_writable(account)
    return account


async def require_holding_account(
    session: AsyncSession,
    account_id: int,
    *,
    writable: bool = False,
    profile_id: int | None = None,
) -> Account:
    account = await require_account(
        session,
        account_id,
        writable=writable,
        profile_id=profile_id,
    )
    if account.type not in HOLDING_ACCOUNT_TYPES:
        raise HTTPException(status_code=422, detail=UNSUPPORTED_HOLDING_ACCOUNT_DETAIL)
    return account
