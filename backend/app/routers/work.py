"""Work module: contracts, pay slips, attachments, pension profile & summary."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..account_access import require_account, require_active_profile
from ..attachments import attachment_path, remove_attachment, store_attachment
from ..common import local_today
from ..db import get_session
from ..models import (
    HouseholdMember,
    PaySlip,
    PaySlipAttachment,
    PensionProfile,
    RecurringSeries,
    WorkContract,
    WorkContractAttachment,
    utc_now,
)
from ..pension_projection import calculate_pension_projection
from ..pension_quarters import calculate_payslip_quarters
from ..schemas import (
    PaySlipAttachmentRead,
    PaySlipCreate,
    PaySlipRead,
    PaySlipUpdate,
    PensionProfileCreateOrUpdate,
    PensionProfileRead,
    PensionProjectionRead,
    PensionQuarterYearRead,
    WorkContractAttachmentRead,
    WorkContractCreate,
    WorkContractRead,
    WorkContractUpdate,
    WorkSummary,
)

router = APIRouter(prefix="/work", tags=["work"])

ZERO = Decimal("0.00")


def _pension_read(
    profile: PensionProfile,
    slips: list[PaySlip],
) -> PensionProfileRead:
    calculation, unsupported_years = calculate_payslip_quarters(slips)
    payslip_quarters = sum(item.validated_quarters for item in calculation)
    projection = calculate_pension_projection(
        slips,
        birth_year=profile.birth_year,
        birth_month=profile.birth_month,
        target_retirement_age=profile.target_retirement_age,
        current_quarters=profile.validated_quarters + payslip_quarters,
        required_quarters=profile.required_quarters,
        today=local_today(),
        income_growth_scenario=profile.income_growth_scenario,
        target_monthly_income=profile.target_monthly_income,
        future_work_percentage=profile.future_work_percentage,
        planned_unemployment_months=profile.planned_unemployment_months,
    )
    return PensionProfileRead.model_validate(profile).model_copy(
        update={
            "payslip_quarters": payslip_quarters,
            "estimated_total_quarters": profile.validated_quarters
            + payslip_quarters,
            "quarter_calculation": [
                PensionQuarterYearRead(
                    year=item.year,
                    gross_salary=item.gross_salary,
                    quarter_threshold=item.quarter_threshold,
                    validated_quarters=item.validated_quarters,
                    next_quarter_remaining=item.next_quarter_remaining,
                )
                for item in calculation
            ],
            "unsupported_payslip_years": unsupported_years,
            "projection": (
                PensionProjectionRead.model_validate(projection)
                if projection
                else None
            ),
        }
    )


async def _require_visible_recurring_series(
    session: AsyncSession,
    recurring_series_id: int,
    profile_id: int,
) -> None:
    series = await session.get(RecurringSeries, recurring_series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Récurrence budgetaire non trouvee")
    await require_account(session, series.account_id, profile_id=profile_id)


@router.get("/summary", response_model=WorkSummary)
async def get_work_summary(
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> WorkSummary:
    today = local_today()
    current_year = today.year

    # Active contracts
    res_contracts = await session.execute(
        select(WorkContract).where(
            WorkContract.profile_id == profile.id,
            WorkContract.status == "active",
        )
    )
    active_contracts = res_contracts.scalars().all()

    # Payslips
    res_slips = await session.execute(
        select(PaySlip)
        .where(PaySlip.profile_id == profile.id)
        .order_by(PaySlip.period.desc())
    )
    slips = res_slips.scalars().all()

    latest_net = slips[0].net_after_tax if slips else ZERO

    ytd_slips = [s for s in slips if s.period.startswith(str(current_year))]

    ytd_taxable_net = sum((s.taxable_net for s in ytd_slips), ZERO)
    ytd_net_after_tax = sum((s.net_after_tax for s in ytd_slips), ZERO)
    ytd_gross = sum((s.gross_salary for s in ytd_slips), ZERO)
    ytd_bonuses = sum((s.bonuses for s in ytd_slips), ZERO)
    ytd_profit_sharing = sum((s.employer_profit_sharing for s in ytd_slips), ZERO)

    if ytd_slips:
        avg_pas = sum((s.pas_rate for s in ytd_slips), ZERO) / Decimal(len(ytd_slips))
    elif slips:
        avg_pas = slips[0].pas_rate
    else:
        avg_pas = ZERO

    # Pension
    res_pension = await session.execute(
        select(PensionProfile).where(PensionProfile.profile_id == profile.id)
    )
    pension = res_pension.scalar_one_or_none()

    declared_val_q = pension.validated_quarters if pension else 0
    quarter_calculation, _ = calculate_payslip_quarters(slips)
    payslip_quarters = sum(item.validated_quarters for item in quarter_calculation)
    req_q = pension.required_quarters if pension else 172
    projection = (
        calculate_pension_projection(
            slips,
            birth_year=pension.birth_year,
            birth_month=pension.birth_month,
            target_retirement_age=pension.target_retirement_age,
            current_quarters=declared_val_q + payslip_quarters,
            required_quarters=req_q,
            today=today,
            income_growth_scenario=pension.income_growth_scenario,
            target_monthly_income=pension.target_monthly_income,
            future_work_percentage=pension.future_work_percentage,
            planned_unemployment_months=pension.planned_unemployment_months,
        )
        if pension
        else None
    )
    legal_projection = next(
        (
            scenario
            for scenario in projection.scenarios
            if scenario.kind == "legal_age"
        ),
        None,
    ) if projection else None
    est_pension = (
        legal_projection.total_monthly_pension
        if legal_projection
        else ZERO
    )

    return WorkSummary(
        active_contracts_count=len(active_contracts),
        latest_net_after_tax=latest_net,
        ytd_taxable_net=ytd_taxable_net,
        ytd_net_after_tax=ytd_net_after_tax,
        ytd_gross=ytd_gross,
        ytd_bonuses=ytd_bonuses,
        ytd_profit_sharing=ytd_profit_sharing,
        average_pas_rate=round(avg_pas, 2),
        estimated_pension=est_pension,
        declared_validated_quarters=declared_val_q,
        payslip_quarters=payslip_quarters,
        validated_quarters=declared_val_q + payslip_quarters,
        required_quarters=req_q,
    )


# --------------------------------------------------------------------------- #
# Contracts
# --------------------------------------------------------------------------- #
def _contract_read(contract: WorkContract) -> WorkContractRead:
    return WorkContractRead.model_validate(contract).model_copy(
        update={"attachment_count": len(contract.attachments)}
    )


@router.get("/contracts", response_model=list[WorkContractRead])
async def list_contracts(
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[WorkContractRead]:
    res = await session.execute(
        select(WorkContract)
        .options(selectinload(WorkContract.attachments))
        .where(WorkContract.profile_id == profile.id)
        .order_by(WorkContract.status.asc(), WorkContract.start_date.desc())
    )
    return [_contract_read(contract) for contract in res.scalars().all()]


@router.post("/contracts", response_model=WorkContractRead, status_code=201)
async def create_contract(
    data: WorkContractCreate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> WorkContractRead:
    payload = data.model_dump()
    recurring_series_id = payload.get("recurring_series_id")
    if recurring_series_id is not None:
        await _require_visible_recurring_series(
            session,
            recurring_series_id,
            profile.id,
        )
    contract = WorkContract(profile_id=profile.id, **payload)
    session.add(contract)
    await session.commit()
    res = await session.execute(
        select(WorkContract)
        .options(selectinload(WorkContract.attachments))
        .where(
            WorkContract.id == contract.id,
            WorkContract.profile_id == profile.id,
        )
    )
    return _contract_read(res.scalar_one())


@router.get("/contracts/{contract_id}", response_model=WorkContractRead)
async def get_contract(
    contract_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> WorkContractRead:
    contract = (
        await session.execute(
            select(WorkContract)
            .options(selectinload(WorkContract.attachments))
            .where(
                WorkContract.id == contract_id,
                WorkContract.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")
    return _contract_read(contract)


@router.patch("/contracts/{contract_id}", response_model=WorkContractRead)
async def update_contract(
    contract_id: int,
    data: WorkContractUpdate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> WorkContractRead:
    contract = (
        await session.execute(
            select(WorkContract)
            .options(selectinload(WorkContract.attachments))
            .where(
                WorkContract.id == contract_id,
                WorkContract.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")

    payload = data.model_dump(exclude_unset=True)
    if (
        "recurring_series_id" in payload
        and payload["recurring_series_id"] is not None
    ):
        await _require_visible_recurring_series(
            session,
            payload["recurring_series_id"],
            profile.id,
        )
    for key, value in payload.items():
        setattr(contract, key, value)
    contract.updated_at = utc_now()

    await session.commit()
    await session.refresh(contract)
    return _contract_read(contract)


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract(
    contract_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    contract = (
        await session.execute(
            select(WorkContract)
            .options(selectinload(WorkContract.attachments))
            .where(
                WorkContract.id == contract_id,
                WorkContract.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")
    for attachment in contract.attachments:
        remove_attachment(attachment.stored_path)
    await session.delete(contract)
    await session.commit()


@router.post(
    "/contracts/{contract_id}/attachments",
    response_model=WorkContractAttachmentRead,
    status_code=201,
)
async def upload_contract_attachment(
    contract_id: int,
    file: UploadFile = File(...),
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> WorkContractAttachment:
    contract = await session.scalar(
        select(WorkContract).where(
            WorkContract.id == contract_id,
            WorkContract.profile_id == profile.id,
        )
    )
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")

    original_name, stored_path, size = await store_attachment(file)
    attachment = WorkContractAttachment(
        contract_id=contract.id,
        original_name=original_name,
        stored_path=stored_path,
        content_type=file.content_type,
        size=size,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return attachment


@router.get(
    "/contracts/{contract_id}/attachments",
    response_model=list[WorkContractAttachmentRead],
)
async def list_contract_attachments(
    contract_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[WorkContractAttachment]:
    contract = await session.scalar(
        select(WorkContract).where(
            WorkContract.id == contract_id,
            WorkContract.profile_id == profile.id,
        )
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Contrat non trouve")
    return list(
        (
            await session.scalars(
                select(WorkContractAttachment)
                .where(WorkContractAttachment.contract_id == contract_id)
                .order_by(
                    WorkContractAttachment.created_at.desc(),
                    WorkContractAttachment.id.desc(),
                )
            )
        ).all()
    )


async def _require_contract_attachment(
    session: AsyncSession,
    contract_id: int,
    attachment_id: int,
    profile_id: int,
) -> WorkContractAttachment:
    attachment = (
        await session.execute(
            select(WorkContractAttachment)
            .join(WorkContract)
            .where(
                WorkContractAttachment.id == attachment_id,
                WorkContractAttachment.contract_id == contract_id,
                WorkContract.profile_id == profile_id,
            )
        )
    ).scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Piece jointe non trouvee")
    return attachment


def _contract_attachment_response(
    attachment: WorkContractAttachment,
) -> FileResponse:
    file_path = attachment_path(attachment.stored_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(
        path=file_path,
        filename=attachment.original_name,
        media_type=attachment.content_type or "application/octet-stream",
    )


@router.get(
    "/contracts/{contract_id}/attachments/{attachment_id}/download"
)
async def download_contract_attachment(
    contract_id: int,
    attachment_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_contract_attachment(
        session,
        contract_id,
        attachment_id,
        profile.id,
    )
    return _contract_attachment_response(attachment)


@router.delete(
    "/contracts/{contract_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_contract_attachment(
    contract_id: int,
    attachment_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    attachment = await _require_contract_attachment(
        session,
        contract_id,
        attachment_id,
        profile.id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


# --------------------------------------------------------------------------- #
# Pay slips
# --------------------------------------------------------------------------- #
@router.get("/payslips", response_model=list[PaySlipRead])
async def list_payslips(
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[PaySlip]:
    res = await session.execute(
        select(PaySlip)
        .options(selectinload(PaySlip.attachments))
        .where(PaySlip.profile_id == profile.id)
        .order_by(PaySlip.period.desc())
    )
    return list(res.scalars().all())


@router.post("/payslips", response_model=PaySlipRead, status_code=201)
async def create_payslip(
    data: PaySlipCreate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PaySlip:
    if data.contract_id:
        contract = await session.scalar(
            select(WorkContract).where(
                WorkContract.id == data.contract_id,
                WorkContract.profile_id == profile.id,
            )
        )
        if not contract:
            raise HTTPException(status_code=404, detail="Contrat non trouve")

    payslip = PaySlip(profile_id=profile.id, **data.model_dump())
    session.add(payslip)
    await session.commit()
    res = await session.execute(
        select(PaySlip)
        .options(selectinload(PaySlip.attachments))
        .where(PaySlip.id == payslip.id, PaySlip.profile_id == profile.id)
    )
    return res.scalar_one()


@router.get("/payslips/{payslip_id}", response_model=PaySlipRead)
async def get_payslip(
    payslip_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PaySlip:
    res = await session.execute(
        select(PaySlip)
        .options(selectinload(PaySlip.attachments))
        .where(PaySlip.id == payslip_id, PaySlip.profile_id == profile.id)
    )
    payslip = res.scalar_one_or_none()
    if not payslip:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")
    return payslip


@router.patch("/payslips/{payslip_id}", response_model=PaySlipRead)
async def update_payslip(
    payslip_id: int,
    data: PaySlipUpdate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PaySlip:
    res = await session.execute(
        select(PaySlip)
        .options(selectinload(PaySlip.attachments))
        .where(PaySlip.id == payslip_id, PaySlip.profile_id == profile.id)
    )
    payslip = res.scalar_one_or_none()
    if not payslip:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")

    payload = data.model_dump(exclude_unset=True)
    if "contract_id" in payload and payload["contract_id"] is not None:
        contract = await session.scalar(
            select(WorkContract).where(
                WorkContract.id == payload["contract_id"],
                WorkContract.profile_id == profile.id,
            )
        )
        if not contract:
            raise HTTPException(status_code=404, detail="Contrat non trouve")

    for key, value in payload.items():
        setattr(payslip, key, value)

    await session.commit()
    res = await session.execute(
        select(PaySlip)
        .options(selectinload(PaySlip.attachments))
        .where(PaySlip.id == payslip_id, PaySlip.profile_id == profile.id)
    )
    return res.scalar_one()


@router.delete("/payslips/{payslip_id}", status_code=204)
async def delete_payslip(
    payslip_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    res = await session.execute(
        select(PaySlip)
        .options(selectinload(PaySlip.attachments))
        .where(PaySlip.id == payslip_id, PaySlip.profile_id == profile.id)
    )
    payslip = res.scalar_one_or_none()
    if not payslip:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")

    for att in payslip.attachments:
        remove_attachment(att.stored_path)

    await session.delete(payslip)
    await session.commit()


@router.post("/payslips/{payslip_id}/attachments", response_model=PaySlipAttachmentRead, status_code=201)
async def upload_payslip_attachment(
    payslip_id: int,
    file: UploadFile = File(...),
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PaySlipAttachment:
    payslip = await session.scalar(
        select(PaySlip).where(
            PaySlip.id == payslip_id,
            PaySlip.profile_id == profile.id,
        )
    )
    if not payslip:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")

    original_name, stored_path, size = await store_attachment(file)
    att = PaySlipAttachment(
        payslip_id=payslip.id,
        original_name=original_name,
        stored_path=stored_path,
        content_type=file.content_type,
        size=size,
    )
    session.add(att)
    await session.commit()
    await session.refresh(att)
    return att


@router.get(
    "/payslips/{payslip_id}/attachments",
    response_model=list[PaySlipAttachmentRead],
)
async def list_payslip_attachments(
    payslip_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[PaySlipAttachment]:
    payslip = await session.scalar(
        select(PaySlip).where(
            PaySlip.id == payslip_id,
            PaySlip.profile_id == profile.id,
        )
    )
    if payslip is None:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")
    return list(
        (
            await session.scalars(
                select(PaySlipAttachment)
                .where(PaySlipAttachment.payslip_id == payslip_id)
                .order_by(PaySlipAttachment.created_at.desc(), PaySlipAttachment.id.desc())
            )
        ).all()
    )


async def _require_payslip_attachment(
    session: AsyncSession,
    payslip_id: int,
    attachment_id: int,
    profile_id: int,
) -> PaySlipAttachment:
    attachment = (
        await session.execute(
            select(PaySlipAttachment)
            .join(PaySlip)
            .where(
                PaySlipAttachment.id == attachment_id,
                PaySlipAttachment.payslip_id == payslip_id,
                PaySlip.profile_id == profile_id,
            )
        )
    ).scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Piece jointe non trouvee")
    return attachment


def _attachment_response(attachment: PaySlipAttachment) -> FileResponse:
    file_path = attachment_path(attachment.stored_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(
        path=file_path,
        filename=attachment.original_name,
        media_type=attachment.content_type or "application/octet-stream",
    )


@router.get("/payslips/{payslip_id}/attachments/{attachment_id}/download")
async def download_payslip_attachment(
    payslip_id: int,
    attachment_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_payslip_attachment(
        session,
        payslip_id,
        attachment_id,
        profile.id,
    )
    return _attachment_response(attachment)


@router.delete(
    "/payslips/{payslip_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_nested_payslip_attachment(
    payslip_id: int,
    attachment_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    attachment = await _require_payslip_attachment(
        session,
        payslip_id,
        attachment_id,
        profile.id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


@router.get("/attachments/{attachment_id}")
async def get_payslip_attachment(
    attachment_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    att = await session.scalar(
        select(PaySlipAttachment)
        .join(PaySlip)
        .where(
            PaySlipAttachment.id == attachment_id,
            PaySlip.profile_id == profile.id,
        )
    )
    if not att:
        raise HTTPException(status_code=404, detail="Piece jointe non trouvee")
    return _attachment_response(att)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_payslip_attachment(
    attachment_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    att = await session.scalar(
        select(PaySlipAttachment)
        .join(PaySlip)
        .where(
            PaySlipAttachment.id == attachment_id,
            PaySlip.profile_id == profile.id,
        )
    )
    if not att:
        raise HTTPException(status_code=404, detail="Piece jointe non trouvee")

    remove_attachment(att.stored_path)
    await session.delete(att)
    await session.commit()


# --------------------------------------------------------------------------- #
# Pension Profile
# --------------------------------------------------------------------------- #
@router.get("/pension", response_model=PensionProfileRead)
async def get_pension_profile(
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PensionProfileRead:
    res = await session.execute(
        select(PensionProfile).where(PensionProfile.profile_id == profile.id)
    )
    pension_profile = res.scalar_one_or_none()
    if not pension_profile:
        pension_profile = PensionProfile(profile_id=profile.id)
        session.add(pension_profile)
        await session.commit()
        await session.refresh(pension_profile)
    res_slips = await session.execute(
        select(PaySlip).where(PaySlip.profile_id == profile.id)
    )
    return _pension_read(pension_profile, list(res_slips.scalars().all()))


@router.put("/pension", response_model=PensionProfileRead)
async def update_pension_profile(
    data: PensionProfileCreateOrUpdate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> PensionProfileRead:
    res = await session.execute(
        select(PensionProfile).where(PensionProfile.profile_id == profile.id)
    )
    pension_profile = res.scalar_one_or_none()
    if not pension_profile:
        pension_profile = PensionProfile(profile_id=profile.id)
        session.add(pension_profile)

    for key, value in data.model_dump().items():
        setattr(pension_profile, key, value)

    pension_profile.updated_at = utc_now()
    await session.commit()
    await session.refresh(pension_profile)
    res_slips = await session.execute(
        select(PaySlip).where(PaySlip.profile_id == profile.id)
    )
    return _pension_read(pension_profile, list(res_slips.scalars().all()))
