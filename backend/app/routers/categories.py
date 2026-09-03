"""Category hierarchy management with cycle-safe parent assignment."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..common import money
from ..db import get_session
from ..models import Category, Transaction
from ..schemas import CategoryRead, CategoryUpdate

router = APIRouter(tags=["categories"])


async def _spent_this_month(session: AsyncSession, category_id: int) -> Decimal:
    month_start = date.today().replace(day=1)
    total = await session.scalar(
        select(func.sum(Transaction.amount)).where(
            Transaction.category_id == category_id,
            Transaction.booked_at >= month_start,
            Transaction.amount < 0,
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
    if "parent_id" in data and data["parent_id"] is not None:
        parent = await session.get(Category, data["parent_id"])
        if parent is None:
            raise HTTPException(status_code=404, detail="Categorie parente introuvable")
        if parent.kind != category.kind:
            raise HTTPException(status_code=422, detail="Le parent doit avoir le meme type")
        if await _would_create_cycle(session, category_id, data["parent_id"]):
            raise HTTPException(status_code=422, detail="Hierarchie circulaire interdite")

    for field, value in data.items():
        setattr(category, field, value)
    try:
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
    await session.commit()
    await session.refresh(category)
    return CategoryRead.model_validate(category).model_copy(
        update={"spent_this_month": await _spent_this_month(session, category_id)}
    )
