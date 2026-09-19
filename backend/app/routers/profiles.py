"""Profile selection and local browser sessions.

The API deliberately exposes active profile tiles without a session so a browser
can render the selector after restart. All profile management routes require an
active administrator session; the opaque session value itself is HttpOnly.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from ..db import get_session
from ..models import (
    Account,
    AccountOwner,
    Debt,
    DebtOwner,
    Household,
    PaySlip,
    PensionProfile,
    Profile,
    ProfileSession,
    RealEstateAsset,
    RealEstateAssetOwner,
    WorkContract,
)
from ..profile_session import require_active_profile
from ..schemas import (
    ProfileCreate,
    ProfileOwnershipRead,
    ProfileRead,
    ProfileSelectRequest,
    ProfileSessionRead,
    ProfileUpdate,
)

router = APIRouter(tags=["profiles"])

_PIN_ITERATIONS = 600_000
_PIN_MAX_FAILURES = 5
_PIN_LOCK_DURATION = timedelta(minutes=1)
_pin_attempt_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def hash_pin(pin: str) -> str:
    """Hash a PIN with a per-profile salt; plaintext PINs are never persisted."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _PIN_ITERATIONS)
    return f"pbkdf2_sha256${_PIN_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored_hash: str | None) -> bool:
    """Constant-time verification for the format emitted by :func:`hash_pin`."""
    if stored_hash is None:
        return False
    try:
        algorithm, iterations, salt_hex, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), bytes.fromhex(salt_hex), int(iterations)
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest, expected)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _profile_read(profile: Profile) -> ProfileRead:
    role = "admin" if profile.role in {"admin", "owner"} else "member"
    return ProfileRead(
        id=profile.id,
        name=profile.name,
        avatar=profile.avatar,
        color=profile.color,
        role=role,
        active=profile.active,
        has_pin=profile.pin_hash is not None,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=config.settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.settings.session_cookie_name,
        httponly=True,
        secure=config.settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


async def _revoke_cookie_session(request: Request, session: AsyncSession) -> None:
    token = request.cookies.get(config.settings.session_cookie_name)
    if token:
        await session.execute(
            ProfileSession.__table__.delete().where(
                ProfileSession.token_hash == hashlib.sha256(token.encode()).hexdigest()
            )
        )


async def _create_session(profile: Profile, session: AsyncSession) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    session.add(
        ProfileSession(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            profile_id=profile.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=config.settings.profile_session_hours),
        )
    )
    return token


# Kept as a router-level import name for callers that adopted the first
# foundation revision. New routers should import require_active_profile directly.
get_active_profile = require_active_profile


async def require_profile_admin(
    profile: Profile = Depends(get_active_profile),
) -> Profile:
    if profile.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Profil administrateur requis")
    return profile


async def _singleton_household(session: AsyncSession) -> Household:
    household = await session.scalar(select(Household).order_by(Household.id).limit(1))
    if household is None:
        household = Household(name="Foyer")
        session.add(household)
        await session.flush()
    return household


async def _profile_ownership(
    profile_id: int, session: AsyncSession
) -> ProfileOwnershipRead:
    async def ids(statement):
        return list((await session.scalars(statement)).all())

    return ProfileOwnershipRead(
        account_ids=await ids(
            select(AccountOwner.account_id).where(AccountOwner.member_id == profile_id)
        ),
        real_estate_asset_ids=await ids(
            select(RealEstateAssetOwner.asset_id).where(
                RealEstateAssetOwner.member_id == profile_id
            )
        ),
        debt_ids=await ids(select(DebtOwner.debt_id).where(DebtOwner.member_id == profile_id)),
        work_contract_ids=await ids(
            select(WorkContract.id).where(WorkContract.profile_id == profile_id)
        ),
        pay_slip_ids=await ids(select(PaySlip.id).where(PaySlip.profile_id == profile_id)),
        pension_profile_ids=await ids(
            select(PensionProfile.id).where(PensionProfile.profile_id == profile_id)
        ),
    )


