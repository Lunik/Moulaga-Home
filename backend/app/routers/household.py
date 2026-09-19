"""Singleton household goals, scoped to the active profile session.

The legacy household/member and shared-account paths are retained where useful
for API compatibility, but they cannot select another household or use an
``actor_id`` header. Profiles and account owners are now managed by their
dedicated APIs.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account
from ..common import money
from ..db import get_session
from ..models import Goal, GoalContribution, Household, HouseholdMember, Profile
from ..profile_session import require_active_profile
from ..schemas import (
    GoalContributionCreate,
    GoalContributionRead,
    GoalCreate,
    GoalRead,
    GoalUpdate,
    HouseholdCreate,
    HouseholdRead,
    MemberCreate,
    MemberRead,
    MemberUpdate,
    SharedLinkCreate,
    SharedLinkRead,
)

router = APIRouter(tags=["household"])


def _goal_read(goal: Goal) -> GoalRead:
    target = Decimal(goal.target_amount)
    current = Decimal(goal.current_amount)
    progress = (current / target).quantize(Decimal("0.01")) if target > 0 else Decimal("0.00")
    return GoalRead(
        id=goal.id,
        household_id=goal.household_id,
        name=goal.name,
        target_amount=money(target),
        current_amount=money(current),
        due_date=goal.due_date,
        account_id=goal.account_id,
        progress=progress,
    )


async def _require_profile_household(
    session: AsyncSession, household_id: int, profile: Profile
) -> Household:
    """Return only the active profile's technical singleton household."""
    if profile.household_id != household_id:
        raise HTTPException(status_code=404, detail="Foyer introuvable")
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Foyer introuvable")
    return household


def _require_admin(profile: Profile) -> None:
    if profile.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Profil administrateur requis")


def _legacy_member_role(role: str) -> str:
    return "admin" if role in {"admin", "owner"} else "member"


async def _goal_for_profile(
    session: AsyncSession, household_id: int, goal_id: int, profile: Profile
) -> Goal:
    await _require_profile_household(session, household_id, profile)
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.household_id != profile.household_id:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    return goal


