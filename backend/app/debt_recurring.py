"""Synchronization rules between debts and their recurring payments."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from .common import add_month, local_today, money
from .models import Debt, RecurringSeries


def recurring_amount(minimum_payment: Decimal | None) -> Decimal | None:
    if minimum_payment is None:
        return None
    return money(-abs(Decimal(minimum_payment)))


def debt_payment(amount: Decimal | None) -> Decimal | None:
    if amount is None:
        return None
    return money(abs(Decimal(amount)))


def build_debt_recurring_series(debt: Debt) -> RecurringSeries:
    if debt.account_id is None:
        raise ValueError("Un compte est requis pour créer la récurrence d'une mensualité.")
    return RecurringSeries(
        label=f"Mensualité · {debt.name}",
        account_id=debt.account_id,
        category_id=None,
        frequency="monthly",
        next_due=_next_payment_date(debt.due_date),
        amount=recurring_amount(debt.minimum_payment),
        amount_type="fixed",
        status="active",
        recurring_type="loan_payment",
        confidence=Decimal("1.00"),
    )


def _next_payment_date(final_due: date | None) -> date:
    today = local_today()
    target_day = final_due.day if final_due is not None else today.day
    candidate = date(
        today.year,
        today.month,
        min(target_day, monthrange(today.year, today.month)[1]),
    )
    if candidate >= today:
        return candidate
    next_month = add_month(today.replace(day=1), 1)
    return date(
        next_month.year,
        next_month.month,
        min(target_day, monthrange(next_month.year, next_month.month)[1]),
    )