async def _claim_unowned_resources(profile: Profile, session: AsyncSession) -> None:
    """Assign startup resources created before the first onboarding profile."""
    async def unowned_ids(resource, owner, resource_field):
        return list(
            (
                await session.scalars(
                    select(resource.id)
                    .outerjoin(owner, resource.id == getattr(owner, resource_field))
                    .where(owner.id.is_(None))
                )
            ).all()
        )

    session.add_all(
        AccountOwner(account_id=resource_id, member_id=profile.id)
        for resource_id in await unowned_ids(Account, AccountOwner, "account_id")
    )
    session.add_all(
        RealEstateAssetOwner(asset_id=resource_id, member_id=profile.id)
        for resource_id in await unowned_ids(
            RealEstateAsset, RealEstateAssetOwner, "asset_id"
        )
    )
    session.add_all(
        DebtOwner(debt_id=resource_id, member_id=profile.id)
        for resource_id in await unowned_ids(Debt, DebtOwner, "debt_id")
    )
    for resource in (WorkContract, PaySlip, PensionProfile):
        await session.execute(
            resource.__table__.update()
            .where(resource.profile_id.is_(None))
            .values(profile_id=profile.id)
        )


async def _ensure_administrator_remains(
    profile: Profile, payload: ProfileUpdate, session: AsyncSession
) -> None:
    is_losing_admin = profile.role in {"admin", "owner"} and (
        payload.role == "member" or payload.active is False
    )
    if not is_losing_admin:
        return
    remaining = await session.scalar(
        select(func.count())
        .select_from(Profile)
        .where(
            Profile.id != profile.id,
            Profile.active.is_(True),
            Profile.role.in_(("admin", "owner")),
        )
    )
    if not remaining:
        raise HTTPException(status_code=409, detail="Au moins un administrateur actif est requis")


