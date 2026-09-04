"""Wealth: debts, investment holdings, contributions and net-worth analytics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account
from ..common import money
from ..db import get_session
from ..models import (
    Account,
    BalanceSnapshot,
    Contribution,
    Debt,
    Holding,
    PortfolioSnapshot,
    Transaction,
)
from ..schemas import (
    AllocationSlice,
    ContributionCreate,
    ContributionCreateAggregate,
    ContributionRead,
    DebtCreate,
    DebtRead,
    DebtUpdate,
    HoldingCreate,
    HoldingRead,
    HoldingUpdate,
    NetWorthOverview,
    NetWorthPoint,
    PerformancePoint,
    PortfolioSnapshotCreate,
    PortfolioSnapshotRead,
    PortfolioSummary,
)

router = APIRouter(tags=["wealth"])


# --------------------------------------------------------------------------- #
# Debts
# --------------------------------------------------------------------------- #
def _debt_read(debt: Debt) -> DebtRead:
    principal = Decimal(debt.principal)
    balance = Decimal(debt.balance)
    paid = money(principal - balance)
    progress = (paid / principal).quantize(Decimal("0.01")) if principal > 0 else Decimal("0.00")
    return DebtRead(
        id=debt.id,
        name=debt.name,
        principal=money(principal),
        balance=money(balance),
        interest_rate=debt.interest_rate,
        minimum_payment=debt.minimum_payment,
        account_id=debt.account_id,
        due_date=debt.due_date,
        color=debt.color,
        archived=debt.archived,
        paid=paid,
        progress=progress,
    )


@router.get("/debts", response_model=list[DebtRead])
async def list_debts(session: AsyncSession = Depends(get_session)) -> list[DebtRead]:
    rows = (await session.execute(select(Debt).order_by(Debt.name))).scalars().all()
    return [_debt_read(row) for row in rows]


@router.post("/debts", response_model=DebtRead, status_code=201)
async def create_debt(payload: DebtCreate, session: AsyncSession = Depends(get_session)) -> DebtRead:
    if payload.account_id is not None:
        await require_account(session, payload.account_id, writable=True)
    if payload.balance > payload.principal:
        raise HTTPException(status_code=422, detail="Le solde ne peut pas exceder le principal")
    debt = Debt(**payload.model_dump())
    session.add(debt)
    await session.commit()
    await session.refresh(debt)
    return _debt_read(debt)


@router.patch("/debts/{debt_id}", response_model=DebtRead)
async def update_debt(
    debt_id: int, payload: DebtUpdate, session: AsyncSession = Depends(get_session)
) -> DebtRead:
    debt = await session.get(Debt, debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="Dette introuvable")
    if debt.account_id is not None:
        await require_account(session, debt.account_id, writable=True)
    data = payload.model_dump(exclude_unset=True)
    if data.get("account_id") is not None:
        await require_account(session, data["account_id"], writable=True)
    for field, value in data.items():
        setattr(debt, field, value)
    if Decimal(debt.balance) > Decimal(debt.principal):
        raise HTTPException(status_code=422, detail="Le solde ne peut pas exceder le principal")
    await session.commit()
    await session.refresh(debt)
    return _debt_read(debt)


@router.delete("/debts/{debt_id}", status_code=204)
async def delete_debt(debt_id: int, session: AsyncSession = Depends(get_session)) -> None:
    debt = await session.get(Debt, debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="Dette introuvable")
    if debt.account_id is not None:
        await require_account(session, debt.account_id, writable=True)
    await session.delete(debt)
    await session.commit()


# --------------------------------------------------------------------------- #
# Holdings
# --------------------------------------------------------------------------- #
def _holding_read(holding: Holding) -> HoldingRead:
    quantity = Decimal(holding.quantity)
    cost_basis = money(quantity * Decimal(holding.average_price))
    market_value = money(quantity * Decimal(holding.current_price))
    return HoldingRead(
        id=holding.id,
        account_id=holding.account_id,
        name=holding.name,
        symbol=holding.symbol,
        asset_class=holding.asset_class,
        quantity=quantity,
        average_price=Decimal(holding.average_price),
        current_price=Decimal(holding.current_price),
        cost_basis=cost_basis,
        market_value=market_value,
        gain=money(market_value - cost_basis),
    )


@router.get("/holdings", response_model=list[HoldingRead])
async def list_holdings(
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[HoldingRead]:
    statement = select(Holding).order_by(Holding.name)
    if account_id is not None:
        if await session.get(Account, account_id) is None:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        statement = statement.where(Holding.account_id == account_id)
    rows = (await session.execute(statement)).scalars().all()
    return [_holding_read(row) for row in rows]


@router.post("/holdings", response_model=HoldingRead, status_code=201)
async def create_holding(
    payload: HoldingCreate, session: AsyncSession = Depends(get_session)
) -> HoldingRead:
    await require_account(session, payload.account_id, writable=True)
    holding = Holding(**payload.model_dump())
    session.add(holding)
    await session.commit()
    await session.refresh(holding)
    return _holding_read(holding)


@router.patch("/holdings/{holding_id}", response_model=HoldingRead)
async def update_holding(
    holding_id: int, payload: HoldingUpdate, session: AsyncSession = Depends(get_session)
) -> HoldingRead:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(holding, field, value)
    await session.commit()
    await session.refresh(holding)
    return _holding_read(holding)


@router.delete("/holdings/{holding_id}", status_code=204)
async def delete_holding(holding_id: int, session: AsyncSession = Depends(get_session)) -> None:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    await session.delete(holding)
    await session.commit()


# --------------------------------------------------------------------------- #
# Contributions
# --------------------------------------------------------------------------- #
@router.get("/holdings/{holding_id}/contributions", response_model=list[ContributionRead])
async def list_contributions(
    holding_id: int, session: AsyncSession = Depends(get_session)
) -> list[ContributionRead]:
    if await session.get(Holding, holding_id) is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    rows = (
        await session.execute(
            select(Contribution)
            .where(Contribution.holding_id == holding_id)
            .order_by(Contribution.occurred_on)
        )
    ).scalars().all()
    return [ContributionRead.model_validate(row) for row in rows]


@router.post(
    "/holdings/{holding_id}/contributions", response_model=ContributionRead, status_code=201
)
async def create_contribution(
    holding_id: int,
    payload: ContributionCreate,
    session: AsyncSession = Depends(get_session),
) -> ContributionRead:
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    contribution = Contribution(holding_id=holding_id, **payload.model_dump())
    session.add(contribution)
    await session.commit()
    await session.refresh(contribution)
    return ContributionRead.model_validate(contribution)


@router.delete("/holdings/{holding_id}/contributions/{contribution_id}", status_code=204)
async def delete_contribution(
    holding_id: int,
    contribution_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    contribution = await session.get(Contribution, contribution_id)
    if contribution is None or contribution.holding_id != holding_id:
        raise HTTPException(status_code=404, detail="Versement introuvable")
    holding = await session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    await session.delete(contribution)
    await session.commit()


@router.get("/contributions", response_model=list[ContributionRead])
async def list_all_contributions(
    session: AsyncSession = Depends(get_session),
) -> list[ContributionRead]:
    rows = (
        await session.execute(
            select(Contribution).order_by(Contribution.occurred_on, Contribution.id)
        )
    ).scalars().all()
    return [ContributionRead.model_validate(row) for row in rows]


@router.post("/contributions", response_model=ContributionRead, status_code=201)
async def create_aggregate_contribution(
    payload: ContributionCreateAggregate,
    session: AsyncSession = Depends(get_session),
) -> ContributionRead:
    holding = await session.get(Holding, payload.holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Actif introuvable")
    await require_account(session, holding.account_id, writable=True)
    contribution = Contribution(**payload.model_dump())
    session.add(contribution)
    await session.commit()
    await session.refresh(contribution)
    return ContributionRead.model_validate(contribution)


# --------------------------------------------------------------------------- #
# Portfolio analytics
# --------------------------------------------------------------------------- #
@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary(session: AsyncSession = Depends(get_session)) -> PortfolioSummary:
    holdings = (await session.execute(select(Holding))).scalars().all()
    cost_basis = sum((Decimal(h.quantity) * Decimal(h.average_price) for h in holdings), Decimal("0"))
    market_value = sum(
        (Decimal(h.quantity) * Decimal(h.current_price) for h in holdings), Decimal("0")
    )
    contributions_total = await session.scalar(
        select(func.coalesce(func.sum(Contribution.amount), 0))
    )
    return PortfolioSummary(
        cost_basis=money(cost_basis),
        market_value=money(market_value),
        gain=money(market_value - cost_basis),
        contributions_total=money(contributions_total),
        holdings=len(holdings),
    )


@router.get("/portfolio/allocation", response_model=list[AllocationSlice])
async def portfolio_allocation(session: AsyncSession = Depends(get_session)) -> list[AllocationSlice]:
    holdings = (await session.execute(select(Holding))).scalars().all()
    by_class: dict[str, Decimal] = {}
    for holding in holdings:
        value = Decimal(holding.quantity) * Decimal(holding.current_price)
        by_class[holding.asset_class] = by_class.get(holding.asset_class, Decimal("0")) + value
    total = sum(by_class.values(), Decimal("0"))
    slices = []
    for asset_class, value in sorted(by_class.items(), key=lambda item: item[1], reverse=True):
        weight = (value / total).quantize(Decimal("0.0001")) if total > 0 else Decimal("0")
        slices.append(
            AllocationSlice(asset_class=asset_class, market_value=money(value), weight=weight)
        )
    return slices


@router.get("/portfolio/snapshots", response_model=list[PortfolioSnapshotRead])
async def list_portfolio_snapshots(
    session: AsyncSession = Depends(get_session),
) -> list[PortfolioSnapshotRead]:
    rows = (
        await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.period))
    ).scalars().all()
    return [PortfolioSnapshotRead.model_validate(row) for row in rows]


@router.put("/portfolio/snapshots", response_model=PortfolioSnapshotRead)
async def upsert_portfolio_snapshot(
    payload: PortfolioSnapshotCreate, session: AsyncSession = Depends(get_session)
) -> PortfolioSnapshotRead:
    snapshot = await session.scalar(
        select(PortfolioSnapshot).where(PortfolioSnapshot.period == payload.period)
    )
    if snapshot is None:
        snapshot = PortfolioSnapshot(period=payload.period)
        session.add(snapshot)
    snapshot.market_value = money(payload.market_value)
    snapshot.cost_basis = money(payload.cost_basis)
    await session.commit()
    await session.refresh(snapshot)
    return PortfolioSnapshotRead.model_validate(snapshot)


@router.post("/portfolio/snapshots/generate", response_model=PortfolioSnapshotRead)
async def generate_portfolio_snapshot(
    period: str | None = None, session: AsyncSession = Depends(get_session)
) -> PortfolioSnapshotRead:
    """Idempotently record the current portfolio valuation for a month (YYYY-MM)."""
    reference = period or date.today().strftime("%Y-%m")
    if len(reference) != 7 or reference[4] != "-":
        raise HTTPException(status_code=422, detail="Periode invalide (attendu AAAA-MM)")
    holdings = (await session.execute(select(Holding))).scalars().all()
    cost_basis = sum((Decimal(h.quantity) * Decimal(h.average_price) for h in holdings), Decimal("0"))
    market_value = sum(
        (Decimal(h.quantity) * Decimal(h.current_price) for h in holdings), Decimal("0")
    )
    snapshot = await session.scalar(
        select(PortfolioSnapshot).where(PortfolioSnapshot.period == reference)
    )
    if snapshot is None:
        snapshot = PortfolioSnapshot(period=reference)
        session.add(snapshot)
    snapshot.market_value = money(market_value)
    snapshot.cost_basis = money(cost_basis)
    await session.commit()
    await session.refresh(snapshot)
    return PortfolioSnapshotRead.model_validate(snapshot)


@router.get("/portfolio/performance", response_model=list[PerformancePoint])
async def portfolio_performance(session: AsyncSession = Depends(get_session)) -> list[PerformancePoint]:
    month_expr = func.strftime("%Y-%m", Contribution.occurred_on)
    contrib_rows = (
        await session.execute(
            select(month_expr, func.sum(Contribution.amount))
            .group_by(month_expr)
            .order_by(month_expr)
        )
    ).all()
    contrib_by_period = {period: Decimal(amount or 0) for period, amount in contrib_rows}

    snapshots = (
        await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.period))
    ).scalars().all()
    snapshot_by_period = {s.period: s for s in snapshots}

    periods = sorted(set(contrib_by_period) | set(snapshot_by_period))
    points: list[PerformancePoint] = []
    cumulative = Decimal("0")
    for period in periods:
        contributed = contrib_by_period.get(period, Decimal("0"))
        cumulative += contributed
        snapshot = snapshot_by_period.get(period)
        market_value = Decimal(snapshot.market_value) if snapshot else Decimal("0")
        cost_basis = Decimal(snapshot.cost_basis) if snapshot else Decimal("0")
        points.append(
            PerformancePoint(
                period=period,
                market_value=money(market_value),
                cost_basis=money(cost_basis),
                gain=money(market_value - cost_basis),
                contributions=money(contributed),
                cumulative_contributions=money(cumulative),
            )
        )
    return points


# --------------------------------------------------------------------------- #
# Net worth
# --------------------------------------------------------------------------- #
async def _investment_account_ids(session: AsyncSession) -> set[int]:
    rows = (await session.execute(select(Holding.account_id).distinct())).scalars().all()
    return set(rows)


@router.get("/networth/overview", response_model=NetWorthOverview)
async def net_worth_overview(session: AsyncSession = Depends(get_session)) -> NetWorthOverview:
    investment_accounts = await _investment_account_ids(session)

    # Cash: computed balances of accounts that do NOT hold investments, so a
    # holding's market value is never double counted with its account balance.
    account_rows = (
        await session.execute(
            select(
                Account.id,
                Account.initial_balance + func.coalesce(func.sum(Transaction.amount), 0),
            )
            .outerjoin(Transaction, Transaction.account_id == Account.id)
            .group_by(Account.id)
        )
    ).all()
    cash = sum(
        (Decimal(balance or 0) for account_id, balance in account_rows
         if account_id not in investment_accounts),
        Decimal("0"),
    )

    holdings = (await session.execute(select(Holding))).scalars().all()
    investments = sum(
        (Decimal(h.quantity) * Decimal(h.current_price) for h in holdings), Decimal("0")
    )
    debts = await session.scalar(select(func.coalesce(func.sum(Debt.balance), 0)))
    debts_total = Decimal(debts or 0)

    return NetWorthOverview(
        cash=money(cash),
        investments=money(investments),
        debts=money(debts_total),
        net_worth=money(cash + investments - debts_total),
    )


@router.get("/networth/history", response_model=list[NetWorthPoint])
async def net_worth_history(session: AsyncSession = Depends(get_session)) -> list[NetWorthPoint]:
    """Historical net worth from cash snapshots plus cumulative contributions.

    Investment accounts are excluded from the cash side (their value is tracked
    via contributions) so nothing is double counted. Current total debt is
    subtracted from each period as a conservative baseline.
    """
    investment_accounts = await _investment_account_ids(session)
    snapshots = (
        await session.execute(select(BalanceSnapshot).order_by(BalanceSnapshot.period))
    ).scalars().all()

    cash_by_period: dict[str, Decimal] = {}
    for snapshot in snapshots:
        if snapshot.account_id in investment_accounts:
            continue
        cash_by_period[snapshot.period] = cash_by_period.get(
            snapshot.period, Decimal("0")
        ) + Decimal(snapshot.balance)

    contrib_rows = (
        await session.execute(
            select(
                func.strftime("%Y-%m", Contribution.occurred_on), func.sum(Contribution.amount)
            )
            .group_by(func.strftime("%Y-%m", Contribution.occurred_on))
            .order_by(func.strftime("%Y-%m", Contribution.occurred_on))
        )
    ).all()
    contrib_by_period = {period: Decimal(amount or 0) for period, amount in contrib_rows}

    debts = await session.scalar(select(func.coalesce(func.sum(Debt.balance), 0)))
    debts_total = Decimal(debts or 0)

    periods = sorted(set(cash_by_period) | set(contrib_by_period))
    points: list[NetWorthPoint] = []
    cumulative_contrib = Decimal("0")
    for period in periods:
        cumulative_contrib += contrib_by_period.get(period, Decimal("0"))
        cash = cash_by_period.get(period, Decimal("0"))
        points.append(
            NetWorthPoint(
                period=period,
                net_worth=money(cash + cumulative_contrib - debts_total),
            )
        )
    return points
