"""Household local sharing with role-gated mutations.

Moulaga has no remote authentication. Every mutating endpoint therefore
requires an explicit actor, supplied as the ``actor_id`` query parameter or the
``X-Actor-Id`` header. The actor must be a member of the target household and
hold a sufficient local role. This models local profiles/roles only; it is not
network authentication and no passwords are stored.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account
from ..account_balances import account_balance
from ..common import money, require_actor
from ..db import get_session
from ..models import (
    Account,
    Goal,
    GoalContribution,
    Household,
    HouseholdMember,
    SharedAccountLink,
)
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


async def resolve_actor(
    actor_id: int | None = Query(default=None),
    x_actor_id: int | None = Header(default=None),
) -> int | None:
    """The acting member id from the query param or the ``X-Actor-Id`` header."""
    return actor_id if actor_id is not None else x_actor_id


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


async def _require_household(session: AsyncSession, household_id: int) -> Household:
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Foyer introuvable")
    return household


async def _shared_link_read(session: AsyncSession, link: SharedAccountLink) -> SharedLinkRead:
    account = await session.get(Account, link.account_id)
    return SharedLinkRead(
        id=link.id,
        household_id=link.household_id,
        account_id=link.account_id,
        permission=link.permission,
        account_name=account.name if account else "",
        balance=await account_balance(session, account) if account else Decimal("0.00"),
    )


# --------------------------------------------------------------------------- #
# Households + members
# --------------------------------------------------------------------------- #
@router.get("/households", response_model=list[HouseholdRead])
async def list_households(session: AsyncSession = Depends(get_session)) -> list[HouseholdRead]:
    households = (
        await session.execute(select(Household).order_by(Household.name))
    ).scalars().all()
    result = []
    for household in households:
        members = (
            await session.execute(
                select(HouseholdMember).where(HouseholdMember.household_id == household.id)
            )
        ).scalars().all()
        result.append(
            HouseholdRead(
                id=household.id,
                name=household.name,
                members=[MemberRead.model_validate(m) for m in members],
            )
        )
    return result


@router.post("/households", response_model=HouseholdRead, status_code=201)
async def create_household(
    payload: HouseholdCreate, session: AsyncSession = Depends(get_session)
) -> HouseholdRead:
    """Bootstrap a household; the creator becomes its first ``owner`` member."""
    household = Household(name=payload.name)
    session.add(household)
    await session.flush()
    owner = HouseholdMember(household_id=household.id, name=payload.owner_name, role="owner")
    session.add(owner)
    await session.commit()
    await session.refresh(household)
    return HouseholdRead(
        id=household.id,
        name=household.name,
        members=[MemberRead.model_validate(owner)],
    )


@router.get("/households/{household_id}", response_model=HouseholdRead)
async def get_household(
    household_id: int, session: AsyncSession = Depends(get_session)
) -> HouseholdRead:
    household = await _require_household(session, household_id)
    members = (
        await session.execute(
            select(HouseholdMember).where(HouseholdMember.household_id == household_id)
        )
    ).scalars().all()
    return HouseholdRead(
        id=household.id,
        name=household.name,
        members=[MemberRead.model_validate(m) for m in members],
    )


@router.post("/households/{household_id}/members", response_model=MemberRead, status_code=201)
async def add_member(
    household_id: int,
    payload: MemberCreate,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "admin", actor_id)
    member = HouseholdMember(household_id=household_id, **payload.model_dump())
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return MemberRead.model_validate(member)


@router.patch(
    "/households/{household_id}/members/{member_id}", response_model=MemberRead
)
async def update_member(
    household_id: int,
    member_id: int,
    payload: MemberUpdate,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "admin", actor_id)
    member = await session.get(HouseholdMember, member_id)
    if member is None or member.household_id != household_id:
        raise HTTPException(status_code=404, detail="Membre introuvable")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    await session.commit()
    await session.refresh(member)
    return MemberRead.model_validate(member)


@router.delete("/households/{household_id}/members/{member_id}", status_code=204)
async def remove_member(
    household_id: int,
    member_id: int,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "owner", actor_id)
    member = await session.get(HouseholdMember, member_id)
    if member is None or member.household_id != household_id:
        raise HTTPException(status_code=404, detail="Membre introuvable")
    await session.delete(member)
    await session.commit()


# --------------------------------------------------------------------------- #
# Shared account links
# --------------------------------------------------------------------------- #
@router.get("/households/{household_id}/shared-accounts", response_model=list[SharedLinkRead])
async def list_shared_accounts(
    household_id: int, session: AsyncSession = Depends(get_session)
) -> list[SharedLinkRead]:
    await _require_household(session, household_id)
    rows = (
        await session.execute(
            select(SharedAccountLink).where(SharedAccountLink.household_id == household_id)
        )
    ).scalars().all()
    return [await _shared_link_read(session, row) for row in rows]


@router.post(
    "/households/{household_id}/shared-accounts", response_model=SharedLinkRead, status_code=201
)
async def share_account(
    household_id: int,
    payload: SharedLinkCreate,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> SharedLinkRead:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "admin", actor_id)
    await require_account(session, payload.account_id, writable=True)
    link = SharedAccountLink(household_id=household_id, **payload.model_dump())
    session.add(link)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Compte deja partage") from exc
    await session.refresh(link)
    return await _shared_link_read(session, link)


@router.delete(
    "/households/{household_id}/shared-accounts/{link_id}", status_code=204
)
async def unshare_account(
    household_id: int,
    link_id: int,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "admin", actor_id)
    link = await session.get(SharedAccountLink, link_id)
    if link is None or link.household_id != household_id:
        raise HTTPException(status_code=404, detail="Partage introuvable")
    await require_account(session, link.account_id, writable=True)
    await session.delete(link)
    await session.commit()


# --------------------------------------------------------------------------- #
# Goals + goal contributions
# --------------------------------------------------------------------------- #
@router.get("/households/{household_id}/goals", response_model=list[GoalRead])
async def list_goals(
    household_id: int, session: AsyncSession = Depends(get_session)
) -> list[GoalRead]:
    await _require_household(session, household_id)
    rows = (
        await session.execute(select(Goal).where(Goal.household_id == household_id))
    ).scalars().all()
    return [_goal_read(row) for row in rows]


@router.post("/households/{household_id}/goals", response_model=GoalRead, status_code=201)
async def create_goal(
    household_id: int,
    payload: GoalCreate,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> GoalRead:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "member", actor_id)
    if payload.account_id is not None:
        await require_account(session, payload.account_id, writable=True)
    goal = Goal(household_id=household_id, **payload.model_dump())
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return _goal_read(goal)


@router.patch("/households/{household_id}/goals/{goal_id}", response_model=GoalRead)
async def update_goal(
    household_id: int,
    goal_id: int,
    payload: GoalUpdate,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> GoalRead:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "member", actor_id)
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.household_id != household_id:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    if goal.account_id is not None:
        await require_account(session, goal.account_id, writable=True)
    data = payload.model_dump(exclude_unset=True)
    if data.get("account_id") is not None:
        await require_account(session, data["account_id"], writable=True)
    for field, value in data.items():
        setattr(goal, field, value)
    await session.commit()
    await session.refresh(goal)
    return _goal_read(goal)


@router.delete("/households/{household_id}/goals/{goal_id}", status_code=204)
async def delete_goal(
    household_id: int,
    goal_id: int,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "admin", actor_id)
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.household_id != household_id:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    if goal.account_id is not None:
        await require_account(session, goal.account_id, writable=True)
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
    session: AsyncSession = Depends(get_session),
) -> list[GoalContributionRead]:
    await _require_household(session, household_id)
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.household_id != household_id:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    rows = (
        await session.execute(
            select(GoalContribution)
            .where(GoalContribution.goal_id == goal_id)
            .order_by(GoalContribution.occurred_on)
        )
    ).scalars().all()
    return [await _goal_contribution_read(session, row) for row in rows]


@router.post(
    "/households/{household_id}/goals/{goal_id}/contributions",
    response_model=GoalContributionRead,
    status_code=201,
)
async def add_goal_contribution(
    household_id: int,
    goal_id: int,
    payload: GoalContributionCreate,
    actor_id: int | None = Depends(resolve_actor),
    session: AsyncSession = Depends(get_session),
) -> GoalContributionRead:
    await _require_household(session, household_id)
    await require_actor(session, household_id, "member", actor_id)
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.household_id != household_id:
        raise HTTPException(status_code=404, detail="Objectif introuvable")
    if goal.account_id is not None:
        await require_account(session, goal.account_id, writable=True)
    if payload.member_id is not None:
        member = await session.get(HouseholdMember, payload.member_id)
        if member is None or member.household_id != household_id:
            raise HTTPException(status_code=404, detail="Membre introuvable")
    contribution = GoalContribution(goal_id=goal_id, **payload.model_dump())
    session.add(contribution)
    goal.current_amount = money(Decimal(goal.current_amount) + payload.amount)
    await session.commit()
    await session.refresh(contribution)
    return await _goal_contribution_read(session, contribution)
