"""Budget calculations for configurable cycles (envelopes, cashflow, spending)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
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
)
from ..recurring_budget import recurring_budget_occurrences, recurring_budget_projection
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


@router.get("/overview", response_model=BudgetCycleOverview)
async def cycle_overview(
    on: date | None = None, session: AsyncSession = Depends(get_session)
) -> BudgetCycleOverview:
    start, end, start_day = await _bounds(session, on)
    occurrences = await recurring_budget_occurrences(session, start, end)
    income = sum(
        (occurrence.amount for occurrence in occurrences if occurrence.amount > 0),
        Decimal("0"),
    )
    expenses = sum(
        (-occurrence.amount for occurrence in occurrences if occurrence.amount < 0),
        Decimal("0"),
    )
    categories = (
        await session.execute(
            select(Category).where(Category.kind == "expense")
        )
    ).scalars().all()
    budget = root_budget_total(categories)
    # A budget on a parent covers every recurring expense in its active subtree.
    covered_category_ids = budgeted_category_ids(categories)
    envelope_planned_raw = sum(
        (
            -occurrence.amount
            for occurrence in occurrences
            if occurrence.amount < 0
            and occurrence.category_id in covered_category_ids
        ),
        Decimal("0"),
    )
    recurring_amount = sum(
        (occurrence.amount for occurrence in occurrences),
        Decimal("0"),
    )
    # Savings contributions recorded in-cycle (kept separate from expense flows).
    savings = await session.scalar(
        select(func.coalesce(func.sum(Contribution.amount), 0)).where(
            Contribution.occurred_on >= start, Contribution.occurred_on <= end
        )
    )
    income_amount = money(income)
    expenses_abs = money(expenses)
    budget_total = money(budget)
    envelope_planned = money(envelope_planned_raw)
    return BudgetCycleOverview(
        cycle=CycleBounds(start=start, end=end, start_day=start_day),
        income=income_amount,
        expenses=expenses_abs,
        net=money(income_amount - expenses_abs),
        budget_total=budget_total,
        budget_remaining=money(budget_total - expenses_abs),
        envelope_planned=envelope_planned,
        envelope_available=money(budget_total - envelope_planned),
        upcoming_recurring_amount=money(recurring_amount),
        upcoming_recurring_count=len(occurrences),
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
    occurrences = await recurring_budget_occurrences(session, start, end)
    direct_planned_by_category: dict[int, Decimal] = {}
    for occurrence in occurrences:
        if occurrence.amount >= 0 or occurrence.category_id is None:
            continue
        direct_planned_by_category[occurrence.category_id] = money(
            direct_planned_by_category.get(occurrence.category_id, Decimal("0"))
            - occurrence.amount
        )
    children_by_parent: dict[int, list[tuple[int, Decimal | None]]] = {}
    for category in active_categories:
        parent_id = effective_parents.get(category.id)
        if parent_id is not None:
            children_by_parent.setdefault(parent_id, []).append(
                (category.id, category.monthly_budget)
            )

    aggregate_planned_by_category: dict[int, Decimal] = {}

    def aggregate_planned(category_id: int, visiting: set[int] | None = None) -> Decimal:
        if category_id in aggregate_planned_by_category:
            return aggregate_planned_by_category[category_id]
        current_visiting = set() if visiting is None else set(visiting)
        if category_id in current_visiting:
            return Decimal("0")
        current_visiting.add(category_id)
        total = direct_planned_by_category.get(category_id, Decimal("0"))
        for child_id, _child_budget in children_by_parent.get(category_id, []):
            total += aggregate_planned(child_id, current_visiting)
        aggregate_planned_by_category[category_id] = money(total)
        return aggregate_planned_by_category[category_id]

    result = []
    for category in active_categories:
        budget_amount = (
            money(category.monthly_budget)
            if category.monthly_budget is not None
            else None
        )
        direct_planned_amount = direct_planned_by_category.get(
            category.id, Decimal("0.00")
        )
        planned_amount = aggregate_planned(category.id)
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
                direct_planned=direct_planned_amount,
                planned=planned_amount,
                available=money(budget_amount - planned_amount)
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
    months: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[CashflowFlow]:
    if months is not None and months not in {1, 3, 6, 12}:
        raise HTTPException(
            status_code=422,
            detail="La projection doit couvrir 1, 3, 6 ou 12 mois",
        )
    if months is None:
        start, end, _ = await _period_bounds(session, on, period)
        entries = await recurring_budget_occurrences(session, start, end)
    else:
        entries = await recurring_budget_projection(session, months)

    if by == "source":
        accounts = {
            account.id: account.name
            for account in (await session.execute(select(Account))).scalars().all()
        }
        totals: dict[int, tuple[Decimal, Decimal]] = {}
        for occurrence in entries:
            income, expenses = totals.get(
                occurrence.account_id,
                (Decimal("0"), Decimal("0")),
            )
            if occurrence.amount > 0:
                income += occurrence.amount
            elif occurrence.amount < 0:
                expenses -= occurrence.amount
            totals[occurrence.account_id] = income, expenses
        return [
            CashflowFlow(
                key=f"account:{account_id}",
                label=accounts.get(account_id, ""),
                inflow=money(income),
                outflow=money(expenses),
                net=money(income - expenses),
            )
            for account_id, (income, expenses) in sorted(
                totals.items(),
                key=lambda item: accounts.get(item[0], "").casefold(),
            )
        ]

    categories = {
        category.id: category.name
        for category in (await session.execute(select(Category))).scalars().all()
    }
    totals_by_category: dict[int | None, tuple[Decimal, Decimal]] = {}
    for occurrence in entries:
        income, expenses = totals_by_category.get(
            occurrence.category_id,
            (Decimal("0"), Decimal("0")),
        )
        if occurrence.amount > 0:
            income += occurrence.amount
        elif occurrence.amount < 0:
            expenses -= occurrence.amount
        totals_by_category[occurrence.category_id] = income, expenses
    return [
        CashflowFlow(
            key=f"category:{category_id}" if category_id is not None else "category:none",
            label=categories.get(category_id, "Sans categorie"),
            inflow=money(income),
            outflow=money(expenses),
            net=money(income - expenses),
        )
        for category_id, (income, expenses) in sorted(
            totals_by_category.items(),
            key=lambda item: categories.get(item[0], "Sans categorie").casefold(),
        )
    ]


@router.get("/spending", response_model=list[HierarchicalSpendingNode])
async def hierarchical_spending(
    on: date | None = None,
    period: str = Query(default="cycle", pattern="^(cycle|year)$"),
    session: AsyncSession = Depends(get_session),
) -> list[HierarchicalSpendingNode]:
    start, end, _ = await _period_bounds(session, on, period)
    occurrences = await recurring_budget_occurrences(session, start, end)
    planned: dict[int | None, tuple[Decimal, int]] = {}
    for occurrence in occurrences:
        if occurrence.amount >= 0:
            continue
        amount, count = planned.get(
            occurrence.category_id,
            (Decimal("0"), 0),
        )
        planned[occurrence.category_id] = (
            money(amount - occurrence.amount),
            count + 1,
        )

    categories = (
        await session.execute(select(Category).where(Category.kind == "expense"))
    ).scalars().all()
    by_parent: dict[int | None, list[Category]] = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    def build(category: Category) -> HierarchicalSpendingNode:
        children = [build(child) for child in by_parent.get(category.id, [])]
        own_amount, own_count = planned.get(category.id, (Decimal("0.00"), 0))
        total = own_amount + sum((child.amount for child in children), Decimal("0.00"))
        total_count = own_count + sum(child.occurrence_count for child in children)
        return HierarchicalSpendingNode(
            category_id=category.id,
            category_name=category.name,
            amount=money(total),
            occurrence_count=total_count,
            children=sorted(children, key=lambda node: node.amount, reverse=True),
        )

    roots = [build(category) for category in by_parent.get(None, [])]
    nodes = sorted(roots, key=lambda node: node.amount, reverse=True)

    uncategorized = planned.get(None)
    if uncategorized and (uncategorized[0] > 0 or uncategorized[1] > 0):
        nodes.append(
            HierarchicalSpendingNode(
                category_id=None,
                category_name="Sans categorie",
                amount=uncategorized[0],
                occurrence_count=uncategorized[1],
            )
        )
    return nodes
