from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .common import money
from .models import Category


class ParentBudgetTooSmall(ValueError):
    def __init__(self, required_budget: Decimal) -> None:
        self.required_budget = money(required_budget)
        super().__init__(
            f"Le plafond doit etre au moins egal a {self.required_budget}"
        )


async def active_children_budget(
    session: AsyncSession,
    category_id: int,
) -> Decimal:
    categories = (await session.execute(select(Category))).scalars().all()
    effective_parents = effective_parent_ids(categories)
    return money(
        sum(
            (
                Decimal(category.monthly_budget)
                for category in categories
                if (
                    not category.archived
                    and effective_parents.get(category.id) == category_id
                    and category.monthly_budget is not None
                )
            ),
            Decimal("0"),
        )
    )


async def validate_parent_budget(
    session: AsyncSession,
    category_id: int,
    proposed_budget: Decimal | None,
) -> None:
    children_budget = await active_children_budget(session, category_id)
    if children_budget <= 0:
        return
    if proposed_budget is None or money(proposed_budget) < children_budget:
        raise ParentBudgetTooSmall(children_budget)


async def ensure_ancestor_budgets(
    session: AsyncSession,
    parent_id: int | None,
) -> None:
    current_id = parent_id
    visited: set[int] = set()
    while current_id is not None and current_id not in visited:
        visited.add(current_id)
        parent = await session.get(Category, current_id)
        if parent is None:
            return
        children_budget = await active_children_budget(session, parent.id)
        current_budget = money(parent.monthly_budget or 0)
        if children_budget > current_budget:
            parent.monthly_budget = children_budget
            await session.flush()
        current_id = parent.parent_id


async def synchronize_parent_budgets(session: AsyncSession) -> None:
    categories = (
        await session.execute(
            select(Category).where(Category.archived.is_(False))
        )
    ).scalars().all()
    parent_ids = {category.parent_id for category in categories if category.parent_id}
    for parent_id in parent_ids:
        await ensure_ancestor_budgets(session, parent_id)


def root_expense_categories(categories: list[Category]) -> list[Category]:
    active = {
        category.id: category
        for category in categories
        if category.kind == "expense" and not category.archived
    }
    effective_parents = effective_parent_ids(categories)
    return [
        category
        for category in active.values()
        if effective_parents.get(category.id) is None
    ]


def effective_parent_ids(categories: list[Category]) -> dict[int, int | None]:
    by_id = {category.id: category for category in categories}
    result: dict[int, int | None] = {}
    for category in categories:
        if category.archived:
            continue
        parent_id = category.parent_id
        visited = {category.id}
        while parent_id is not None:
            if parent_id in visited:
                parent_id = None
                break
            visited.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                parent_id = None
                break
            if not parent.archived:
                break
            parent_id = parent.parent_id
        result[category.id] = parent_id
    return result


def root_budget_total(categories: list[Category]) -> Decimal:
    return money(
        sum(
            (
                Decimal(category.monthly_budget)
                for category in root_expense_categories(categories)
                if category.monthly_budget is not None
            ),
            Decimal("0"),
        )
    )


def budgeted_category_ids(categories: list[Category]) -> set[int]:
    active = {
        category.id: category
        for category in categories
        if category.kind == "expense" and not category.archived
    }
    effective_parents = effective_parent_ids(categories)
    children: dict[int, list[int]] = {}
    for category in active.values():
        parent_id = effective_parents.get(category.id)
        if parent_id in active:
            children.setdefault(parent_id, []).append(category.id)

    result: set[int] = set()

    def add_subtree(category_id: int) -> None:
        if category_id in result:
            return
        result.add(category_id)
        for child_id in children.get(category_id, []):
            add_subtree(child_id)

    for root in root_expense_categories(categories):
        if root.monthly_budget is not None:
            add_subtree(root.id)
    return result
