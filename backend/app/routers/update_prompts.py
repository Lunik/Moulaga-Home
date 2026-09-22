"""Profile-scoped prompts for stale or incomplete financial information."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import HOLDING_ACCOUNT_TYPES, visible_account_ids
from ..common import add_month, local_today
from ..db import get_session
from ..models import (
    Account,
    BalanceSnapshot,
    Debt,
    DebtOwner,
    Holding,
    HoldingOperation,
    PaySlip,
    PensionProfile,
    Profile,
    RealEstateAsset,
    RealEstateAssetOwner,
    RecurringSeries,
    UpdatePromptDismissal,
    WorkContract,
)
from ..profile_session import require_active_profile
from ..schemas import (
    DocumentKind,
    UpdatePromptCenterRead,
    UpdatePromptIgnoreRead,
    UpdatePromptRead,
)
from .documents import document_center, set_document_resource_ignored

router = APIRouter(tags=["update-prompts"])

RECURRING_REVIEW_DAYS = 180
HOLDING_PRICE_REVIEW_DAYS = 30
HOLDING_OPERATION_REVIEW_DAYS = 90
REAL_ESTATE_REVIEW_DAYS = 365
DEBT_REVIEW_DAYS = 90
WORK_CONTRACT_REVIEW_DAYS = 365
PENSION_REVIEW_DAYS = 365

_PRIORITY_ORDER = {"important": 0, "review": 1, "suggestion": 2}
_RECURRENCE_DAYS = {
    "missing_account_statement": 30,
    "missing_recurring_amount": 30,
    "stale_recurring_amount": RECURRING_REVIEW_DAYS,
    "review_recurring_catalog": 90,
    "stale_holding_value": HOLDING_PRICE_REVIEW_DAYS,
    "stale_holding_operations": HOLDING_OPERATION_REVIEW_DAYS,
    "review_new_assets": 90,
    "stale_real_estate_value": REAL_ESTATE_REVIEW_DAYS,
    "stale_debt_balance": DEBT_REVIEW_DAYS,
    "stale_work_contract": WORK_CONTRACT_REVIEW_DAYS,
    "missing_payslip": 30,
    "stale_pension_profile": PENSION_REVIEW_DAYS,
}


def _as_date(value: datetime | None, fallback: datetime) -> date:
    return (value or fallback).date()


def _is_stale(value: datetime | None, fallback: datetime, cutoff: date) -> bool:
    return _as_date(value, fallback) <= cutoff


def _prompt(
    *,
    prompt_id: str,
    kind: str,
    priority: str,
    title: str,
    detail: str,
    action_label: str,
    target: str,
    resource_id: int | None = None,
    period: str | None = None,
    document_kind: DocumentKind | None = None,
) -> UpdatePromptRead:
    recurrence_days = _RECURRENCE_DAYS.get(kind)
    return UpdatePromptRead(
        id=prompt_id,
        kind=kind,
        priority=priority,
        title=title,
        detail=detail,
        action_label=action_label,
        target=target,
        resource_id=resource_id,
        period=period,
        document_kind=document_kind,
        ignore_mode="document" if document_kind is not None else "snooze",
        recurrence_days=recurrence_days,
    )


async def _build_update_prompts(
    session: AsyncSession,
    profile: Profile,
) -> list[UpdatePromptRead]:
    today = local_today()
    account_ids = await visible_account_ids(session, profile.id)
    accounts = list(
        (
            await session.scalars(
                select(Account)
                .where(Account.id.in_(account_ids), Account.archived.is_(False))
                .order_by(Account.name, Account.id)
            )
        ).all()
    ) if account_ids else []
    active_account_ids = {account.id for account in accounts}
    prompts: list[UpdatePromptRead] = []

    await _append_account_prompts(session, accounts, today, prompts)
    await _append_recurring_prompts(
        session, active_account_ids, today, prompts
    )
    await _append_holding_prompts(
        session, accounts, today, prompts
    )
    await _append_real_estate_prompts(session, profile.id, today, prompts)
    await _append_debt_prompts(session, profile.id, today, prompts)
    await _append_work_prompts(session, profile.id, today, prompts)
    await _append_document_prompts(session, profile, today, prompts)

    prompts.sort(
        key=lambda item: (
            _PRIORITY_ORDER[item.priority],
            item.title.casefold(),
            item.id,
        )
    )
    return prompts


@router.get("/update-prompts", response_model=UpdatePromptCenterRead)
async def get_update_prompts(
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> UpdatePromptCenterRead:
    prompts = await _build_update_prompts(session, profile)
    now = datetime.now(UTC)
    snoozed_ids = set(
        await session.scalars(
            select(UpdatePromptDismissal.prompt_id).where(
                UpdatePromptDismissal.profile_id == profile.id,
                UpdatePromptDismissal.snoozed_until > now,
            )
        )
    )
    return UpdatePromptCenterRead(
        generated_at=now,
        prompts=[prompt for prompt in prompts if prompt.id not in snoozed_ids],
    )


@router.post(
    "/update-prompts/{prompt_id}/ignore",
    response_model=UpdatePromptIgnoreRead,
)
async def ignore_update_prompt(
    prompt_id: str,
    profile: Profile = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> UpdatePromptIgnoreRead:
    prompt = next(
        (
            item
            for item in await _build_update_prompts(session, profile)
            if item.id == prompt_id
        ),
        None,
    )
    if prompt is None:
        raise HTTPException(status_code=404, detail="Demande de mise à jour introuvable")

    if prompt.ignore_mode == "document":
        if prompt.document_kind is None or prompt.resource_id is None:
            raise RuntimeError("Demande documentaire incomplète")
        await set_document_resource_ignored(
            kind=prompt.document_kind,
            resource_id=prompt.resource_id,
            ignored=True,
            profile=profile,
            session=session,
        )
        return UpdatePromptIgnoreRead(mode="document")

    if prompt.recurrence_days is None:
        raise RuntimeError("Cadence de rappel manquante")
    now = datetime.now(UTC)
    snoozed_until = now + timedelta(days=prompt.recurrence_days)
    dismissal = await session.scalar(
        select(UpdatePromptDismissal).where(
            UpdatePromptDismissal.profile_id == profile.id,
            UpdatePromptDismissal.prompt_id == prompt.id,
        )
    )
    if dismissal is None:
        session.add(
            UpdatePromptDismissal(
                profile_id=profile.id,
                prompt_id=prompt.id,
                snoozed_until=snoozed_until,
            )
        )
    else:
        dismissal.snoozed_until = snoozed_until
        dismissal.updated_at = now
    await session.commit()
    return UpdatePromptIgnoreRead(
        mode="snooze",
        snoozed_until=snoozed_until,
    )


async def _append_account_prompts(
    session: AsyncSession,
    accounts: list[Account],
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    expected_month = add_month(today.replace(day=1), -1)
    expected_period = expected_month.strftime("%Y-%m")
    month_end = today.replace(day=1) - timedelta(days=1)
    account_ids_with_history = set(
        await session.scalars(
            select(BalanceSnapshot.account_id).where(
                BalanceSnapshot.account_id.in_([account.id for account in accounts]),
                BalanceSnapshot.period <= expected_period,
            )
        )
    )
    eligible = [
        account
        for account in accounts
        if account.created_at.date() <= month_end
        or account.id in account_ids_with_history
    ]
    if not eligible:
        return
    covered_account_ids = set(
        await session.scalars(
            select(BalanceSnapshot.account_id).where(
                BalanceSnapshot.account_id.in_([account.id for account in eligible]),
                BalanceSnapshot.period == expected_period,
            )
        )
    )
    for account in eligible:
        if account.id in covered_account_ids:
            continue
        prompts.append(
            _prompt(
                prompt_id=f"missing-statement:{account.id}",
                kind="missing_account_statement",
                priority="important",
                title=f"Relevé {expected_period} manquant",
                detail=f"Ajoutez le solde mensuel de {account.name}.",
                action_label="Ajouter le relevé",
                target="account",
                resource_id=account.id,
                period=expected_period,
            )
        )


async def _append_recurring_prompts(
    session: AsyncSession,
    account_ids: set[int],
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    if not account_ids:
        return
    series = list(
        (
            await session.scalars(
                select(RecurringSeries)
                .where(
                    RecurringSeries.account_id.in_(account_ids),
                    RecurringSeries.status == "active",
                )
                .order_by(RecurringSeries.label, RecurringSeries.id)
            )
        ).all()
    )
    cutoff = today - timedelta(days=RECURRING_REVIEW_DAYS)
    for item in series:
        if item.amount is None:
            prompts.append(
                _prompt(
                    prompt_id=f"missing-recurring-amount:{item.id}",
                    kind="missing_recurring_amount",
                    priority="important",
                    title=f"Montant à compléter · {item.label}",
                    detail="Cette série active n’a pas encore de montant.",
                    action_label="Compléter",
                    target="recurring",
                    resource_id=item.id,
                )
            )
        elif _is_stale(item.amount_updated_at, item.created_at, cutoff):
            prompts.append(
                _prompt(
                    prompt_id=f"stale-recurring:{item.id}",
                    kind="stale_recurring_amount",
                    priority="review",
                    title=f"Budget à vérifier · {item.label}",
                    detail=(
                        "Confirmez son montant ou terminez la série si elle "
                        "n’est plus d’actualité."
                    ),
                    action_label="Vérifier",
                    target="recurring",
                    resource_id=item.id,
                )
            )
    prompts.append(
        _prompt(
            prompt_id="review-recurring-catalog",
            kind="review_recurring_catalog",
            priority="suggestion",
            title="De nouveaux récurrents ?",
            detail="Vérifiez si un revenu, abonnement ou prélèvement doit être ajouté.",
            action_label="Parcourir les récurrents",
            target="recurring",
        )
    )


async def _append_holding_prompts(
    session: AsyncSession,
    accounts: list[Account],
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    holding_account_ids = {
        account.id for account in accounts if account.type in HOLDING_ACCOUNT_TYPES
    }
    if not holding_account_ids:
        return
    holdings = list(
        (
            await session.scalars(
                select(Holding)
                .where(Holding.account_id.in_(holding_account_ids))
                .order_by(Holding.name, Holding.id)
            )
        ).all()
    )
    price_cutoff = today - timedelta(days=HOLDING_PRICE_REVIEW_DAYS)
    operation_cutoff = today - timedelta(days=HOLDING_OPERATION_REVIEW_DAYS)
    latest_operations = dict(
        (
            await session.execute(
                select(
                    HoldingOperation.holding_id,
                    func.max(HoldingOperation.occurred_on),
                )
                .where(HoldingOperation.holding_id.in_([item.id for item in holdings]))
                .group_by(HoldingOperation.holding_id)
            )
        ).all()
    ) if holdings else {}
    stale_operation_count = 0
    for holding in holdings:
        if holding.quantity <= 0:
            continue
        if _is_stale(holding.price_updated_at, holding.created_at, price_cutoff):
            prompts.append(
                _prompt(
                    prompt_id=f"stale-holding-price:{holding.id}",
                    kind="stale_holding_value",
                    priority="review",
                    title=f"Cours à actualiser · {holding.name}",
                    detail="La valeur de marché n’a pas été confirmée depuis 30 jours.",
                    action_label="Mettre à jour",
                    target="holdings",
                    resource_id=holding.id,
                )
            )
        last_operation = latest_operations.get(holding.id)
        if last_operation is None or last_operation <= operation_cutoff:
            stale_operation_count += 1
    if stale_operation_count:
        prompts.append(
            _prompt(
                prompt_id="stale-holding-operations",
                kind="stale_holding_operations",
                priority="review",
                title="Opérations sur les actifs à vérifier",
                detail=(
                    f"{stale_operation_count} position"
                    f"{'s' if stale_operation_count > 1 else ''} sans opération récente."
                ),
                action_label="Voir les opérations",
                target="holding_operations",
            )
        )
    prompts.append(
        _prompt(
            prompt_id="review-new-assets",
            kind="review_new_assets",
            priority="suggestion",
            title="De nouveaux actifs ?",
            detail="Ajoutez les placements récemment acquis pour garder le patrimoine complet.",
            action_label="Parcourir les actifs",
            target="holdings",
        )
    )


async def _append_real_estate_prompts(
    session: AsyncSession,
    profile_id: int,
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    assets = list(
        (
            await session.scalars(
                select(RealEstateAsset)
                .join(
                    RealEstateAssetOwner,
                    RealEstateAssetOwner.asset_id == RealEstateAsset.id,
                )
                .where(RealEstateAssetOwner.member_id == profile_id)
                .order_by(RealEstateAsset.name, RealEstateAsset.id)
            )
        ).all()
    )
    cutoff = today - timedelta(days=REAL_ESTATE_REVIEW_DAYS)
    for asset in assets:
        missing = asset.current_value is None
        if not missing and not _is_stale(
            asset.value_updated_at, asset.created_at, cutoff
        ):
            continue
        prompts.append(
            _prompt(
                prompt_id=f"real-estate-value:{asset.id}",
                kind="stale_real_estate_value",
                priority="important" if missing else "review",
                title=f"Valeur immobilière à {'compléter' if missing else 'vérifier'}",
                detail=f"Actualisez l’estimation de {asset.name}.",
                action_label="Mettre à jour",
                target="real_estate",
                resource_id=asset.id,
            )
        )


async def _append_debt_prompts(
    session: AsyncSession,
    profile_id: int,
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    debts = list(
        (
            await session.scalars(
                select(Debt)
                .join(DebtOwner, DebtOwner.debt_id == Debt.id)
                .where(
                    DebtOwner.member_id == profile_id,
                    Debt.archived.is_(False),
                    Debt.balance > 0,
                )
                .order_by(Debt.name, Debt.id)
            )
        ).all()
    )
    cutoff = today - timedelta(days=DEBT_REVIEW_DAYS)
    for debt in debts:
        if not _is_stale(debt.balance_updated_at, debt.created_at, cutoff):
            continue
        prompts.append(
            _prompt(
                prompt_id=f"stale-debt-balance:{debt.id}",
                kind="stale_debt_balance",
                priority="review",
                title=f"Capital restant à actualiser · {debt.name}",
                detail="Le solde de cette dette n’a pas été confirmé depuis 90 jours.",
                action_label="Mettre à jour",
                target="debts",
                resource_id=debt.id,
            )
        )


async def _append_work_prompts(
    session: AsyncSession,
    profile_id: int,
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    contracts = list(
        (
            await session.scalars(
                select(WorkContract)
                .where(
                    WorkContract.profile_id == profile_id,
                    WorkContract.status == "active",
                )
                .order_by(WorkContract.employer, WorkContract.id)
            )
        ).all()
    )
    contract_cutoff = today - timedelta(days=WORK_CONTRACT_REVIEW_DAYS)
    for contract in contracts:
        if _is_stale(contract.updated_at, contract.created_at, contract_cutoff):
            prompts.append(
                _prompt(
                    prompt_id=f"stale-work-contract:{contract.id}",
                    kind="stale_work_contract",
                    priority="review",
                    title=f"Contrat à vérifier · {contract.employer}",
                    detail="Salaire, poste et temps de travail n’ont pas été confirmés depuis un an.",
                    action_label="Vérifier le contrat",
                    target="work_contract",
                    resource_id=contract.id,
                )
            )

    if contracts:
        expected_month = add_month(today.replace(day=1), -1)
        expected_period = expected_month.strftime("%Y-%m")
        expected_month_end = today.replace(day=1) - timedelta(days=1)
        eligible_contracts = [
            contract
            for contract in contracts
            if contract.start_date <= expected_month_end
            and (
                contract.end_date is None
                or contract.end_date >= expected_month
            )
        ]
        has_payslip = await session.scalar(
            select(PaySlip.id)
            .where(
                PaySlip.profile_id == profile_id,
                PaySlip.period == expected_period,
            )
            .limit(1)
        )
        if eligible_contracts and has_payslip is None:
            prompts.append(
                _prompt(
                    prompt_id=f"missing-payslip:{profile_id}",
                    kind="missing_payslip",
                    priority="important",
                    title=f"Fiche de paie {expected_period} manquante",
                    detail="Ajoutez le dernier bulletin pour actualiser salaire et retraite.",
                    action_label="Ajouter la fiche",
                    target="payslips",
                    period=expected_period,
                )
            )

    pension = await session.scalar(
        select(PensionProfile).where(PensionProfile.profile_id == profile_id)
    )
    if pension is not None and pension.updated_at.date() <= (
        today - timedelta(days=PENSION_REVIEW_DAYS)
    ):
        prompts.append(
            _prompt(
                prompt_id=f"stale-pension:{pension.id}",
                kind="stale_pension_profile",
                priority="review",
                title="Projection retraite à actualiser",
                detail="Confirmez vos trimestres et votre objectif de revenu annuel.",
                action_label="Mettre à jour",
                target="pension",
                resource_id=pension.id,
            )
        )


async def _append_document_prompts(
    session: AsyncSession,
    profile: Profile,
    today: date,
    prompts: list[UpdatePromptRead],
) -> None:
    resources = (
        await document_center(profile=profile, session=session)
    ).resources_without_documents
    previous_period = add_month(today.replace(day=1), -1).strftime("%Y-%m")
    active_recurring_ids = set(
        await session.scalars(
            select(RecurringSeries.id).where(RecurringSeries.status == "active")
        )
    )
    open_debt_ids = set(
        await session.scalars(
            select(Debt.id).where(
                Debt.archived.is_(False),
                Debt.balance > 0,
            )
        )
    )
    active_contract_ids = set(
        await session.scalars(
            select(WorkContract.id).where(WorkContract.status == "active")
        )
    )
    for resource in resources:
        if not resource.can_upload:
            continue
        if resource.kind == "snapshot" and resource.reference != previous_period:
            continue
        if (
            resource.kind == "recurring"
            and resource.resource_id not in active_recurring_ids
        ):
            continue
        if resource.kind == "debt" and resource.resource_id not in open_debt_ids:
            continue
        if (
            resource.kind == "work_contract"
            and resource.resource_id not in active_contract_ids
        ):
            continue
        if resource.kind == "payslip" and resource.reference != previous_period:
            continue
        context = resource.context
        if resource.reference:
            context = f"{context} · {resource.reference}"
        prompts.append(
            _prompt(
                prompt_id=f"missing-document:{resource.kind}:{resource.resource_id}",
                kind="missing_documents",
                priority="suggestion",
                title=f"Document manquant · {resource.label}",
                detail=context,
                action_label="Ajouter le document",
                target="documents",
                resource_id=resource.resource_id,
                document_kind=resource.kind,
            )
        )
