"""Budget calculations for configurable cycles (envelopes, cashflow, spending)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common import cycle_bounds, get_preferences, money
from ..db import get_session
from ..models import Account, Category, Contribution, RecurringSeries, Transaction
from ..schemas import (
    BudgetCycleOverview,
    CashflowFlow,
    CycleBounds,
    EnvelopeRead,
    HierarchicalSpendingNode,
)

router = APIRouter(tags=["budget-cycles"], prefix="/budget")


async def _bounds(session: AsyncSession, on: date | None) -> tuple[date, date, int]:
    prefs = await get_preferences(session)
    reference = on or date.today()
    start, end = cycle_bounds(reference, prefs.budget_cycle_start_day)
    return start, end, prefs.budget_cycle_start_day


async def _period_bounds(
    session: AsyncSession, on: date | None, period: str
) -> tuple[date, date, int]:
    """Resolve the analysis window: the configurable cycle or the civil year."""
    if period == "year":
        reference = on or date.today()
        prefs = await get_preferences(session)
        return date(reference.year, 1, 1), date(reference.year, 12, 31), prefs.budget_cycle_start_day
    return await _bounds(session, on)


def _in_cycle(statement: Select, start: date, end: date) -> Select:
    return statement.where(Transaction.booked_at >= start, Transaction.booked_at <= end)


@router.get("/overview", response_model=BudgetCycleOverview)
async def cycle_overview(
    on: date | None = None, session: AsyncSession = Depends(get_session)
) -> BudgetCycleOverview:
    start, end, start_day = await _bounds(session, on)
    income = await session.scalar(
        _in_cycle(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.amount > 0),
            start,
            end,
        )
    )
    expenses = await session.scalar(
        _in_cycle(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.amount < 0),
            start,
            end,
        )
    )
    budget = await session.scalar(
        select(func.coalesce(func.sum(Category.monthly_budget), 0)).where(
            Category.kind == "expense", Category.archived.is_(False)
        )
    )
    uncategorized = await session.scalar(
        _in_cycle(
            select(func.count()).select_from(Transaction).where(Transaction.category_id.is_(None)),
            start,
            end,
        )
    )
    # Envelope spending: expenses booked in-cycle against budgeted expense categories.
    envelope_spent_raw = await session.scalar(
        select(func.coalesce(func.sum(-Transaction.amount), 0))
        .select_from(Transaction)
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.amount < 0,
            Transaction.booked_at >= start,
            Transaction.booked_at <= end,
            Category.kind == "expense",
            Category.archived.is_(False),
            Category.monthly_budget.is_not(None),
        )
    )
    # Upcoming recurring items whose next occurrence falls inside the cycle.
    recurring_rows = (
        await session.execute(
            select(RecurringSeries.amount).where(
                RecurringSeries.status == "active",
                RecurringSeries.next_due >= start,
                RecurringSeries.next_due <= end,
                RecurringSeries.amount.is_not(None),
            )
        )
    ).all()
    upcoming_recurring_amount = sum(
        (abs(Decimal(row[0])) for row in recurring_rows), Decimal("0")
    )
    upcoming_recurring_count = len(recurring_rows)
    # Savings contributions recorded in-cycle (kept separate from expense flows).
    savings = await session.scalar(
        select(func.coalesce(func.sum(Contribution.amount), 0)).where(
            Contribution.occurred_on >= start, Contribution.occurred_on <= end
        )
    )
    income_amount = money(income)
    expenses_abs = money(abs(Decimal(expenses or 0)))
    budget_total = money(budget)
    envelope_spent = money(envelope_spent_raw)
    return BudgetCycleOverview(
        cycle=CycleBounds(start=start, end=end, start_day=start_day),
        income=income_amount,
        expenses=expenses_abs,
        net=money(income_amount - expenses_abs),
        budget_total=budget_total,
        budget_remaining=money(budget_total - expenses_abs),
        uncategorized_count=int(uncategorized or 0),
        envelope_spent=envelope_spent,
        envelope_remaining=money(budget_total - envelope_spent),
        upcoming_recurring_amount=money(upcoming_recurring_amount),
        upcoming_recurring_count=upcoming_recurring_count,
        savings_contributions=money(savings),
    )


@router.get("/envelopes", response_model=list[EnvelopeRead])
async def envelopes(
    on: date | None = None, session: AsyncSession = Depends(get_session)
) -> list[EnvelopeRead]:
    start, end, _ = await _bounds(session, on)
    spent_expr = func.coalesce(
        func.sum(case((Transaction.amount < 0, -Transaction.amount), else_=0)), 0
    )
    rows = (
        await session.execute(
            select(Category.id, Category.name, Category.color, Category.monthly_budget, spent_expr)
            .outerjoin(
                Transaction,
                (Transaction.category_id == Category.id)
                & (Transaction.booked_at >= start)
                & (Transaction.booked_at <= end),
            )
            .where(
                Category.kind == "expense",
                Category.archived.is_(False),
                Category.monthly_budget.is_not(None),
            )
            .group_by(Category.id)
            .order_by(Category.name)
        )
    ).all()
    result = []
    for cat_id, name, color, budget, spent in rows:
        budget_amount = money(budget)
        spent_amount = money(spent)
        result.append(
            EnvelopeRead(
                category_id=cat_id,
                category_name=name,
                color=color,
                budget=budget_amount,
                spent=spent_amount,
                remaining=money(budget_amount - spent_amount),
            )
        )
    return result


@router.get("/cashflow", response_model=list[CashflowFlow])
async def cashflow(
    on: date | None = None,
    by: str = Query(default="category", pattern="^(category|source)$"),
    period: str = Query(default="cycle", pattern="^(cycle|year)$"),
    session: AsyncSession = Depends(get_session),
) -> list[CashflowFlow]:
    start, end, _ = await _period_bounds(session, on, period)
    inflow = func.coalesce(func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)), 0)
    outflow = func.coalesce(
        func.sum(case((Transaction.amount < 0, -Transaction.amount), else_=0)), 0
    )

    if by == "source":
        rows = (
            await session.execute(
                _in_cycle(
                    select(Account.id, Account.name, inflow, outflow).join(
                        Transaction, Transaction.account_id == Account.id
                    ),
                    start,
                    end,
                )
                .group_by(Account.id)
                .order_by(Account.name)
            )
        ).all()
        return [
            CashflowFlow(
                key=f"account:{row[0]}",
                label=row[1],
                inflow=money(row[2]),
                outflow=money(row[3]),
                net=money(Decimal(row[2] or 0) - Decimal(row[3] or 0)),
            )
            for row in rows
        ]

    rows = (
        await session.execute(
            select(Category.id, Category.name, inflow, outflow)
            .select_from(Transaction)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(Transaction.booked_at >= start, Transaction.booked_at <= end)
            .group_by(Category.id)
            .order_by(Category.name)
        )
    ).all()
    flows = []
    for cat_id, name, inflow_v, outflow_v in rows:
        flows.append(
            CashflowFlow(
                key=f"category:{cat_id}" if cat_id is not None else "category:none",
                label=name or "Sans categorie",
                inflow=money(inflow_v),
                outflow=money(outflow_v),
                net=money(Decimal(inflow_v or 0) - Decimal(outflow_v or 0)),
            )
        )
    return flows


@router.get("/spending", response_model=list[HierarchicalSpendingNode])
async def hierarchical_spending(
    on: date | None = None,
    period: str = Query(default="cycle", pattern="^(cycle|year)$"),
    session: AsyncSession = Depends(get_session),
) -> list[HierarchicalSpendingNode]:
    start, end, _ = await _period_bounds(session, on, period)
    rows = (
        await session.execute(
            _in_cycle(
                select(
                    Transaction.category_id,
                    func.sum(-Transaction.amount),
                    func.count(),
                ).where(Transaction.amount < 0),
                start,
                end,
            ).group_by(Transaction.category_id)
        )
    ).all()
    spent = {row[0]: (money(row[1]), int(row[2] or 0)) for row in rows}

    categories = (
        await session.execute(select(Category).where(Category.kind == "expense"))
    ).scalars().all()
    by_parent: dict[int | None, list[Category]] = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    def build(category: Category) -> HierarchicalSpendingNode:
        children = [build(child) for child in by_parent.get(category.id, [])]
        own_amount, own_count = spent.get(category.id, (Decimal("0.00"), 0))
        total = own_amount + sum((child.amount for child in children), Decimal("0.00"))
        total_count = own_count + sum(child.transaction_count for child in children)
        return HierarchicalSpendingNode(
            category_id=category.id,
            category_name=category.name,
            amount=money(total),
            transaction_count=total_count,
            children=sorted(children, key=lambda node: node.amount, reverse=True),
        )

    roots = [build(category) for category in by_parent.get(None, [])]
    nodes = sorted(roots, key=lambda node: node.amount, reverse=True)

    uncategorized = spent.get(None)
    if uncategorized and (uncategorized[0] > 0 or uncategorized[1] > 0):
        nodes.append(
            HierarchicalSpendingNode(
                category_id=None,
                category_name="Sans categorie",
                amount=uncategorized[0],
                transaction_count=uncategorized[1],
            )
        )
    return nodes
