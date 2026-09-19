"""Singleton preferences. No external AI or logo services are ever contacted."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..common import get_preferences
from ..db import get_session
from ..models import Profile
from ..profile_session import require_active_profile
from ..schemas import PreferencesRead, PreferencesUpdate

router = APIRouter(tags=["preferences"])


@router.get("/preferences", response_model=PreferencesRead)
async def read_preferences(
    _profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PreferencesRead:
    return PreferencesRead.model_validate(await get_preferences(session))


@router.patch("/preferences", response_model=PreferencesRead)
async def update_preferences(
    payload: PreferencesUpdate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PreferencesRead:
    if profile.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Profil administrateur requis")
    prefs = await get_preferences(session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(prefs, field, value)
    await session.commit()
    await session.refresh(prefs)
    return PreferencesRead.model_validate(prefs)
