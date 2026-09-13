"""Cross-domain document index for every resource that supports attachments."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import (
    Account,
    BalanceSnapshot,
    BalanceSnapshotAttachment,
    Debt,
    DebtAttachment,
    PaySlip,
    PaySlipAttachment,
    RealEstateAsset,
    RealEstateAttachment,
    RecurringSeries,
    RecurringSeriesAttachment,
    WorkContract,
    WorkContractAttachment,
)
from ..schemas import (
    DocumentCenterRead,
    DocumentCenterStats,
    DocumentKind,
    DocumentKindSummary,
    DocumentRead,
    DocumentResourceRead,
)

router = APIRouter(tags=["documents"])

KIND_LABELS: dict[DocumentKind, str] = {
    "snapshot": "Relevés de compte",
    "recurring": "Récurrents",
    "debt": "Dettes",
    "real_estate": "Biens immobiliers",
    "work_contract": "Contrats de travail",
    "payslip": "Fiches de paie",
}

DOCUMENT_RESOURCE_MODELS = {
    "snapshot": (BalanceSnapshot, BalanceSnapshotAttachment.snapshot_id),
    "recurring": (RecurringSeries, RecurringSeriesAttachment.series_id),
    "debt": (Debt, DebtAttachment.debt_id),
    "real_estate": (RealEstateAsset, RealEstateAttachment.asset_id),
    "work_contract": (WorkContract, WorkContractAttachment.contract_id),
    "payslip": (PaySlip, PaySlipAttachment.payslip_id),
}


@router.post(
    "/documents/resources/{kind}/{resource_id}/ignored",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def set_document_resource_ignored(
    kind: DocumentKind,
    resource_id: int,
    ignored: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
) -> Response:
    resource_model, attachment_resource_id = DOCUMENT_RESOURCE_MODELS[kind]
    resource = await session.get(resource_model, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Ressource documentaire introuvable")

    if ignored:
        attachment_exists = await session.scalar(
            select(attachment_resource_id)
            .where(attachment_resource_id == resource_id)
            .limit(1)
        )
        if attachment_exists is not None:
            raise HTTPException(
                status_code=409,
                detail="Une ressource avec document ne peut pas être ignorée",
            )

    resource.document_ignored = ignored
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents", response_model=DocumentCenterRead)
async def document_center(
    session: AsyncSession = Depends(get_session),
) -> DocumentCenterRead:
    documents: list[DocumentRead] = []
    resources: list[DocumentResourceRead] = []
    covered_keys: set[tuple[DocumentKind, int]] = set()
    ignored_keys: set[tuple[DocumentKind, int]] = set()

    snapshot_attachments = (
        await session.execute(
            select(BalanceSnapshotAttachment, BalanceSnapshot, Account)
            .join(
                BalanceSnapshot,
                BalanceSnapshot.id == BalanceSnapshotAttachment.snapshot_id,
            )
            .join(Account, Account.id == BalanceSnapshot.account_id)
        )
    ).all()
    for attachment, snapshot, account in snapshot_attachments:
        covered_keys.add(("snapshot", snapshot.id))
        documents.append(
            DocumentRead(
                id=attachment.id,
                kind="snapshot",
                resource_id=snapshot.id,
                account_id=account.id,
                resource_label=account.name,
                resource_context="Relevé de compte",
                reference=snapshot.period,
                original_name=attachment.original_name,
                content_type=attachment.content_type,
                size=attachment.size,
                created_at=attachment.created_at,
                download_url=(
                    f"/api/accounts/{account.id}/snapshots/{snapshot.id}/"
                    f"attachments/{attachment.id}/download"
                ),
            )
        )

    recurring_attachments = (
        await session.execute(
            select(RecurringSeriesAttachment, RecurringSeries, Account)
            .join(
                RecurringSeries,
                RecurringSeries.id == RecurringSeriesAttachment.series_id,
            )
            .join(Account, Account.id == RecurringSeries.account_id)
        )
    ).all()
    for attachment, series, account in recurring_attachments:
        covered_keys.add(("recurring", series.id))
        documents.append(
            DocumentRead(
                id=attachment.id,
                kind="recurring",
                resource_id=series.id,
                account_id=account.id,
                resource_label=series.label,
                resource_context=account.name,
                reference=series.next_due.isoformat(),
                original_name=attachment.original_name,
                content_type=attachment.content_type,
                size=attachment.size,
                created_at=attachment.created_at,
                download_url=(
                    f"/api/recurring/{series.id}/attachments/"
                    f"{attachment.id}/download"
                ),
            )
        )

    debt_attachments = (
        await session.execute(
            select(DebtAttachment, Debt, Account)
            .join(Debt, Debt.id == DebtAttachment.debt_id)
            .outerjoin(Account, Account.id == Debt.account_id)
        )
    ).all()
    for attachment, debt, account in debt_attachments:
        covered_keys.add(("debt", debt.id))
        documents.append(
            DocumentRead(
                id=attachment.id,
                kind="debt",
                resource_id=debt.id,
                account_id=debt.account_id,
                resource_label=debt.name,
                resource_context=account.name if account else "Dette sans compte associé",
                reference=debt.due_date.isoformat() if debt.due_date else None,
                original_name=attachment.original_name,
                content_type=attachment.content_type,
                size=attachment.size,
                created_at=attachment.created_at,
                download_url=(
                    f"/api/debts/{debt.id}/attachments/{attachment.id}/download"
                ),
            )
        )

    real_estate_attachments = (
        await session.execute(
            select(RealEstateAttachment, RealEstateAsset).join(
                RealEstateAsset,
                RealEstateAsset.id == RealEstateAttachment.asset_id,
            )
        )
    ).all()
    for attachment, asset in real_estate_attachments:
        covered_keys.add(("real_estate", asset.id))
        documents.append(
            DocumentRead(
                id=attachment.id,
                kind="real_estate",
                resource_id=asset.id,
                account_id=None,
                resource_label=asset.name,
                resource_context=asset.address or "Patrimoine immobilier",
                reference=asset.acquired_on.isoformat() if asset.acquired_on else None,
                original_name=attachment.original_name,
                content_type=attachment.content_type,
                size=attachment.size,
                created_at=attachment.created_at,
                download_url=(
                    f"/api/real-estate/{asset.id}/attachments/"
                    f"{attachment.id}/download"
                ),
            )
        )

    contract_attachments = (
        await session.execute(
            select(WorkContractAttachment, WorkContract).join(
                WorkContract,
                WorkContract.id == WorkContractAttachment.contract_id,
            )
        )
    ).all()
    for attachment, contract in contract_attachments:
        covered_keys.add(("work_contract", contract.id))
        documents.append(
            DocumentRead(
                id=attachment.id,
                kind="work_contract",
                resource_id=contract.id,
                account_id=None,
                resource_label=contract.employer,
                resource_context=f"{contract.position} · {contract.contract_type}",
                reference=contract.start_date.isoformat(),
                original_name=attachment.original_name,
                content_type=attachment.content_type,
                size=attachment.size,
                created_at=attachment.created_at,
                download_url=(
                    f"/api/work/contracts/{contract.id}/attachments/"
                    f"{attachment.id}/download"
                ),
            )
        )

    payslip_attachments = (
        await session.execute(
            select(PaySlipAttachment, PaySlip, WorkContract)
            .join(PaySlip, PaySlip.id == PaySlipAttachment.payslip_id)
            .outerjoin(WorkContract, WorkContract.id == PaySlip.contract_id)
        )
    ).all()
    for attachment, payslip, contract in payslip_attachments:
        covered_keys.add(("payslip", payslip.id))
        documents.append(
            DocumentRead(
                id=attachment.id,
                kind="payslip",
                resource_id=payslip.id,
                account_id=None,
                resource_label=f"Bulletin de paie {payslip.period}",
                resource_context=(
                    f"{contract.employer} · {contract.position}"
                    if contract
                    else "Fiche de paie sans contrat associé"
                ),
                reference=payslip.period,
                original_name=attachment.original_name,
                content_type=attachment.content_type,
                size=attachment.size,
                created_at=attachment.created_at,
                download_url=(
                    f"/api/work/payslips/{payslip.id}/attachments/"
                    f"{attachment.id}/download"
                ),
            )
        )

    snapshots = (
        await session.execute(
            select(BalanceSnapshot, Account)
            .join(Account, Account.id == BalanceSnapshot.account_id)
            .order_by(BalanceSnapshot.period.desc(), Account.name, BalanceSnapshot.id)
        )
    ).all()
    for snapshot, account in snapshots:
        if snapshot.document_ignored:
            ignored_keys.add(("snapshot", snapshot.id))
        resources.append(
            DocumentResourceRead(
                kind="snapshot",
                resource_id=snapshot.id,
                account_id=account.id,
                label=account.name,
                context="Relevé de compte",
                reference=snapshot.period,
                can_upload=not account.archived,
            )
        )

    recurring_series = (
        await session.execute(
            select(RecurringSeries, Account)
            .join(Account, Account.id == RecurringSeries.account_id)
            .order_by(RecurringSeries.next_due.desc(), RecurringSeries.label)
        )
    ).all()
    for series, account in recurring_series:
        if series.document_ignored:
            ignored_keys.add(("recurring", series.id))
        resources.append(
            DocumentResourceRead(
                kind="recurring",
                resource_id=series.id,
                account_id=account.id,
                label=series.label,
                context=account.name,
                reference=series.next_due.isoformat(),
                can_upload=not account.archived,
            )
        )

    debts = (
        await session.execute(
            select(Debt, Account)
            .outerjoin(Account, Account.id == Debt.account_id)
            .order_by(Debt.due_date.desc(), Debt.name)
        )
    ).all()
    for debt, account in debts:
        if debt.document_ignored:
            ignored_keys.add(("debt", debt.id))
        resources.append(
            DocumentResourceRead(
                kind="debt",
                resource_id=debt.id,
                account_id=debt.account_id,
                label=debt.name,
                context=account.name if account else "Dette sans compte associé",
                reference=debt.due_date.isoformat() if debt.due_date else None,
                can_upload=account is None or not account.archived,
            )
        )

    real_estate_assets = (
        await session.execute(
            select(RealEstateAsset).order_by(
                RealEstateAsset.acquired_on.desc(),
                RealEstateAsset.name,
            )
        )
    ).scalars().all()
    for asset in real_estate_assets:
        if asset.document_ignored:
            ignored_keys.add(("real_estate", asset.id))
        resources.append(
            DocumentResourceRead(
                kind="real_estate",
                resource_id=asset.id,
                account_id=None,
                label=asset.name,
                context=asset.address or "Patrimoine immobilier",
                reference=asset.acquired_on.isoformat() if asset.acquired_on else None,
                can_upload=True,
            )
        )

    contracts = (
        await session.execute(
            select(WorkContract).order_by(
                WorkContract.start_date.desc(),
                WorkContract.id.desc(),
            )
        )
    ).scalars().all()
    for contract in contracts:
        if contract.document_ignored:
            ignored_keys.add(("work_contract", contract.id))
        resources.append(
            DocumentResourceRead(
                kind="work_contract",
                resource_id=contract.id,
                account_id=None,
                label=contract.employer,
                context=f"{contract.position} · {contract.contract_type}",
                reference=contract.start_date.isoformat(),
                can_upload=True,
            )
        )

    payslips = (
        await session.execute(
            select(PaySlip, WorkContract)
            .outerjoin(WorkContract, WorkContract.id == PaySlip.contract_id)
            .order_by(PaySlip.period.desc(), PaySlip.id.desc())
        )
    ).all()
    for payslip, contract in payslips:
        if payslip.document_ignored:
            ignored_keys.add(("payslip", payslip.id))
        resources.append(
            DocumentResourceRead(
                kind="payslip",
                resource_id=payslip.id,
                account_id=None,
                label=f"Bulletin de paie {payslip.period}",
                context=(
                    f"{contract.employer} · {contract.position}"
                    if contract
                    else "Fiche de paie sans contrat associé"
                ),
                reference=payslip.period,
                can_upload=True,
            )
        )

    resource_counts = Counter(resource.kind for resource in resources)
    covered_counts = Counter(kind for kind, _resource_id in covered_keys)
    document_counts = Counter(document.kind for document in documents)
    missing_resources = [
        resource
        for resource in resources
        if (resource.kind, resource.resource_id) not in covered_keys
    ]
    resources_without_documents = [
        resource
        for resource in missing_resources
        if (resource.kind, resource.resource_id) not in ignored_keys
    ]
    ignored_resources = [
        resource
        for resource in missing_resources
        if (resource.kind, resource.resource_id) in ignored_keys
    ]
    missing_counts = Counter(resource.kind for resource in resources_without_documents)
    documents.sort(key=lambda document: (document.created_at, document.id), reverse=True)

    return DocumentCenterRead(
        stats=DocumentCenterStats(
            total_documents=len(documents),
            total_size=sum(document.size for document in documents),
            total_resources=len(resources),
            covered_resources=len(covered_keys),
            missing_resources=len(resources_without_documents),
        ),
        kinds=[
            DocumentKindSummary(
                kind=kind,
                label=label,
                total_resources=resource_counts[kind],
                covered_resources=covered_counts[kind],
                missing_resources=missing_counts[kind],
                document_count=document_counts[kind],
            )
            for kind, label in KIND_LABELS.items()
        ],
        documents=documents,
        resources_without_documents=resources_without_documents,
        ignored_resources=ignored_resources,
    )
