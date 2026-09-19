"""Shared dependency for the active local-profile browser session."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import config
from .db import get_session
from .models import Profile, ProfileSession


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def require_active_profile(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Profile:
    """Resolve, refresh and enforce the active profile session for API routes."""
    token = request.cookies.get(config.settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Profil actif requis")
    row = (
        await session.execute(
            select(ProfileSession, Profile)
            .join(Profile, Profile.id == ProfileSession.profile_id)
            .where(ProfileSession.token_hash == hashlib.sha256(token.encode()).hexdigest())
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=401, detail="Session de profil invalide")

    profile_session, profile = row
    now = datetime.now(UTC)
    expired = _as_utc(profile_session.expires_at) <= now
    idle_locked = profile.pin_hash is not None and (
        now - _as_utc(profile_session.last_seen_at)
        > timedelta(minutes=config.settings.protected_profile_idle_minutes)
    )
    if not profile.active or expired or idle_locked:
        await session.execute(
            delete(ProfileSession).where(ProfileSession.id == profile_session.id)
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="Session de profil expiree ou verrouillee")

    refreshed_id = await session.scalar(
        update(ProfileSession)
        .where(ProfileSession.id == profile_session.id)
        .values(last_seen_at=now)
        .returning(ProfileSession.id)
    )
    if refreshed_id is None:
        await session.rollback()
        raise HTTPException(status_code=401, detail="Session de profil invalide")
    await session.commit()
    return profile
