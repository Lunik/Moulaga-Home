"""Projected budget occurrences derived from configured recurring series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .common import add_month, money
from .models import Account, RecurringSeries

_FREQUENCY_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}
_MONTHLY_FREQUENCY_MULTIPLIERS = {
    "weekly": Decimal("4"),
    "monthly": Decimal("1"),
    "quarterly": Decimal("1") / Decimal("3"),
    "yearly": Decimal("1") / Decimal("12"),
}


@dataclass(frozen=True)
class RecurringOccurrence:
    series_id: int
    due_date: date
    amount: Decimal
    account_id: int
    category_id: int | None


@dataclass(frozen=True)
class RecurringProjection:
    series_id: int
    amount: Decimal
    account_id: int
    category_id: int | None


def advance_recurrence(day: date, frequency: str, steps: int = 1) -> date:
    if frequency == "weekly":
        return day + timedelta(days=7 * steps)
    month_step = _FREQUENCY_MONTHS.get(frequency)
    if month_step is None:
        raise ValueError(f"Frequence recurrente inconnue: {frequency}")
    return add_month(day, month_step * steps)


def recurrence_dates(
    next_due: date,
    frequency: str,
    start: date,
    end: date,
) -> list[date]:
    """Project a cadence around ``next_due`` for the inclusive date range."""
    if start > end:
        return []

    if frequency == "weekly":
        step_index = (start - next_due).days // 7
    else:
        month_step = _FREQUENCY_MONTHS.get(frequency)
        if month_step is None:
            raise ValueError(f"Frequence recurrente inconnue: {frequency}")
        month_delta = (start.year - next_due.year) * 12 + start.month - next_due.month
        step_index = month_delta // month_step

    candidate = advance_recurrence(next_due, frequency, step_index)
    while candidate < start:
        step_index += 1
        candidate = advance_recurrence(next_due, frequency, step_index)

    dates: list[date] = []
    while candidate <= end:
        dates.append(candidate)
        step_index += 1
        candidate = advance_recurrence(next_due, frequency, step_index)
    return dates


async def _active_budget_series(session: AsyncSession) -> list[RecurringSeries]:
    return list(
        (
            await session.execute(
                select(RecurringSeries)
                .join(Account, RecurringSeries.account_id == Account.id)
                .where(
                    RecurringSeries.status == "active",
                    RecurringSeries.amount.is_not(None),
                    RecurringSeries.recurring_type != "transfer",
                    Account.archived.is_(False),
                )
                .order_by(RecurringSeries.id)
            )
        )
        .scalars()
        .all()
    )


async def recurring_budget_occurrences(
    session: AsyncSession,
    start: date,
    end: date,
) -> list[RecurringOccurrence]:
    """Return active, non-transfer occurrences for active accounts."""
    series = await _active_budget_series(session)

    occurrences = [
        RecurringOccurrence(
            series_id=item.id,
            due_date=due_date,
            amount=money(item.amount),
            account_id=item.account_id,
            category_id=item.category_id,
        )
        for item in series
        for due_date in recurrence_dates(item.next_due, item.frequency, start, end)
    ]
    return sorted(occurrences, key=lambda item: (item.due_date, item.series_id))


async def recurring_budget_projection(
    session: AsyncSession,
    months: int,
) -> list[RecurringProjection]:
    """Normalize active series to monthly amounts and scale them to a period."""
    if months <= 0:
        raise ValueError("La projection doit couvrir au moins un mois")

    series = await _active_budget_series(session)
    projections: list[RecurringProjection] = []
    for item in series:
        multiplier = _MONTHLY_FREQUENCY_MULTIPLIERS.get(item.frequency)
        if multiplier is None:
            raise ValueError(f"Frequence recurrente inconnue: {item.frequency}")
        projections.append(
            RecurringProjection(
                series_id=item.id,
                amount=Decimal(item.amount) * multiplier * Decimal(months),
                account_id=item.account_id,
                category_id=item.category_id,
            )
        )
    return projections