@router.get("/households", response_model=list[HouseholdRead])
async def list_households(
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[HouseholdRead]:
    household = await _require_profile_household(session, profile.household_id, profile)
    members_query = select(HouseholdMember).where(
        HouseholdMember.household_id == profile.household_id
    )
    if profile.role not in {"admin", "owner"}:
        members_query = members_query.where(HouseholdMember.active.is_(True))
    members = (await session.scalars(members_query.order_by(HouseholdMember.id))).all()
    return [
        HouseholdRead(
            id=household.id,
            name=household.name,
            members=[MemberRead.model_validate(member) for member in members],
        )
    ]


@router.post("/households", response_model=HouseholdRead, status_code=status.HTTP_409_CONFLICT)
async def create_household(
    _payload: HouseholdCreate,
    _profile: Profile = Depends(require_active_profile),
) -> HouseholdRead:
    """Retired: the instance owns one technical household created at onboarding."""
    raise HTTPException(status_code=409, detail="Cette instance utilise un foyer unique")


@router.get("/households/{household_id}", response_model=HouseholdRead)
async def get_household(
    household_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> HouseholdRead:
    household = await _require_profile_household(session, household_id, profile)
    members_query = select(HouseholdMember).where(
        HouseholdMember.household_id == profile.household_id
    )
    if profile.role not in {"admin", "owner"}:
        members_query = members_query.where(HouseholdMember.active.is_(True))
    members = (await session.scalars(members_query.order_by(HouseholdMember.id))).all()
    return HouseholdRead(
        id=household.id,
        name=household.name,
        members=[MemberRead.model_validate(member) for member in members],
    )


@router.post(
    "/households/{household_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    household_id: int,
    payload: MemberCreate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    """Legacy profile creation path, restricted to the active household admin."""
    _require_admin(profile)
    await _require_profile_household(session, household_id, profile)
    member = HouseholdMember(
        household_id=profile.household_id,
        name=payload.name,
        role=_legacy_member_role(payload.role),
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return MemberRead.model_validate(member)


@router.patch("/households/{household_id}/members/{member_id}", response_model=MemberRead)
async def update_member(
    household_id: int,
    member_id: int,
    payload: MemberUpdate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    _require_admin(profile)
    await _require_profile_household(session, household_id, profile)
    member = await session.get(HouseholdMember, member_id)
    if member is None or member.household_id != profile.household_id:
        raise HTTPException(status_code=404, detail="Membre introuvable")
    if (
        member.role in {"admin", "owner"}
        and payload.role is not None
        and _legacy_member_role(payload.role) == "member"
    ):
        remaining_admins = await session.scalar(
            select(func.count())
            .select_from(HouseholdMember)
            .where(
                HouseholdMember.household_id == profile.household_id,
                HouseholdMember.id != member.id,
                HouseholdMember.active.is_(True),
                HouseholdMember.role.in_(("admin", "owner")),
            )
        )
        if not remaining_admins:
            raise HTTPException(
                status_code=409,
                detail="Au moins un administrateur actif est requis",
            )
    if payload.name is not None:
        member.name = payload.name
    if payload.role is not None:
        member.role = _legacy_member_role(payload.role)
    await session.commit()
    await session.refresh(member)
    return MemberRead.model_validate(member)


@router.delete("/households/{household_id}/members/{member_id}", status_code=status.HTTP_409_CONFLICT)
async def remove_member(
    household_id: int,
    member_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_admin(profile)
    await _require_profile_household(session, household_id, profile)
    member = await session.get(HouseholdMember, member_id)
    if member is None or member.household_id != profile.household_id:
        raise HTTPException(status_code=404, detail="Membre introuvable")
    raise HTTPException(
        status_code=409,
        detail="Les profils sont archives via PATCH /profiles/{profile_id}",
    )


async def _retired_shared_accounts(
    household_id: int,
    profile: Profile,
    session: AsyncSession,
) -> None:
    await _require_profile_household(session, household_id, profile)
    raise HTTPException(
        status_code=410,
        detail="Les comptes partages utilisent desormais leurs proprietaires de profil",
    )


@router.get("/households/{household_id}/shared-accounts", response_model=list[SharedLinkRead])
async def list_shared_accounts(
    household_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[SharedLinkRead]:
    await _retired_shared_accounts(household_id, profile, session)


@router.post(
    "/households/{household_id}/shared-accounts",
    response_model=SharedLinkRead,
    status_code=status.HTTP_410_GONE,
)
async def share_account(
    household_id: int,
    _payload: SharedLinkCreate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> SharedLinkRead:
    await _retired_shared_accounts(household_id, profile, session)


@router.delete(
    "/households/{household_id}/shared-accounts/{link_id}",
    status_code=status.HTTP_410_GONE,
)
async def unshare_account(
    household_id: int,
    _link_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _retired_shared_accounts(household_id, profile, session)


@router.get("/households/{household_id}/goals", response_model=list[GoalRead])
async def list_goals(
    household_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[GoalRead]:
    await _require_profile_household(session, household_id, profile)
    rows = (
        await session.scalars(
            select(Goal).where(Goal.household_id == profile.household_id).order_by(Goal.id)
        )
    ).all()
    return [_goal_read(row) for row in rows]


@router.post(
    "/households/{household_id}/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED
)
async def create_goal(
    household_id: int,
    payload: GoalCreate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> GoalRead:
    await _require_profile_household(session, household_id, profile)
    if payload.account_id is not None:
        await require_account(session, payload.account_id, writable=True, profile_id=profile.id)
    goal = Goal(household_id=profile.household_id, **payload.model_dump())
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return _goal_read(goal)


@router.patch("/households/{household_id}/goals/{goal_id}", response_model=GoalRead)
async def update_goal(
    household_id: int,
    goal_id: int,
    payload: GoalUpdate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> GoalRead:
    goal = await _goal_for_profile(session, household_id, goal_id, profile)
    if goal.account_id is not None:
        await require_account(session, goal.account_id, writable=True, profile_id=profile.id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("account_id") is not None:
        await require_account(session, data["account_id"], writable=True, profile_id=profile.id)
    for field, value in data.items():
        setattr(goal, field, value)
    await session.commit()
    await session.refresh(goal)
    return _goal_read(goal)


@router.delete("/households/{household_id}/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    household_id: int,
    goal_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_admin(profile)
    goal = await _goal_for_profile(session, household_id, goal_id, profile)
    if goal.account_id is not None:
        await require_account(session, goal.account_id, writable=True, profile_id=profile.id)
    await session.delete(goal)
    await session.commit()


async def _goal_contribution_read(
    session: AsyncSession, contribution: GoalContribution
) -> GoalContributionRead:
    member_name: str | None = None
    if contribution.member_id is not None:
        member = await session.get(HouseholdMember, contribution.member_id)
        member_name = member.name if member else None
    return GoalContributionRead(
        id=contribution.id,
        goal_id=contribution.goal_id,
        amount=money(Decimal(contribution.amount)),
        occurred_on=contribution.occurred_on,
        member_id=contribution.member_id,
        note=contribution.note,
        member_name=member_name,
    )


@router.get(
    "/households/{household_id}/goals/{goal_id}/contributions",
    response_model=list[GoalContributionRead],
)
async def list_goal_contributions(
    household_id: int,
    goal_id: int,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[GoalContributionRead]:
    goal = await _goal_for_profile(session, household_id, goal_id, profile)
    rows = (
        await session.scalars(
            select(GoalContribution)
            .where(GoalContribution.goal_id == goal.id)
            .order_by(GoalContribution.occurred_on, GoalContribution.id)
        )
    ).all()
    return [await _goal_contribution_read(session, row) for row in rows]


@router.post(
    "/households/{household_id}/goals/{goal_id}/contributions",
    response_model=GoalContributionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_goal_contribution(
    household_id: int,
    goal_id: int,
    payload: GoalContributionCreate,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> GoalContributionRead:
    goal = await _goal_for_profile(session, household_id, goal_id, profile)
    if goal.account_id is not None:
        await require_account(session, goal.account_id, writable=True, profile_id=profile.id)
    if payload.member_id is not None and payload.member_id != profile.id:
        raise HTTPException(status_code=403, detail="Contribution pour un autre profil interdite")
    contribution = GoalContribution(
        goal_id=goal.id,
        member_id=profile.id,
        amount=payload.amount,
        occurred_on=payload.occurred_on,
        note=payload.note,
    )
    session.add(contribution)
    goal.current_amount = money(Decimal(goal.current_amount) + payload.amount)
    await session.commit()
    await session.refresh(contribution)
    return await _goal_contribution_read(session, contribution)
