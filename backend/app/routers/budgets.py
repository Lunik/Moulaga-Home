"""Budget calculations for configurable cycles (envelopes, cashflow, spending)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..category_budgeting import (
    budgeted_category_ids,
    effective_parent_ids,
    root_budget_total,
)
from ..common import cycle_bounds, get_preferences, money
from ..db import get_session
from ..models import (
    Account,
    Category,
    Contribution,
    RecurringSeries,
    Transaction,
)
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
    return statement.where(
        Transaction.booked_at >= start,
        Transaction.booked_at <= end,
        Transaction.transfer_group.is_(None),
    )


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
    categories = (
        await session.execute(
            select(Category).where(Category.kind == "expense")
        )
    ).scalars().all()
    budget = root_budget_total(categories)
    uncategorized = await session.scalar(
        _in_cycle(
            select(func.count()).select_from(Transaction).where(Transaction.category_id.is_(None)),
            start,
            end,
        )
    )
    # A budget on a parent covers every transaction in its active subtree.
    covered_category_ids = budgeted_category_ids(categories)
    envelope_spent_raw = Decimal("0")
    if covered_category_ids:
        envelope_spent_raw = await session.scalar(
            select(func.coalesce(func.sum(-Transaction.amount), 0)).where(
                Transaction.amount < 0,
                Transaction.booked_at >= start,
                Transaction.booked_at <= end,
                Transaction.transfer_group.is_(None),
                Transaction.category_id.in_(covered_category_ids),
            )
        )
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
        (Decimal(row[0]) for row in recurring_rows), Decimal("0")
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
    categories = (
        await session.execute(
            select(Category)
            .where(Category.kind == "expense")
            .order_by(Category.name)
        )
    ).scalars().all()
    effective_parents = effective_parent_ids(categories)
    active_categories = [category for category in categories if not category.archived]
    spent_rows = (
        await session.execute(
            select(Transaction.category_id, func.sum(-Transaction.amount))
            .where(
                Transaction.amount < 0,
                Transaction.booked_at >= start,
                Transaction.booked_at <= end,
                Transaction.transfer_group.is_(None),
                Transaction.category_id.is_not(None),
            )
            .group_by(Transaction.category_id)
        )
    ).all()
    direct_spent_by_category = {
        category_id: money(spent)
        for category_id, spent in spent_rows
        if category_id is not None
    }
    children_by_parent: dict[int, list[tuple[int, Decimal | None]]] = {}
    for category in active_categories:
        parent_id = effective_parents.get(category.id)
        if parent_id is not None:
            children_by_parent.setdefault(parent_id, []).append(
                (category.id, category.monthly_budget)
            )

    aggregate_spent_by_category: dict[int, Decimal] = {}

    def aggregate_spent(category_id: int, visiting: set[int] | None = None) -> Decimal:
        if category_id in aggregate_spent_by_category:
            return aggregate_spent_by_category[category_id]
        current_visiting = set() if visiting is None else set(visiting)
        if category_id in current_visiting:
            return Decimal("0")
        current_visiting.add(category_id)
        total = direct_spent_by_category.get(category_id, Decimal("0"))
        for child_id, _child_budget in children_by_parent.get(category_id, []):
            total += aggregate_spent(child_id, current_visiting)
        aggregate_spent_by_category[category_id] = money(total)
        return aggregate_spent_by_category[category_id]

    result = []
    for category in active_categories:
        budget_amount = (
            money(category.monthly_budget)
            if category.monthly_budget is not None
            else None
        )
        direct_spent_amount = direct_spent_by_category.get(
            category.id, Decimal("0")
        )
        spent_amount = aggregate_spent(category.id)
        child_budgets = children_by_parent.get(category.id)
        children_budget = money(
            sum(
                (
                    Decimal(child_budget)
                    for _child_id, child_budget in child_budgets or []
                    if child_budget is not None
                ),
                Decimal("0"),
            )
        )
        remainder_budget = None
        if (
            child_budgets
            and budget_amount is not None
            and budget_amount > children_budget
        ):
            remainder_budget = money(budget_amount - children_budget)
        result.append(
            EnvelopeRead(
                category_id=category.id,
                category_name=category.name,
                color=category.color,
                parent_id=effective_parents.get(category.id),
                budget=budget_amount,
                direct_spent=direct_spent_amount,
                spent=spent_amount,
                remaining=money(budget_amount - spent_amount)
                if budget_amount is not None
                else None,
                children_budget=children_budget,
                remainder_budget=remainder_budget,
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
            .where(
                Transaction.booked_at >= start,
                Transaction.booked_at <= end,
                Transaction.transfer_group.is_(None),
            )
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
