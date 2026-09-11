from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_balances import account_balances
from ..category_budgeting import (
    ParentBudgetTooSmall,
    ensure_ancestor_budgets,
    root_budget_total,
    validate_parent_budget,
)
from ..common import add_month, local_today, money
from ..db import get_session
from ..institutions import institution_fields
from ..models import Account, Category
from ..recurring_budget import recurring_budget_occurrences
from ..schemas import (
    DEPRECATED_ACCOUNT_TYPES,
    AccountCreate,
    AccountRead,
    CategoryBreakdown,
    CategoryBudgetUpdate,
    CategoryCreate,
    CategoryRead,
    MonthlyPoint,
    Overview,
)

router = APIRouter(tags=["budget"])


@router.get("/accounts", response_model=list[AccountRead])
async def list_accounts(
    include_archived: bool = False,
    as_of: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[AccountRead]:
    statement = select(Account).order_by(Account.name)
    if not include_archived:
        statement = statement.where(Account.archived.is_(False))
    rows = (await session.execute(statement)).scalars().all()
    balances = await account_balances(session, through=as_of)
    return [
        AccountRead.model_validate(account).model_copy(
            update={
                "balance": balances.get(account.id, account.initial_balance),
                **institution_fields(
                    account.institution,
                    account.regional_entity,
                ),
            }
        )
        for account in rows
    ]


@router.post("/accounts", response_model=AccountRead, status_code=201)
async def create_account(payload: AccountCreate, session: AsyncSession = Depends(get_session)) -> AccountRead:
    if payload.type in DEPRECATED_ACCOUNT_TYPES:
        raise HTTPException(status_code=422, detail="Ce type de compte n'est plus disponible")
    data = payload.model_dump()
    data.update(
        institution_fields(
            payload.institution,
            payload.regional_entity,
        )
    )
    account = Account(**data)
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    return AccountRead.model_validate(account).model_copy(
        update={
            "balance": account.initial_balance,
            **institution_fields(
                account.institution,
                account.regional_entity,
            ),
        }
    )


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(session: AsyncSession = Depends(get_session)) -> list[CategoryRead]:
    rows = (await session.execute(select(Category).order_by(Category.kind, Category.name))).scalars().all()
    planned = await _current_month_category_plan(session)
    return [
        CategoryRead.model_validate(category).model_copy(
            update={"planned_this_month": planned.get(category.id, Decimal("0.00"))}
        )
        for category in rows
    ]


@router.post("/categories", response_model=CategoryRead, status_code=201)
async def create_category(
    payload: CategoryCreate,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    if payload.parent_id is not None:
        parent = await session.get(Category, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Categorie parente introuvable")
        if parent.archived:
            raise HTTPException(status_code=409, detail="La categorie parente est archivee")
        if parent.kind != payload.kind:
            raise HTTPException(status_code=422, detail="Le parent doit avoir le meme type")
    category = Category(**payload.model_dump())
    session.add(category)
    try:
        await session.flush()
        await ensure_ancestor_budgets(session, category.parent_id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Cette categorie existe deja") from exc
    await session.refresh(category)
    return CategoryRead.model_validate(category)


@router.patch("/categories/{category_id}/budget", response_model=CategoryRead)
async def update_category_budget(
    category_id: int,
    payload: CategoryBudgetUpdate,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")
    try:
        await validate_parent_budget(session, category_id, payload.monthly_budget)
    except ParentBudgetTooSmall as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    category.monthly_budget = payload.monthly_budget
    await session.flush()
    await ensure_ancestor_budgets(session, category.parent_id)
    await session.commit()
    await session.refresh(category)
    planned = await _current_month_category_plan(session)
    return CategoryRead.model_validate(category).model_copy(
        update={"planned_this_month": planned.get(category.id, Decimal("0.00"))}
    )


@router.get("/overview", response_model=Overview)
async def overview(
    as_of: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> Overview:
    today = as_of or local_today()
    month_start = _month_start(today)
    month_end = add_month(month_start, 1) - timedelta(days=1)
    balances = await account_balances(session, through=today)
    occurrences = await recurring_budget_occurrences(
        session,
        month_start,
        month_end,
    )
    income = sum(
        (occurrence.amount for occurrence in occurrences if occurrence.amount > 0),
        Decimal("0"),
    )
    expenses = sum(
        (-occurrence.amount for occurrence in occurrences if occurrence.amount < 0),
        Decimal("0"),
    )
    categories = (await session.execute(select(Category))).scalars().all()
    budget_total = root_budget_total(categories)
    return Overview(
        balance=money(sum(balances.values(), Decimal("0.00"))),
        income_current_month=money(income),
        expenses_current_month=money(expenses),
        net_current_month=money(income - expenses),
        budget_current_month=money(budget_total),
        budget_remaining=money(budget_total - expenses),
    )


@router.get("/stats/monthly", response_model=list[MonthlyPoint])
async def monthly_stats(
    as_of: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[MonthlyPoint]:
    today = as_of or local_today()
    first_month = _month_start(today)
    last_month = add_month(first_month, 11)
    end = add_month(last_month, 1) - timedelta(days=1)
    occurrences = await recurring_budget_occurrences(session, first_month, end)
    totals = {
        add_month(first_month, offset).strftime("%Y-%m"): [
            Decimal("0"),
            Decimal("0"),
        ]
        for offset in range(12)
    }
    for occurrence in occurrences:
        month = occurrence.due_date.strftime("%Y-%m")
        if occurrence.amount > 0:
            totals[month][0] += occurrence.amount
        elif occurrence.amount < 0:
            totals[month][1] -= occurrence.amount
    return [
        MonthlyPoint(
            month=month,
            income=money(income),
            expenses=money(expenses),
            net=money(income - expenses),
        )
        for month, (income, expenses) in totals.items()
    ]


@router.get("/stats/categories", response_model=list[CategoryBreakdown])
async def category_stats(session: AsyncSession = Depends(get_session)) -> list[CategoryBreakdown]:
    today = local_today()
    month_start = _month_start(today)
    month_end = add_month(month_start, 1) - timedelta(days=1)
    occurrences = await recurring_budget_occurrences(
        session,
        month_start,
        month_end,
    )
    spent: dict[int | None, Decimal] = {}
    for occurrence in occurrences:
        if occurrence.amount >= 0:
            continue
        spent[occurrence.category_id] = money(
            spent.get(occurrence.category_id, Decimal("0")) - occurrence.amount
        )
    categories = {
        category.id: category
        for category in (await session.execute(select(Category))).scalars().all()
    }
    breakdown = [
        CategoryBreakdown(
            category_id=category_id,
            category_name=categories[category_id].name,
            amount=amount,
            budget=categories[category_id].monthly_budget,
        )
        for category_id, amount in sorted(
            (
                (category_id, amount)
                for category_id, amount in spent.items()
                if category_id is not None and category_id in categories
            ),
            key=lambda item: item[1],
            reverse=True,
        )
    ]
    uncategorized = spent.get(None, Decimal("0"))
    if uncategorized:
        breakdown.append(
            CategoryBreakdown(
                category_id=None,
                category_name="Sans categorie",
                amount=uncategorized,
            )
        )
    return breakdown


async def _current_month_category_plan(session: AsyncSession) -> dict[int, Decimal]:
    today = local_today()
    month_start = _month_start(today)
    month_end = add_month(month_start, 1) - timedelta(days=1)
    occurrences = await recurring_budget_occurrences(
        session,
        month_start,
        month_end,
    )
    planned: dict[int, Decimal] = {}
    for occurrence in occurrences:
        if occurrence.amount >= 0 or occurrence.category_id is None:
            continue
        planned[occurrence.category_id] = money(
            planned.get(occurrence.category_id, Decimal("0")) - occurrence.amount
        )
    return planned


def _month_start(day: date) -> date:
    return day.replace(day=1)
