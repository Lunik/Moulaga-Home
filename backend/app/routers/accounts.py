"""Extended account management: metadata and monthly snapshots."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..account_access import ensure_account_writable, require_account
from ..attachments import attachment_path, remove_attachment, store_attachment
from ..common import local_today, money
from ..db import get_session
from ..models import (
    Account,
    BalanceSnapshot,
    BalanceSnapshotAttachment,
    Debt,
    Goal,
    Holding,
    RecurringSeries,
    SharedAccountLink,
    Transaction,
)
from ..schemas import (
    DEPRECATED_ACCOUNT_TYPES,
    AccountDetail,
    AccountHistoryPoint,
    AccountRead,
    AccountUpdate,
    BalanceSnapshotAttachmentRead,
    BalanceSnapshotCreate,
    BalanceSnapshotRead,
    BalanceSnapshotUpdate,
    InstitutionHistoryPoint,
)

router = APIRouter(tags=["accounts"])


async def _require_account(session: AsyncSession, account_id: int) -> Account:
    return await require_account(session, account_id)


async def _balance(session: AsyncSession, account: Account) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.account_id == account.id
        )
    )
    return money(account.initial_balance + Decimal(total or 0))


async def _account_read(session: AsyncSession, account: Account) -> AccountRead:
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.account_id == account.id
        )
    )
    return AccountRead.model_validate(account).model_copy(
        update={
            "balance": await _balance(session, account),
            "transaction_count": int(count or 0),
        }
    )


async def _has_dependencies(session: AsyncSession, account_id: int) -> bool:
    for model in (
        Transaction,
        BalanceSnapshot,
        RecurringSeries,
        Debt,
        Holding,
        SharedAccountLink,
        Goal,
    ):
        dependency_id = await session.scalar(
            select(model.id).where(model.account_id == account_id).limit(1)
        )
        if dependency_id is not None:
            return True
    return False


@router.get(
    "/accounts/institution-history",
    response_model=list[InstitutionHistoryPoint],
)
async def list_institution_history(
    archived: bool = False,
    account_type: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[InstitutionHistoryPoint]:
    institution = func.coalesce(
        func.nullif(func.trim(Account.institution), ""),
        "Établissement non renseigné",
    )
    statement = (
        select(
            Account.id.label("account_id"),
            BalanceSnapshot.period.label("period"),
            institution.label("institution"),
            BalanceSnapshot.balance.label("balance"),
        )
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .where(Account.archived.is_(archived))
        .order_by(BalanceSnapshot.period, Account.id)
    )
    if account_type is not None:
        statement = statement.where(Account.type == account_type)

    rows = (await session.execute(statement)).all()
    snapshots_by_period: dict[str, list[tuple[int, str, Decimal]]] = {}
    for account_id, period, institution_name, balance in rows:
        snapshots_by_period.setdefault(period, []).append(
            (account_id, institution_name, Decimal(balance))
        )

    latest_by_account: dict[int, tuple[str, Decimal]] = {}
    history: list[InstitutionHistoryPoint] = []
    for period, snapshots in snapshots_by_period.items():
        for account_id, institution_name, balance in snapshots:
            latest_by_account[account_id] = (institution_name, balance)

        totals: dict[str, Decimal] = {}
        for institution_name, balance in latest_by_account.values():
            totals[institution_name] = totals.get(institution_name, Decimal("0.00")) + balance
        history.extend(
            InstitutionHistoryPoint(
                period=period,
                institution=institution_name,
                balance=money(balance),
            )
            for institution_name, balance in sorted(totals.items())
        )
    return history


@router.get("/accounts/{account_id}", response_model=AccountDetail)
async def get_account(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> AccountDetail:
    account = await _require_account(session, account_id)
    balance = await _balance(session, account)
    snapshots = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id)
    )
    detail = AccountDetail(
        id=account.id,
        name=account.name,
        type=account.type,
        currency=account.currency,
        initial_balance=account.initial_balance,
        institution=account.institution,
        account_number=account.account_number,
        color=account.color,
        archived=account.archived,
        savings_product=account.savings_product,
        annual_interest_rate=account.annual_interest_rate,
        legal_cap=account.legal_cap,
        balance=balance,
        history=[
            AccountHistoryPoint(period=s.period, balance=money(s.balance)) for s in snapshots
        ],
        transaction_count=int(count or 0),
    )
    return detail


@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    data = payload.model_dump(exclude_unset=True)
    requested_type = data.get("type")
    if requested_type in DEPRECATED_ACCOUNT_TYPES and requested_type != account.type:
        raise HTTPException(status_code=422, detail="Ce type de compte n'est plus disponible")
    for field, value in data.items():
        setattr(account, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    return await _account_read(session, account)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    if await _has_dependencies(session, account_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Ce compte contient un historique ou des liens. "
                "Archivez-le pour conserver vos donnees."
            ),
        )
    await session.delete(account)
    await session.commit()


@router.post("/accounts/{account_id}/archive", response_model=AccountRead)
async def archive_account(
    account_id: int,
    archived: bool = True,
    transfer_to_account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id)
    if transfer_to_account_id is not None:
        if not archived:
            raise HTTPException(
                status_code=422,
                detail="Un transfert est uniquement possible lors de l'archivage",
            )
        if transfer_to_account_id == account_id:
            raise HTTPException(
                status_code=422,
                detail="Le compte de destination doit etre different",
            )
        destination = await _require_account(session, transfer_to_account_id)
        if destination.archived:
            raise HTTPException(
                status_code=409,
                detail="Le compte de destination est archive",
            )
        if destination.currency != account.currency:
            raise HTTPException(
                status_code=409,
                detail="Les deux comptes doivent utiliser la meme devise",
            )
        balance = await _balance(session, account)
        if balance <= 0:
            raise HTTPException(
                status_code=409,
                detail="Seul un solde positif peut etre transfere avant archivage",
            )
        transfer_group = uuid4().hex
        session.add_all(
            [
                Transaction(
                    booked_at=local_today(),
                    description=f"Transfert vers {destination.name}",
                    amount=money(-balance),
                    account_id=account.id,
                    transfer_group=transfer_group,
                ),
                Transaction(
                    booked_at=local_today(),
                    description=f"Transfert depuis {account.name}",
                    amount=money(balance),
                    account_id=destination.id,
                    transfer_group=transfer_group,
                ),
            ]
        )
    account.archived = archived
    await session.commit()
    await session.refresh(account)
    return await _account_read(session, account)


# --------------------------------------------------------------------------- #
# Monthly balance snapshots
# --------------------------------------------------------------------------- #
def _snapshot_read(snapshot: BalanceSnapshot) -> BalanceSnapshotRead:
    return BalanceSnapshotRead.model_validate(snapshot).model_copy(
        update={"attachment_count": len(snapshot.attachments)}
    )


def _remove_snapshot_files(snapshot: BalanceSnapshot) -> None:
    for attachment in snapshot.attachments:
        remove_attachment(attachment.stored_path)


@router.get("/accounts/{account_id}/snapshots", response_model=list[BalanceSnapshotRead])
async def list_snapshots(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> list[BalanceSnapshotRead]:
    await _require_account(session, account_id)
    rows = (
        await session.execute(
            select(BalanceSnapshot)
            .options(selectinload(BalanceSnapshot.attachments))
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    return [_snapshot_read(row) for row in rows]


async def _require_snapshot(
    session: AsyncSession,
    account_id: int,
    snapshot_id: int,
) -> BalanceSnapshot:
    snapshot = (
        await session.execute(
            select(BalanceSnapshot)
            .options(selectinload(BalanceSnapshot.attachments))
            .where(
                BalanceSnapshot.id == snapshot_id,
                BalanceSnapshot.account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Releve introuvable")
    return snapshot


@router.put("/accounts/{account_id}/snapshots", response_model=BalanceSnapshotRead)
async def upsert_snapshot(
    account_id: int,
    payload: BalanceSnapshotCreate,
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    """Create or overwrite the snapshot for a period (idempotent)."""
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    existing = await session.scalar(
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.period == payload.period,
        )
    )
    if existing is None:
        existing = BalanceSnapshot(account_id=account_id, period=payload.period)
        session.add(existing)
    existing.balance = money(payload.balance)
    await session.commit()
    return _snapshot_read(await _require_snapshot(session, account_id, existing.id))


@router.patch(
    "/accounts/{account_id}/snapshots/{snapshot_id}",
    response_model=BalanceSnapshotRead,
)
async def update_snapshot(
    account_id: int,
    snapshot_id: int,
    payload: BalanceSnapshotUpdate,
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    snapshot = await _require_snapshot(session, account_id, snapshot_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(snapshot, field, money(value) if field == "balance" else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Un releve existe deja pour cette periode",
        ) from exc
    return _snapshot_read(await _require_snapshot(session, account_id, snapshot.id))


@router.delete("/accounts/{account_id}/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(
    account_id: int,
    snapshot_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    snapshot = await _require_snapshot(session, account_id, snapshot_id)
    _remove_snapshot_files(snapshot)
    await session.delete(snapshot)
    await session.commit()


@router.post("/accounts/{account_id}/snapshots/generate", response_model=list[BalanceSnapshotRead])
async def generate_snapshots(
    account_id: int, session: AsyncSession = Depends(get_session)
) -> list[BalanceSnapshotRead]:
    """Rebuild month-end cumulative snapshots from the ledger (idempotent)."""
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    month_expr = func.strftime("%Y-%m", Transaction.booked_at)
    rows = (
        await session.execute(
            select(month_expr, func.sum(Transaction.amount))
            .where(Transaction.account_id == account_id)
            .group_by(month_expr)
            .order_by(month_expr)
        )
    ).all()

    existing = {
        snap.period: snap
        for snap in (
            await session.execute(
                select(BalanceSnapshot)
                .options(selectinload(BalanceSnapshot.attachments))
                .where(BalanceSnapshot.account_id == account_id)
            )
        ).scalars().all()
    }

    running = Decimal(account.initial_balance)
    for period, delta in rows:
        running += Decimal(delta or 0)
        snapshot = existing.get(period)
        if snapshot is None:
            snapshot = BalanceSnapshot(account_id=account_id, period=period)
            session.add(snapshot)
            existing[period] = snapshot
        snapshot.balance = money(running)
    generated_periods = {period for period, _delta in rows}
    for period, snapshot in existing.items():
        if period not in generated_periods:
            _remove_snapshot_files(snapshot)
            await session.delete(snapshot)
    await session.commit()

    refreshed = (
        await session.execute(
            select(BalanceSnapshot)
            .options(selectinload(BalanceSnapshot.attachments))
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    return [_snapshot_read(row) for row in refreshed]


def _snapshot_attachment_read(
    attachment: BalanceSnapshotAttachment,
) -> BalanceSnapshotAttachmentRead:
    return BalanceSnapshotAttachmentRead(
        id=attachment.id,
        snapshot_id=attachment.snapshot_id,
        original_name=attachment.original_name,
        storage_path=f"/{attachment.stored_path}",
        content_type=attachment.content_type,
        size=attachment.size,
    )


async def _require_snapshot_attachment(
    session: AsyncSession,
    account_id: int,
    snapshot_id: int,
    attachment_id: int,
) -> BalanceSnapshotAttachment:
    await _require_snapshot(session, account_id, snapshot_id)
    attachment = await session.get(BalanceSnapshotAttachment, attachment_id)
    if attachment is None or attachment.snapshot_id != snapshot_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    return attachment


@router.get(
    "/accounts/{account_id}/snapshots/{snapshot_id}/attachments",
    response_model=list[BalanceSnapshotAttachmentRead],
)
async def list_snapshot_attachments(
    account_id: int,
    snapshot_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[BalanceSnapshotAttachmentRead]:
    await _require_snapshot(session, account_id, snapshot_id)
    rows = (
        await session.execute(
            select(BalanceSnapshotAttachment)
            .where(BalanceSnapshotAttachment.snapshot_id == snapshot_id)
            .order_by(
                BalanceSnapshotAttachment.created_at,
                BalanceSnapshotAttachment.id,
            )
        )
    ).scalars().all()
    return [_snapshot_attachment_read(row) for row in rows]


@router.post(
    "/accounts/{account_id}/snapshots/{snapshot_id}/attachments",
    response_model=BalanceSnapshotAttachmentRead,
    status_code=201,
)
async def upload_snapshot_attachment(
    account_id: int,
    snapshot_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotAttachmentRead:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    await _require_snapshot(session, account_id, snapshot_id)
    content_type = file.content_type
    original_name, stored_path, size = await store_attachment(file)
    attachment = BalanceSnapshotAttachment(
        snapshot_id=snapshot_id,
        original_name=original_name,
        stored_path=stored_path,
        content_type=content_type,
        size=size,
    )
    session.add(attachment)
    try:
        await session.commit()
    except SQLAlchemyError:
        remove_attachment(stored_path)
        raise
    await session.refresh(attachment)
    return _snapshot_attachment_read(attachment)


@router.get(
    "/accounts/{account_id}/snapshots/{snapshot_id}/attachments/{attachment_id}/download",
    response_model=None,
)
async def download_snapshot_attachment(
    account_id: int,
    snapshot_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_snapshot_attachment(
        session,
        account_id,
        snapshot_id,
        attachment_id,
    )
    path = attachment_path(attachment.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier de piece jointe introuvable")
    return FileResponse(
        path,
        filename=attachment.original_name,
        media_type=attachment.content_type or "application/octet-stream",
        content_disposition_type="attachment",
    )


@router.delete(
    "/accounts/{account_id}/snapshots/{snapshot_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_snapshot_attachment(
    account_id: int,
    snapshot_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id)
    ensure_account_writable(account)
    attachment = await _require_snapshot_attachment(
        session,
        account_id,
        snapshot_id,
        attachment_id,
    )
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()
