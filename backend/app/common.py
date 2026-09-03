"""Shared helpers: money quantization, budget-cycle math and actor auth."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .models import HouseholdMember, Preferences

TWO_PLACES = Decimal("0.01")

# Role capability ordering for the local (no remote auth) sharing model.
ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def money(value: Decimal | int | float | str | None) -> Decimal:
    """Return a 2-decimal Decimal, treating ``None`` as zero."""
    if value is None:
        return Decimal("0.00")
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def add_month(day: date, months: int) -> date:
    """Add whole months to a date, clamping the day to the target month."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    last = monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def cycle_bounds(reference: date, start_day: int) -> tuple[date, date]:
    """Inclusive [start, end] of the budget cycle containing ``reference``.

    ``start_day`` is clamped to 1..28 so every month has the anchor day.
    """
    start_day = max(1, min(28, start_day))
    if reference.day >= start_day:
        start = reference.replace(day=start_day)
    else:
        start = add_month(reference.replace(day=start_day), -1)
    end = add_month(start, 1) - timedelta(days=1)
    return start, end


async def get_preferences(session: AsyncSession) -> Preferences:
    prefs = await session.get(Preferences, 1)
    if prefs is None:
        prefs = Preferences(id=1)
        session.add(prefs)
        await session.commit()
        await session.refresh(prefs)
    return prefs


async def require_actor(
    session: AsyncSession,
    household_id: int,
    minimum_role: str,
    actor_id: int | None,
) -> HouseholdMember:
    """Resolve and authorize the acting member for a household mutation.

    Because Moulaga has no remote authentication, mutating endpoints require an
    explicit ``actor_id`` identifying a local profile. The actor must belong to
    the target household and hold at least ``minimum_role``. This is a local
    role check only and is never a substitute for network authentication.
    """
    if actor_id is None:
        raise HTTPException(status_code=401, detail="actor_id requis pour cette action")
    member = await session.get(HouseholdMember, actor_id)
    if member is None or member.household_id != household_id:
        raise HTTPException(status_code=403, detail="Acteur inconnu pour ce foyer")
    if ROLE_RANK.get(member.role, -1) < ROLE_RANK[minimum_role]:
        raise HTTPException(status_code=403, detail="Role insuffisant pour cette action")
    return member


async def actor_header(x_actor_id: int | None = Header(default=None)) -> int | None:
    """FastAPI dependency exposing the optional ``X-Actor-Id`` header."""
    return x_actor_id
