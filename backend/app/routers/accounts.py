"""Extended account management: metadata and monthly snapshots."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..account_access import (
    account_owner,
    account_owner_ids,
    account_owner_member_column,
    allocate_equal_shares,
    ensure_account_writable,
    require_account,
    require_active_profile,
)
from ..account_balances import (
    account_balance,
    account_balance_shares,
    account_missing_snapshot_periods,
    missing_snapshot_periods,
)
from ..attachments import attachment_path, remove_attachment, store_attachment
from ..common import local_today, money
from ..db import get_session
from ..institutions import (
    UNASSIGNED_INSTITUTION,
    institution_fields,
    institution_group,
    institution_label,
)
from ..models import (
    Account,
    AccountOwner,
    BalanceSnapshot,
    BalanceSnapshotAttachment,
    Debt,
    Goal,
    Holding,
    HouseholdMember,
    RecurringSeries,
    SharedAccountLink,
)
from ..schemas import (
    DEPRECATED_ACCOUNT_TYPES,
    AccountDetail,
    AccountHistoryPoint,
    AccountRead,
    AccountUpdate,
    BalanceSnapshotAttachmentRead,
    BalanceSnapshotCreate,
    BalanceSnapshotImportRequest,
    BalanceSnapshotImportResult,
    BalanceSnapshotRead,
    BalanceSnapshotUpdate,
    InstitutionHistoryPoint,
)
from ..snapshot_import import SnapshotImportError, parse_snapshot_tsv

router = APIRouter(tags=["accounts"])


async def _require_account(
    session: AsyncSession, account_id: int, profile: HouseholdMember
) -> Account:
    return await require_account(session, account_id, profile_id=profile.id)


async def _balance(session: AsyncSession, account: Account) -> Decimal:
    return await account_balance(session, account)


async def _set_snapshot_balance(
    session: AsyncSession,
    account_id: int,
    period: str,
    balance: Decimal,
) -> BalanceSnapshot:
    snapshot = await session.scalar(
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.period == period,
        )
    )
    if snapshot is None:
        snapshot = BalanceSnapshot(account_id=account_id, period=period)
        session.add(snapshot)
    snapshot.balance = money(balance)
    return snapshot


def _with_share_fields(
    account_read: AccountRead,
    *,
    total_balance: Decimal,
    profile_share: Decimal,
    owner_ids: tuple[int, ...],
) -> AccountRead:
    """Populate optional ownership fields as schemas gain the multi-user contract."""
    updates: dict[str, object] = {"balance": profile_share}
    available = type(account_read).model_fields
    for name, value in (
        ("total_balance", total_balance),
        ("profile_share", profile_share),
        ("owner_profile_ids", list(owner_ids)),
    ):
        if name in available:
            updates[name] = value
    return account_read.model_copy(update=updates)


async def _account_read(
    session: AsyncSession, account: Account, profile: HouseholdMember
) -> AccountRead:
    missing_periods = await account_missing_snapshot_periods(
        session,
        account_ids={account.id} if not account.archived else set(),
    )
    total_balance = await account_balance(session, account)
    owner_ids = tuple(await account_owner_ids(session, account.id))
    profile_share = allocate_equal_shares(total_balance, owner_ids).get(
        profile.id, Decimal("0.00")
    )
    return _with_share_fields(
        AccountRead.model_validate(account).model_copy(
            update={
                "missing_snapshot_periods": missing_periods.get(account.id, []),
                **institution_fields(
                    account.institution,
                    account.regional_entity,
                ),
            }
        ),
        total_balance=total_balance,
        profile_share=profile_share,
        owner_ids=owner_ids,
    )


async def _has_dependencies(session: AsyncSession, account_id: int) -> bool:
    for model in (
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


async def _replace_account_owners(
    session: AsyncSession,
    account: Account,
    profile: HouseholdMember,
    profile_ids: list[int],
) -> None:
    """Set equal owners, including an explicit transfer away from the actor."""
    unique_ids = sorted(set(profile_ids))
    if not unique_ids:
        raise HTTPException(
            status_code=422,
            detail="Au moins un proprietaire est requis",
        )
    owners = list(
        (
            await session.execute(
                select(HouseholdMember).where(
                    HouseholdMember.id.in_(unique_ids),
                    HouseholdMember.active.is_(True),
                )
            )
        ).scalars().all()
    )
    if len(owners) != len(unique_ids):
        raise HTTPException(status_code=422, detail="Un profil proprietaire est introuvable")
    if (
        len({owner.household_id for owner in owners}) != 1
        or owners[0].household_id != profile.household_id
    ):
        raise HTTPException(
            status_code=422,
            detail="Les proprietaires doivent appartenir au meme foyer",
        )
    await session.execute(
        sql_delete(AccountOwner).where(AccountOwner.account_id == account.id)
    )
    session.add_all(
        [
            account_owner(account.id, owner_id)
            for owner_id in unique_ids
        ]
    )


@router.get(
    "/accounts/institution-history",
    response_model=list[InstitutionHistoryPoint],
)
async def list_institution_history(
    include_archived: bool = True,
    account_type: str | None = None,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[InstitutionHistoryPoint]:
    statement = (
        select(
            Account.id.label("account_id"),
            BalanceSnapshot.period.label("period"),
            Account.institution.label("institution"),
            Account.regional_entity.label("regional_entity"),
            BalanceSnapshot.balance.label("balance"),
        )
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .join(AccountOwner, AccountOwner.account_id == Account.id)
        .where(account_owner_member_column() == profile.id)
        .order_by(BalanceSnapshot.period, Account.id)
    )
    if not include_archived:
        statement = statement.where(Account.archived.is_(False))
    if account_type is not None:
        statement = statement.where(Account.type == account_type)

    from ..account_access import account_share

    rows = [
        (
            account_id,
            period,
            raw_institution,
            regional_entity,
            await account_share(session, account_id, profile.id, Decimal(balance)),
        )
        for account_id, period, raw_institution, regional_entity, balance in (
            await session.execute(statement)
        ).all()
    ]
    snapshots_by_period: dict[str, list[tuple[int, str, Decimal]]] = {}
    for account_id, period, raw_institution, regional_entity, balance in rows:
        institution_name = (
            institution_label(raw_institution, regional_entity)
            or UNASSIGNED_INSTITUTION
        )
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
    account_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> AccountDetail:
    account = await _require_account(session, account_id, profile)
    balance_share = (
        await account_balance_shares(session, profile.id, account_ids={account.id})
    )[account.id]
    snapshots = (
        await session.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    normalized_institution = institution_fields(
        account.institution,
        account.regional_entity,
    )
    from ..account_access import account_share

    detail = AccountDetail(
        id=account.id,
        name=account.name,
        type=account.type,
        currency=account.currency,
        initial_balance=account.initial_balance,
        institution=normalized_institution["institution"],
        regional_entity=normalized_institution["regional_entity"],
        account_number=account.account_number,
        color=account.color,
        archived=account.archived,
        savings_product=account.savings_product,
        annual_interest_rate=account.annual_interest_rate,
        legal_cap=account.legal_cap,
        balance=balance_share.profile_share,
        missing_snapshot_periods=(
            []
            if account.archived
            else missing_snapshot_periods([snapshot.period for snapshot in snapshots])
        ),
        history=[
            AccountHistoryPoint(
                period=s.period,
                balance=await account_share(
                    session,
                    account.id,
                    profile.id,
                    money(s.balance),
                ),
            )
            for s in snapshots
        ],
    )
    return _with_share_fields(
        detail,
        total_balance=balance_share.total,
        profile_share=balance_share.profile_share,
        owner_ids=balance_share.owner_ids,
    )


@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id, profile)
    ensure_account_writable(account)
    data = payload.model_dump(exclude_unset=True)
    owner_profile_ids = data.pop("owner_profile_ids", None)
    balance = data.pop("balance", None)
    if balance is None and "initial_balance" in data:
        balance = data["initial_balance"]
    if "institution" in data or "regional_entity" in data:
        current_institution = institution_fields(
            account.institution,
            account.regional_entity,
        )
        next_institution = data.get(
            "institution",
            current_institution["institution"],
        )
        if "regional_entity" in data:
            next_regional_entity = data["regional_entity"]
        elif institution_group(next_institution) == institution_group(
            current_institution["institution"]
        ):
            next_regional_entity = current_institution["regional_entity"]
        else:
            next_regional_entity = None
        if next_regional_entity is not None and next_institution is None:
            raise HTTPException(
                status_code=422,
                detail="Une entite regionale necessite un etablissement",
            )
        data.update(
            institution_fields(
                next_institution,
                next_regional_entity,
            )
        )
    requested_type = data.get("type")
    if requested_type in DEPRECATED_ACCOUNT_TYPES and requested_type != account.type:
        raise HTTPException(status_code=422, detail="Ce type de compte n'est plus disponible")
    for field, value in data.items():
        setattr(account, field, value)
    if balance is not None:
        await _set_snapshot_balance(
            session,
            account.id,
            local_today().strftime("%Y-%m"),
            balance,
        )
    try:
        if owner_profile_ids is not None:
            await _replace_account_owners(
                session,
                account,
                profile,
                owner_profile_ids,
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Un compte avec ce nom existe deja") from exc
    await session.refresh(account)
    return await _account_read(session, account, profile)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id, profile)
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


@router.put("/accounts/{account_id}/owners", response_model=AccountRead)
async def replace_account_owners(
    account_id: int,
    profile_ids: list[int] = Body(embed=True, min_length=1),
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    """Replace equal account ownership after verifying every proposed profile."""
    account = await _require_account(session, account_id, profile)
    ensure_account_writable(account)
    await _replace_account_owners(session, account, profile, profile_ids)
    await session.commit()
    await session.refresh(account)
    return await _account_read(session, account, profile)


@router.post("/accounts/{account_id}/archive", response_model=AccountRead)
async def archive_account(
    account_id: int,
    archived: bool = True,
    transfer_to_account_id: int | None = None,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> AccountRead:
    account = await _require_account(session, account_id, profile)
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
        destination = await _require_account(session, transfer_to_account_id, profile)
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
        destination_balance = await _balance(session, destination)
        today = local_today()
        period = today.strftime("%Y-%m")
        await _set_snapshot_balance(session, account.id, period, Decimal("0.00"))
        await _set_snapshot_balance(
            session,
            destination.id,
            period,
            destination_balance + balance,
        )
    account.archived = archived
    await session.commit()
    await session.refresh(account)
    return await _account_read(session, account, profile)


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
    account_id: int,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[BalanceSnapshotRead]:
    await _require_account(session, account_id, profile)
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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    """Create or overwrite the snapshot for a period (idempotent)."""
    account = await _require_account(session, account_id, profile)
    ensure_account_writable(account)
    existing = await _set_snapshot_balance(
        session,
        account_id,
        payload.period,
        payload.balance,
    )
    await session.commit()
    return _snapshot_read(await _require_snapshot(session, account_id, existing.id))


@router.post(
    "/accounts/{account_id}/snapshots/import",
    response_model=BalanceSnapshotImportResult,
)
async def import_snapshots(
    account_id: int,
    payload: BalanceSnapshotImportRequest,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotImportResult:
    account = await _require_account(session, account_id, profile)
    ensure_account_writable(account)
    try:
        rows = parse_snapshot_tsv(payload.content)
    except SnapshotImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    periods = {row.period for row in rows}
    existing_by_period = {
        snapshot.period: snapshot
        for snapshot in (
            await session.execute(
                select(BalanceSnapshot).where(
                    BalanceSnapshot.account_id == account_id,
                )
            )
        ).scalars().all()
        if snapshot.period in periods
    }
    created_count = 0
    updated_count = 0
    for row in rows:
        snapshot = existing_by_period.get(row.period)
        if snapshot is None:
            snapshot = BalanceSnapshot(account_id=account_id, period=row.period)
            session.add(snapshot)
            created_count += 1
        else:
            updated_count += 1
        snapshot.balance = money(row.balance)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Un relevé existe déjà pour l'une des périodes importées.",
        ) from exc

    imported = (
        await session.execute(
            select(BalanceSnapshot)
            .options(selectinload(BalanceSnapshot.attachments))
            .where(BalanceSnapshot.account_id == account_id)
            .order_by(BalanceSnapshot.period)
        )
    ).scalars().all()
    return BalanceSnapshotImportResult(
        imported_count=len(rows),
        created_count=created_count,
        updated_count=updated_count,
        snapshots=[
            _snapshot_read(snapshot)
            for snapshot in imported
            if snapshot.period in periods
        ],
    )


@router.patch(
    "/accounts/{account_id}/snapshots/{snapshot_id}",
    response_model=BalanceSnapshotRead,
)
async def update_snapshot(
    account_id: int,
    snapshot_id: int,
    payload: BalanceSnapshotUpdate,
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotRead:
    account = await _require_account(session, account_id, profile)
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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id, profile)
    ensure_account_writable(account)
    snapshot = await _require_snapshot(session, account_id, snapshot_id)
    _remove_snapshot_files(snapshot)
    await session.delete(snapshot)
    await session.commit()


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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> list[BalanceSnapshotAttachmentRead]:
    await _require_account(session, account_id, profile)
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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> BalanceSnapshotAttachmentRead:
    account = await _require_account(session, account_id, profile)
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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    await _require_account(session, account_id, profile)
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
    profile: HouseholdMember = Depends(require_active_profile),
    session: AsyncSession = Depends(get_session),
) -> None:
    account = await _require_account(session, account_id, profile)
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
