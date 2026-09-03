"""Fully-local merchant identities.

These records only ever store user-provided local data (a label, a matching
pattern, a short monogram and a color). No logo is fetched and no network call
is ever made. The feature is gated behind the ``local_merchant_identities``
preference toggle, mirroring the other privacy-sensitive endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common import get_preferences
from ..db import get_session
from ..models import MerchantIdentity
from ..schemas import (
    MerchantIdentityCreate,
    MerchantIdentityRead,
    MerchantIdentityUpdate,
)

router = APIRouter(tags=["merchants"])


async def _require_enabled(session: AsyncSession) -> None:
    prefs = await get_preferences(session)
    if not prefs.local_merchant_identities:
        raise HTTPException(
            status_code=403, detail="Les identites marchandes locales sont desactivees"
        )


@router.get("/merchants", response_model=list[MerchantIdentityRead])
async def list_merchants(
    session: AsyncSession = Depends(get_session),
) -> list[MerchantIdentityRead]:
    await _require_enabled(session)
    rows = (
        await session.execute(select(MerchantIdentity).order_by(MerchantIdentity.label))
    ).scalars().all()
    return [MerchantIdentityRead.model_validate(row) for row in rows]


@router.post("/merchants", response_model=MerchantIdentityRead, status_code=201)
async def create_merchant(
    payload: MerchantIdentityCreate, session: AsyncSession = Depends(get_session)
) -> MerchantIdentityRead:
    await _require_enabled(session)
    merchant = MerchantIdentity(**payload.model_dump())
    session.add(merchant)
    await session.commit()
    await session.refresh(merchant)
    return MerchantIdentityRead.model_validate(merchant)


@router.patch("/merchants/{merchant_id}", response_model=MerchantIdentityRead)
async def update_merchant(
    merchant_id: int,
    payload: MerchantIdentityUpdate,
    session: AsyncSession = Depends(get_session),
) -> MerchantIdentityRead:
    await _require_enabled(session)
    merchant = await session.get(MerchantIdentity, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Identite marchande introuvable")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(merchant, field, value)
    await session.commit()
    await session.refresh(merchant)
    return MerchantIdentityRead.model_validate(merchant)


@router.delete("/merchants/{merchant_id}", status_code=204)
async def delete_merchant(
    merchant_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    await _require_enabled(session)
    merchant = await session.get(MerchantIdentity, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Identite marchande introuvable")
    await session.delete(merchant)
    await session.commit()
