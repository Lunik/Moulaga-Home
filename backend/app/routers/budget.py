from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..account_access import require_account
from ..account_balances import account_balances
from ..category_budgeting import (
    ParentBudgetTooSmall,
    ensure_ancestor_budgets,
    root_budget_total,
    validate_parent_budget,
)
from ..common import add_month, local_today, money
from ..db import get_session
from ..models import Account, Category, Transaction
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
    TransactionCount,
    TransactionCreate,
    TransactionRead,
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
    transaction_counts = await _account_transaction_counts(session)
    return [
        AccountRead.model_validate(account).model_copy(
            update={
                "balance": balances.get(account.id, account.initial_balance),
                "transaction_count": transaction_counts.get(account.id, 0),
            }
        )
        for account in rows
    ]


@router.post("/accounts", response_model=AccountRead, status_code=201)
async def create_account(payload: AccountCreate, session: AsyncSession = Depends(get_session)) -> AccountRead:
    if payload.type in DEPRECATED_ACCOUNT_TYPES:
        raise HTTPException(status_code=422, detail="Ce type de compte n'est plus disponible")
    account = Account(**payload.model_dump())
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    return AccountRead.model_validate(account).model_copy(update={"balance": account.initial_balance})


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(session: AsyncSession = Depends(get_session)) -> list[CategoryRead]:
    rows = (await session.execute(select(Category).order_by(Category.kind, Category.name))).scalars().all()
    spent = await _current_month_category_spend(session)
    return [
        CategoryRead.model_validate(category).model_copy(
            update={"spent_this_month": spent.get(category.id, Decimal("0.00"))}
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
    spent = await _current_month_category_spend(session)
    return CategoryRead.model_validate(category).model_copy(
        update={"spent_this_month": spent.get(category.id, Decimal("0.00"))}
    )


@router.get("/transactions", response_model=list[TransactionRead])
async def list_transactions(
    start: date | None = None,
    end: date | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[TransactionRead]:
    statement = (
        _transaction_query()
        .order_by(Transaction.booked_at.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    statement = _apply_transaction_filters(
        statement, start, end, account_id, category_id, uncategorized, search
    )
    rows = (await session.execute(statement)).scalars().all()
    return [_transaction_read(row) for row in rows]


@router.get("/transactions/count", response_model=TransactionCount)
async def count_transactions(
    start: date | None = None,
    end: date | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    search: str | None = Query(default=None, max_length=120),
    session: AsyncSession = Depends(get_session),
) -> TransactionCount:
    statement = select(func.count()).select_from(Transaction)
    statement = _apply_transaction_filters(
        statement, start, end, account_id, category_id, uncategorized, search
    )
    total = await session.scalar(statement)
    return TransactionCount(count=int(total or 0))


@router.post("/transactions", response_model=TransactionRead, status_code=201)
async def create_transaction(
    payload: TransactionCreate, session: AsyncSession = Depends(get_session)
) -> TransactionRead:
    await require_account(session, payload.account_id, writable=True)
    if payload.category_id is not None:
        await _require_category(session, payload.category_id)
    transaction = Transaction(**payload.model_dump())
    session.add(transaction)
    await session.commit()
    statement = _transaction_query().where(Transaction.id == transaction.id)
    created = (await session.execute(statement)).scalar_one()
    return _transaction_read(created)


@router.get("/overview", response_model=Overview)
async def overview(
    as_of: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> Overview:
    today = as_of or local_today()
    month_start = _month_start(today)
    balances = await account_balances(session, through=today)
    income = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.booked_at >= month_start,
            Transaction.booked_at <= today,
            Transaction.amount > 0,
            Transaction.transfer_group.is_(None),
        )
    )
    expenses = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.booked_at >= month_start,
            Transaction.booked_at <= today,
            Transaction.amount < 0,
            Transaction.transfer_group.is_(None),
        )
    )
    categories = (await session.execute(select(Category))).scalars().all()
    uncategorized = await session.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.booked_at >= month_start,
            Transaction.booked_at <= today,
            Transaction.category_id.is_(None),
            Transaction.transfer_group.is_(None),
            Transaction.account_id.in_(
                select(Account.id).where(Account.archived.is_(False))
            ),
        )
    )
    expenses_abs = abs(Decimal(expenses or 0))
    budget_total = root_budget_total(categories)
    return Overview(
        balance=money(sum(balances.values(), Decimal("0.00"))),
        income_current_month=money(income),
        expenses_current_month=money(expenses_abs),
        net_current_month=money(Decimal(income or 0) + Decimal(expenses or 0)),
        budget_current_month=money(budget_total),
        budget_remaining=money(budget_total - expenses_abs),
        uncategorized_count=int(uncategorized or 0),
    )


