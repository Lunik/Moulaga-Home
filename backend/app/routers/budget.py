from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import (
    account_owner,
    account_owner_member_column,
    require_active_profile,
)
from ..account_balances import account_balance_shares, account_missing_snapshot_periods
from ..category_budgeting import (
    ParentBudgetTooSmall,
    ensure_ancestor_budgets,
    root_budget_total,
    validate_parent_budget,
)
from ..common import add_month, local_today, money
from ..db import get_session
from ..institutions import institution_fields
from ..models import Account, AccountOwner, Category, HouseholdMember
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


def _with_account_share(
    account_read: AccountRead,
    *,
    total_balance: Decimal,
    profile_share: Decimal,
    owner_ids: tuple[int, ...],
) -> AccountRead:
    updates: dict[str, object] = {"balance": profile_share}
    available = type(account_read).model_fields
    for name, value in (
        ("total_balance", total_balance),
        ("profile_share", profile_share),
        ("owner_profile_ids", list(owner_ids)),
    ):
        if name in available:
            updates[name] = value
    return account_read.model_copy(update=updates)


@router.get("/accounts", response_model=list[AccountRead])
async def list_accounts(
    include_archived: bool = False,
    as_of: date | None = None,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[AccountRead]:
    statement = (
        select(Account)
        .join(AccountOwner, AccountOwner.account_id == Account.id)
        .where(account_owner_member_column() == profile.id)
        .order_by(Account.name)
    )
    if not include_archived:
        statement = statement.where(Account.archived.is_(False))
    rows = (await session.execute(statement)).scalars().all()
    shares = await account_balance_shares(session, profile.id, through=as_of)
    missing_periods = await account_missing_snapshot_periods(
        session,
        through=as_of,
        account_ids={account.id for account in rows if not account.archived},
    )
    return [
        _with_account_share(
            AccountRead.model_validate(account).model_copy(
            update={
                "missing_snapshot_periods": missing_periods.get(account.id, []),
                **institution_fields(
                    account.institution,
                    account.regional_entity,
                ),
            }
            ),
            total_balance=shares[account.id].total,
            profile_share=shares[account.id].profile_share,
            owner_ids=shares[account.id].owner_ids,
        )
        for account in rows
    ]


@router.post("/accounts", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    if payload.type in DEPRECATED_ACCOUNT_TYPES:
        raise HTTPException(status_code=422, detail="Ce type de compte n'est plus disponible")
    owner_ids = sorted(
        set(getattr(payload, "owner_profile_ids", None) or [profile.id])
    )
    if profile.id not in owner_ids:
        raise HTTPException(
            status_code=422,
            detail="Le profil actif doit rester proprietaire du compte",
        )
    owners = list(
        (
            await session.execute(
                select(HouseholdMember).where(
                    HouseholdMember.id.in_(owner_ids),
                    HouseholdMember.active.is_(True),
                )
            )
        ).scalars().all()
    )
    if len(owners) != len(owner_ids):
        raise HTTPException(status_code=422, detail="Un profil proprietaire est introuvable")
    if (
        len({owner.household_id for owner in owners}) != 1
        or owners[0].household_id != profile.household_id
    ):
        raise HTTPException(
            status_code=422,
            detail="Les proprietaires doivent appartenir au meme foyer",
        )
    data = payload.model_dump()
    data.pop("owner_profile_ids", None)
    data.update(
        institution_fields(
            payload.institution,
            payload.regional_entity,
        )
    )
    account = Account(**data)
    session.add(account)
    try:
        await session.flush()
        # The compatibility migration installs a default-owner trigger for
        # legacy writers. Replace that fallback with the requested owners.
        await session.execute(
            sql_delete(AccountOwner).where(AccountOwner.account_id == account.id)
        )
        session.add_all(
            [
                account_owner(account.id, owner_id)
                for owner_id in owner_ids
            ]
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    share = (await account_balance_shares(session, profile.id, account_ids={account.id}))[
        account.id
    ]
    return _with_account_share(
        AccountRead.model_validate(account).model_copy(
            update={
            **institution_fields(
                account.institution,
                account.regional_entity,
            ),
            }
        ),
        total_balance=share.total,
        profile_share=share.profile_share,
        owner_ids=share.owner_ids,
    )


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[CategoryRead]:
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
    profile: HouseholdMember = Depends(require_active_profile),
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
    profile: HouseholdMember = Depends(require_active_profile),
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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> Overview:
    today = as_of or local_today()
    month_start = _month_start(today)
    month_end = add_month(month_start, 1) - timedelta(days=1)
    balances = await account_balance_shares(session, profile.id, through=today)
    occurrences = await recurring_budget_occurrences(
        session,
        month_start,
        month_end,
        profile_id=profile.id,
    )
    household_occurrences = await recurring_budget_occurrences(
        session,
        month_start,
        month_end,
    )
    income = sum(
        (
            occurrence.profile_share or Decimal("0")
            for occurrence in occurrences
            if occurrence.amount > 0
        ),
        Decimal("0"),
    )
    expenses = sum(
        (
            -(occurrence.profile_share or Decimal("0"))
            for occurrence in occurrences
            if occurrence.amount < 0
        ),
        Decimal("0"),
    )
    household_expenses = sum(
        (
            -occurrence.amount
            for occurrence in household_occurrences
            if occurrence.amount < 0
        ),
        Decimal("0"),
    )
    categories = (await session.execute(select(Category))).scalars().all()
    budget_total = root_budget_total(categories)
    return Overview(
        balance=money(
            sum((balance.profile_share for balance in balances.values()), Decimal("0.00"))
        ),
        income_current_month=money(income),
        expenses_current_month=money(expenses),
        net_current_month=money(income - expenses),
        budget_current_month=money(budget_total),
        budget_remaining=money(budget_total - household_expenses),
    )


@router.get("/stats/monthly", response_model=list[MonthlyPoint])
async def monthly_stats(
    as_of: date | None = None,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[MonthlyPoint]:
    today = as_of or local_today()
    first_month = _month_start(today)
    last_month = add_month(first_month, 11)
    end = add_month(last_month, 1) - timedelta(days=1)
    occurrences = await recurring_budget_occurrences(
        session,
        first_month,
        end,
        profile_id=profile.id,
    )
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
            totals[month][0] += occurrence.profile_share or Decimal("0")
        elif occurrence.amount < 0:
            totals[month][1] -= occurrence.profile_share or Decimal("0")
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
async def category_stats(
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[CategoryBreakdown]:
    today = local_today()
    month_start = _month_start(today)
    month_end = add_month(month_start, 1) - timedelta(days=1)
    occurrences = await recurring_budget_occurrences(
        session,
        month_start,
        month_end,
        profile_id=profile.id,
    )
    spent: dict[int | None, Decimal] = {}
    for occurrence in occurrences:
        if occurrence.amount >= 0:
            continue
        spent[occurrence.category_id] = money(
            spent.get(occurrence.category_id, Decimal("0"))
            - (occurrence.profile_share or Decimal("0"))
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
