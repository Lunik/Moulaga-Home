"""Category hierarchy management with cycle-safe parent assignment."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..category_budgeting import (
    ParentBudgetTooSmall,
    ensure_ancestor_budgets,
    validate_parent_budget,
)
from ..common import local_today, money
from ..db import get_session
from ..models import CategorizationRule, Category, RecurringSeries, Transaction
from ..schemas import CategoryRead, CategoryRemovalResult, CategoryUpdate

router = APIRouter(tags=["categories"])


async def _spent_this_month(session: AsyncSession, category_id: int) -> Decimal:
    today = local_today()
    month_start = today.replace(day=1)
    total = await session.scalar(
        select(func.sum(Transaction.amount)).where(
            Transaction.category_id == category_id,
            Transaction.booked_at >= month_start,
            Transaction.booked_at <= today,
            Transaction.amount < 0,
            Transaction.transfer_group.is_(None),
        )
    )
    return money(abs(Decimal(total or 0)))


async def _would_create_cycle(
    session: AsyncSession, category_id: int, parent_id: int
) -> bool:
    """True if making ``parent_id`` the parent of ``category_id`` forms a loop."""
    if parent_id == category_id:
        return True
    seen: set[int] = {category_id}
    cursor: int | None = parent_id
    while cursor is not None:
        if cursor in seen:
            return True
        seen.add(cursor)
        parent = await session.get(Category, cursor)
        if parent is None:
            return False
        cursor = parent.parent_id
    return False


@router.get("/categories/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: int, session: AsyncSession = Depends(get_session)
) -> CategoryRead:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")
    return CategoryRead.model_validate(category).model_copy(
        update={"spent_this_month": await _spent_this_month(session, category_id)}
    )


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")

    data = payload.model_dump(exclude_unset=True)
    parent_changed = (
        "parent_id" in data and data["parent_id"] != category.parent_id
    )
    if parent_changed and data["parent_id"] is not None:
        parent = await session.get(Category, data["parent_id"])
        if parent is None:
            raise HTTPException(status_code=404, detail="Categorie parente introuvable")
        if parent.archived:
            raise HTTPException(status_code=409, detail="La categorie parente est archivee")
        if parent.kind != category.kind:
            raise HTTPException(status_code=422, detail="Le parent doit avoir le meme type")
        if await _would_create_cycle(session, category_id, data["parent_id"]):
            raise HTTPException(status_code=422, detail="Hierarchie circulaire interdite")

    if "monthly_budget" in data:
        try:
            await validate_parent_budget(session, category_id, data["monthly_budget"])
        except ParentBudgetTooSmall as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    for field, value in data.items():
        setattr(category, field, value)
    try:
        await session.flush()
        if not category.archived:
            await ensure_ancestor_budgets(session, category.id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Cette categorie existe deja") from exc
    await session.refresh(category)
    return CategoryRead.model_validate(category).model_copy(
        update={"spent_this_month": await _spent_this_month(session, category_id)}
    )


@router.post("/categories/{category_id}/archive", response_model=CategoryRead)
async def archive_category(
    category_id: int,
    archived: bool = True,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    """Archive a category while preserving its historical transaction links."""
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")
    category.archived = archived
    await session.flush()
    if not archived:
        await ensure_ancestor_budgets(session, category.id)
    await session.commit()
    await session.refresh(category)
    return CategoryRead.model_validate(category).model_copy(
        update={"spent_this_month": await _spent_this_month(session, category_id)}
    )


@router.post("/categories/{category_id}/remove", response_model=CategoryRemovalResult)
async def remove_category(
    category_id: int,
    session: AsyncSession = Depends(get_session),
) -> CategoryRemovalResult:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")

    transaction_count = int(
        await session.scalar(
            select(func.count()).select_from(Transaction).where(
                Transaction.category_id == category_id
            )
        )
        or 0
    )
    linked_ids = [
        await session.scalar(
            select(model.id).where(column == category_id).limit(1)
        )
        for model, column in (
            (CategorizationRule, CategorizationRule.category_id),
            (RecurringSeries, RecurringSeries.category_id),
            (Category, Category.parent_id),
        )
    ]
    if transaction_count > 0 or any(linked_id is not None for linked_id in linked_ids):
        category.archived = True
        await session.commit()
        return CategoryRemovalResult(
            action="archived",
            transaction_count=transaction_count,
        )

    await session.delete(category)
    await session.commit()
    return CategoryRemovalResult(action="deleted", transaction_count=0)


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: int,
    replacement_category_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")
    if replacement_category_id == category_id:
        raise HTTPException(
            status_code=422,
            detail="La categorie de destination doit etre differente",
        )

    replacement = await session.get(Category, replacement_category_id)
    if replacement is None:
        raise HTTPException(status_code=404, detail="Categorie de destination introuvable")
    if replacement.archived:
        raise HTTPException(status_code=409, detail="La categorie de destination est archivee")
    if replacement.kind != category.kind:
        raise HTTPException(
            status_code=422,
            detail="La categorie de destination doit avoir le meme type",
        )

    for model in (Transaction, RecurringSeries, CategorizationRule):
        await session.execute(
            update(model)
            .where(model.category_id == category_id)
            .values(category_id=replacement_category_id)
        )
    await session.execute(sql_delete(Category).where(Category.id == category_id))
    await session.commit()