@router.get("/profiles", response_model=list[ProfileRead])
async def list_profiles(
    request: Request,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[ProfileRead]:
    """Expose active selector tiles, or every profile to an authenticated admin."""
    statement = select(Profile).order_by(Profile.id)
    if include_archived:
        current_profile = await get_active_profile(request, session)
        if current_profile.role not in {"admin", "owner"}:
            raise HTTPException(status_code=403, detail="Profil administrateur requis")
    else:
        statement = statement.where(Profile.active.is_(True))
    profiles = (await session.scalars(statement)).all()
    return [_profile_read(profile) for profile in profiles]


@router.post("/profiles", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: ProfileCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ProfileRead:
    """Create the first administrator, or let an administrator add a member."""
    connection = await session.connection()
    await connection.exec_driver_sql("BEGIN IMMEDIATE")
    count = await session.scalar(select(func.count()).select_from(Profile))
    is_first_profile = not count
    if not is_first_profile:
        active_profile = await get_active_profile(request, session)
        if active_profile.role not in {"admin", "owner"}:
            raise HTTPException(status_code=403, detail="Profil administrateur requis")
        if payload.pin is not None:
            raise HTTPException(
                status_code=403,
                detail="Chaque membre configure lui-meme son code PIN",
            )
    household = await _singleton_household(session)
    profile = Profile(
        household_id=household.id,
        name=payload.name,
        avatar=payload.avatar,
        color=payload.color,
        role="admin" if is_first_profile else "member",
        active=True,
        pin_hash=(
            await asyncio.to_thread(hash_pin, payload.pin)
            if payload.pin is not None
            else None
        ),
    )
    session.add(profile)
    await session.flush()
    await _claim_unowned_resources(profile, session)
    await session.commit()
    await session.refresh(profile)
    return _profile_read(profile)


@router.get("/profiles/manage", response_model=list[ProfileRead])
async def manage_profiles(
    _admin: Profile = Depends(require_profile_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ProfileRead]:
    profiles = (await session.scalars(select(Profile).order_by(Profile.id))).all()
    return [_profile_read(profile) for profile in profiles]


@router.post("/profiles/manage", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
async def add_profile(
    payload: ProfileCreate,
    _admin: Profile = Depends(require_profile_admin),
    session: AsyncSession = Depends(get_session),
) -> ProfileRead:
    if payload.pin is not None:
        raise HTTPException(
            status_code=403,
            detail="Chaque membre configure lui-meme son code PIN",
        )
    household = await _singleton_household(session)
    profile = Profile(
        household_id=household.id,
        name=payload.name,
        avatar=payload.avatar,
        color=payload.color,
        role="member",
        active=True,
        pin_hash=hash_pin(payload.pin) if payload.pin is not None else None,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return _profile_read(profile)


@router.get("/profile-session", response_model=ProfileSessionRead)
@router.get("/profiles/session", response_model=ProfileSessionRead)
async def read_profile_session(
    profile: Profile = Depends(get_active_profile),
) -> ProfileSessionRead:
    return ProfileSessionRead(profile=_profile_read(profile))


@router.post("/profiles/{profile_id}/select", response_model=ProfileSessionRead)
async def select_profile(
    profile_id: int,
    payload: ProfileSelectRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> ProfileSessionRead:
    profile = await session.get(Profile, profile_id)
    if profile is None or not profile.active:
        raise HTTPException(status_code=404, detail="Profil introuvable")
    if profile.pin_hash is not None:
        async with _pin_attempt_locks[profile_id]:
            await session.refresh(profile)
            now = _now()
            if (
                profile.pin_locked_until is not None
                and _as_utc(profile.pin_locked_until) > now
            ):
                retry_after = max(
                    1,
                    int((_as_utc(profile.pin_locked_until) - now).total_seconds()),
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Trop de tentatives. Réessayez dans une minute.",
                    headers={"Retry-After": str(retry_after)},
                )
            valid_pin = payload.pin is not None and await asyncio.to_thread(
                verify_pin,
                payload.pin,
                profile.pin_hash,
            )
            if not valid_pin:
                profile.pin_failed_attempts += 1
                if profile.pin_failed_attempts >= _PIN_MAX_FAILURES:
                    profile.pin_locked_until = now + _PIN_LOCK_DURATION
                await session.commit()
                raise HTTPException(status_code=401, detail="PIN invalide")
            profile.pin_failed_attempts = 0
            profile.pin_locked_until = None

    await _revoke_cookie_session(request, session)
    token = await _create_session(profile, session)
    await session.commit()
    _set_session_cookie(response, token)
    return ProfileSessionRead(profile=_profile_read(profile))


@router.post("/profile-session/lock", status_code=status.HTTP_204_NO_CONTENT)
@router.post("/profiles/lock", status_code=status.HTTP_204_NO_CONTENT)
async def lock_profile(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _revoke_cookie_session(request, session)
    await session.commit()
    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/profiles/{profile_id}/ownership", response_model=ProfileOwnershipRead)
async def profile_ownership(
    profile_id: int,
    current_profile: Profile = Depends(get_active_profile),
    session: AsyncSession = Depends(get_session),
) -> ProfileOwnershipRead:
    if profile_id != current_profile.id:
        # Profile administration must not become a financial read backdoor.
        raise HTTPException(status_code=404, detail="Profil introuvable")
    return await _profile_ownership(profile_id, session)


@router.patch("/profiles/{profile_id}", response_model=ProfileRead)
async def update_profile(
    profile_id: int,
    payload: ProfileUpdate,
    current_profile: Profile = Depends(get_active_profile),
    session: AsyncSession = Depends(get_session),
) -> ProfileRead:
    profile = await session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profil introuvable")
    is_admin = current_profile.role in {"admin", "owner"}
    if current_profile.id != profile.id and not is_admin:
        raise HTTPException(status_code=403, detail="Modification de profil interdite")
    if (
        current_profile.id != profile.id
        and "pin" in payload.model_fields_set
        and payload.pin is not None
    ):
        raise HTTPException(
            status_code=403,
            detail="Un administrateur peut uniquement supprimer le code PIN d'un autre profil",
        )
    protected_fields = {"active", "role"}
    if not is_admin and protected_fields.intersection(payload.model_fields_set):
        raise HTTPException(status_code=403, detail="Modification de profil interdite")
    if is_admin:
        await _ensure_administrator_remains(profile, payload, session)
    if payload.active is False and profile.active:
        ownership = await _profile_ownership(profile.id, session)
        if any(ownership.model_dump().values()):
            raise HTTPException(
                status_code=409,
                detail="Les ressources du profil doivent etre transferees ou archivees",
            )

    for field in ("name", "avatar", "color", "active", "role"):
        if field in payload.model_fields_set:
            setattr(profile, field, getattr(payload, field))
    if "pin" in payload.model_fields_set:
        profile.pin_hash = (
            await asyncio.to_thread(hash_pin, payload.pin)
            if payload.pin is not None
            else None
        )
        profile.pin_failed_attempts = 0
        profile.pin_locked_until = None
    await session.commit()
    await session.refresh(profile)
    return _profile_read(profile)
