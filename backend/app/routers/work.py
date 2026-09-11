"""Work module: contracts, pay slips, attachments, pension profile & summary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..attachments import attachment_path, remove_attachment, store_attachment
from ..common import local_today
from ..db import get_session
from ..models import PaySlip, PaySlipAttachment, PensionProfile, RecurringSeries, WorkContract
from ..schemas import (
    PaySlipAttachmentRead,
    PaySlipCreate,
    PaySlipRead,
    PaySlipUpdate,
    PensionProfileCreateOrUpdate,
    PensionProfileRead,
    WorkContractCreate,
    WorkContractRead,
    WorkContractUpdate,
    WorkSummary,
)

router = APIRouter(prefix="/work", tags=["work"])

ZERO = Decimal("0.00")


@router.get("/summary", response_model=WorkSummary)
async def get_work_summary(
    session: AsyncSession = Depends(get_session),
) -> WorkSummary:
    today = local_today()
    current_year = today.year

    # Active contracts
    res_contracts = await session.execute(
        select(WorkContract).where(WorkContract.status == "active")
    )
    active_contracts = res_contracts.scalars().all()

    # Payslips
    res_slips = await session.execute(
        select(PaySlip).order_by(PaySlip.period.desc())
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
    res_pension = await session.execute(select(PensionProfile).limit(1))
    pension = res_pension.scalar_one_or_none()

    est_pension = pension.estimated_monthly_pension if pension else ZERO
    val_q = pension.validated_quarters if pension else 0
    req_q = pension.required_quarters if pension else 172

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
        validated_quarters=val_q,
        required_quarters=req_q,
    )


# --------------------------------------------------------------------------- #
# Contracts
# --------------------------------------------------------------------------- #
@router.get("/contracts", response_model=list[WorkContractRead])
async def list_contracts(
    session: AsyncSession = Depends(get_session),
) -> list[WorkContract]:
    res = await session.execute(
        select(WorkContract).order_by(WorkContract.status.asc(), WorkContract.start_date.desc())
    )
    return list(res.scalars().all())


@router.post("/contracts", response_model=WorkContractRead, status_code=201)
async def create_contract(
    data: WorkContractCreate,
    session: AsyncSession = Depends(get_session),
) -> WorkContract:
    payload = data.model_dump()
    recurring_series_id = payload.get("recurring_series_id")
    if recurring_series_id is not None and not await session.get(RecurringSeries, recurring_series_id):
        raise HTTPException(status_code=404, detail="Récurrence budgetaire non trouvee")
    contract = WorkContract(**payload)
    session.add(contract)
    await session.commit()
    await session.refresh(contract)
    return contract


@router.get("/contracts/{contract_id}", response_model=WorkContractRead)
async def get_contract(
    contract_id: int,
    session: AsyncSession = Depends(get_session),
) -> WorkContract:
    contract = await session.get(WorkContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")
    return contract


@router.patch("/contracts/{contract_id}", response_model=WorkContractRead)
async def update_contract(
    contract_id: int,
    data: WorkContractUpdate,
    session: AsyncSession = Depends(get_session),
) -> WorkContract:
    contract = await session.get(WorkContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")

    payload = data.model_dump(exclude_unset=True)
    if (
        "recurring_series_id" in payload
        and payload["recurring_series_id"] is not None
        and not await session.get(RecurringSeries, payload["recurring_series_id"])
    ):
        raise HTTPException(status_code=404, detail="Récurrence budgetaire non trouvee")
    for key, value in payload.items():
        setattr(contract, key, value)

    await session.commit()
    await session.refresh(contract)
    return contract


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract(
    contract_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    contract = await session.get(WorkContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contrat non trouve")
    await session.delete(contract)
    await session.commit()


# --------------------------------------------------------------------------- #
# Pay slips
# --------------------------------------------------------------------------- #
@router.get("/payslips", response_model=list[PaySlipRead])
async def list_payslips(
    session: AsyncSession = Depends(get_session),
) -> list[PaySlip]:
    res = await session.execute(
        select(PaySlip).options(selectinload(PaySlip.attachments)).order_by(PaySlip.period.desc())
    )
    return list(res.scalars().all())


@router.post("/payslips", response_model=PaySlipRead, status_code=201)
async def create_payslip(
    data: PaySlipCreate,
    session: AsyncSession = Depends(get_session),
) -> PaySlip:
    if data.contract_id:
        contract = await session.get(WorkContract, data.contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contrat non trouve")

    payslip = PaySlip(**data.model_dump())
    session.add(payslip)
    await session.commit()
    res = await session.execute(
        select(PaySlip).options(selectinload(PaySlip.attachments)).where(PaySlip.id == payslip.id)
    )
    return res.scalar_one()


@router.get("/payslips/{payslip_id}", response_model=PaySlipRead)
async def get_payslip(
    payslip_id: int,
    session: AsyncSession = Depends(get_session),
) -> PaySlip:
    res = await session.execute(
        select(PaySlip).options(selectinload(PaySlip.attachments)).where(PaySlip.id == payslip_id)
    )
    payslip = res.scalar_one_or_none()
    if not payslip:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")
    return payslip


@router.patch("/payslips/{payslip_id}", response_model=PaySlipRead)
async def update_payslip(
    payslip_id: int,
    data: PaySlipUpdate,
    session: AsyncSession = Depends(get_session),
) -> PaySlip:
    res = await session.execute(
        select(PaySlip).options(selectinload(PaySlip.attachments)).where(PaySlip.id == payslip_id)
    )
    payslip = res.scalar_one_or_none()
    if not payslip:
        raise HTTPException(status_code=404, detail="Fiche de paie non trouvee")

    payload = data.model_dump(exclude_unset=True)
    if "contract_id" in payload and payload["contract_id"] is not None:
        contract = await session.get(WorkContract, payload["contract_id"])
        if not contract:
            raise HTTPException(status_code=404, detail="Contrat non trouve")

    for key, value in payload.items():
        setattr(payslip, key, value)

    await session.commit()
    res = await session.execute(
        select(PaySlip).options(selectinload(PaySlip.attachments)).where(PaySlip.id == payslip_id)
    )
    return res.scalar_one()


@router.delete("/payslips/{payslip_id}", status_code=204)
async def delete_payslip(
    payslip_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    res = await session.execute(
        select(PaySlip).options(selectinload(PaySlip.attachments)).where(PaySlip.id == payslip_id)
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
    session: AsyncSession = Depends(get_session),
) -> PaySlipAttachment:
    payslip = await session.get(PaySlip, payslip_id)
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
    session: AsyncSession = Depends(get_session),
) -> list[PaySlipAttachment]:
    if await session.get(PaySlip, payslip_id) is None:
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
) -> PaySlipAttachment:
    attachment = (
        await session.execute(
            select(PaySlipAttachment).where(
                PaySlipAttachment.id == attachment_id,
                PaySlipAttachment.payslip_id == payslip_id,
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
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_payslip_attachment(
        session,
        payslip_id,
        attachment_id,
    )
    return _attachment_response(attachment)


@router.delete(
    "/payslips/{payslip_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_nested_payslip_attachment(
    payslip_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    attachment = await _require_payslip_attachment(
        session,
        payslip_id,
        attachment_id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


@router.get("/attachments/{attachment_id}")
async def get_payslip_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    att = await session.get(PaySlipAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Piece jointe non trouvee")
    return _attachment_response(att)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_payslip_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    att = await session.get(PaySlipAttachment, attachment_id)
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
    session: AsyncSession = Depends(get_session),
) -> PensionProfile:
    res = await session.execute(select(PensionProfile).limit(1))
    profile = res.scalar_one_or_none()
    if not profile:
        profile = PensionProfile()
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


@router.put("/pension", response_model=PensionProfileRead)
async def update_pension_profile(
    data: PensionProfileCreateOrUpdate,
    session: AsyncSession = Depends(get_session),
) -> PensionProfile:
    res = await session.execute(select(PensionProfile).limit(1))
    profile = res.scalar_one_or_none()
    if not profile:
        profile = PensionProfile()
        session.add(profile)

    for key, value in data.model_dump().items():
        setattr(profile, key, value)

    profile.updated_at = datetime.now()
    await session.commit()
    await session.refresh(profile)
    return profile