@router.get("/stats/monthly", response_model=list[MonthlyPoint])
async def monthly_stats(
    as_of: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[MonthlyPoint]:
    today = as_of or local_today()
    current_month_start = _month_start(today)
    oldest_month_start = add_month(current_month_start, -11)
    month_expr = func.strftime("%Y-%m", Transaction.booked_at)
    income_expr = func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0))
    expense_expr = func.sum(case((Transaction.amount < 0, Transaction.amount), else_=0))
    rows = (
        await session.execute(
            select(month_expr, income_expr, expense_expr)
            .where(
                Transaction.transfer_group.is_(None),
                Transaction.booked_at >= oldest_month_start,
                Transaction.booked_at <= today,
            )
            .group_by(month_expr)
            .order_by(month_expr.desc())
            .limit(12)
        )
    ).all()
    points = [
        MonthlyPoint(
            month=row[0],
            income=Decimal(row[1] or 0),
            expenses=abs(Decimal(row[2] or 0)),
            net=Decimal(row[1] or 0) + Decimal(row[2] or 0),
        )
        for row in rows
    ]
    return list(reversed(points))


@router.get("/stats/categories", response_model=list[CategoryBreakdown])
async def category_stats(session: AsyncSession = Depends(get_session)) -> list[CategoryBreakdown]:
    today = local_today()
    month_start = _month_start(today)
    rows = (
        await session.execute(
            select(Category.id, Category.name, func.sum(Transaction.amount), Category.monthly_budget)
            .join(Transaction, Transaction.category_id == Category.id)
            .where(
                Transaction.booked_at >= month_start,
                Transaction.booked_at <= today,
                Transaction.amount < 0,
                Transaction.transfer_group.is_(None),
            )
            .group_by(Category.id)
            .order_by(func.sum(Transaction.amount))
        )
    ).all()
    uncategorized = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.booked_at >= month_start,
            Transaction.booked_at <= today,
            Transaction.amount < 0,
            Transaction.category_id.is_(None),
            Transaction.transfer_group.is_(None),
        )
    )
    breakdown = [
        CategoryBreakdown(
            category_id=row[0],
            category_name=row[1],
            amount=abs(Decimal(row[2] or 0)),
            budget=row[3],
        )
        for row in rows
    ]
    if uncategorized:
        breakdown.append(
            CategoryBreakdown(
                category_id=None,
                category_name="Sans categorie",
                amount=abs(Decimal(uncategorized)),
            )
        )
    return breakdown


def _apply_transaction_filters(
    statement: Select[tuple[Transaction]],
    start: date | None,
    end: date | None,
    account_id: int | None,
    category_id: int | None,
    uncategorized: bool,
    search: str | None,
) -> Select[tuple[Transaction]]:
    if start:
        statement = statement.where(Transaction.booked_at >= start)
    if end:
        statement = statement.where(Transaction.booked_at <= end)
    if account_id:
        statement = statement.where(Transaction.account_id == account_id)
    if uncategorized:
        statement = statement.where(
            Transaction.category_id.is_(None),
            Transaction.transfer_group.is_(None),
            Transaction.account_id.in_(
                select(Account.id).where(Account.archived.is_(False))
            ),
        )
    elif category_id:
        statement = statement.where(Transaction.category_id == category_id)
    if search:
        like = f"%{search.strip()}%"
        statement = statement.where(or_(Transaction.description.ilike(like), Transaction.notes.ilike(like)))
    return statement


def _transaction_query() -> Select[tuple[Transaction]]:
    return select(Transaction).options(
        selectinload(Transaction.account),
        selectinload(Transaction.category),
        selectinload(Transaction.attachments),
    )


def _transaction_read(transaction: Transaction) -> TransactionRead:
    return TransactionRead.model_validate(transaction).model_copy(
        update={
            "account_name": transaction.account.name,
            "category_name": transaction.category.name if transaction.category else None,
            "category_kind": transaction.category.kind if transaction.category else None,
            "attachment_count": len(transaction.attachments),
        }
    )


async def _require_category(session: AsyncSession, category_id: int) -> None:
    if await session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")


async def _account_transaction_counts(session: AsyncSession) -> dict[int, int]:
    rows = (
        await session.execute(
            select(Transaction.account_id, func.count(Transaction.id)).group_by(
                Transaction.account_id
            )
        )
    ).all()
    return {row[0]: int(row[1]) for row in rows}


async def _current_month_category_spend(session: AsyncSession) -> dict[int, Decimal]:
    today = local_today()
    month_start = _month_start(today)
    rows = (
        await session.execute(
            select(Transaction.category_id, func.sum(Transaction.amount))
            .where(
                Transaction.booked_at >= month_start,
                Transaction.booked_at <= today,
                Transaction.amount < 0,
                Transaction.transfer_group.is_(None),
            )
            .group_by(Transaction.category_id)
        )
    ).all()
    return {row[0]: abs(Decimal(row[1] or 0)) for row in rows if row[0] is not None}


def _month_start(day: date) -> date:
    return day.replace(day=1)
