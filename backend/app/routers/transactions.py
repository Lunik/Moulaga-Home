"""Transaction mutations that complement the core ledger in ``budget.py``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..account_access import ensure_account_writable, require_account
from ..attachments import attachment_path, remove_attachment, store_attachment
from ..db import get_session
from ..models import Category, Transaction, TransactionAttachment
from ..schemas import (
    TransactionAttachmentRead,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)

router = APIRouter(tags=["transactions"])


def _read(transaction: Transaction) -> TransactionRead:
    return TransactionRead.model_validate(transaction).model_copy(
        update={
            "account_name": transaction.account.name,
            "category_name": transaction.category.name if transaction.category else None,
            "category_kind": transaction.category.kind if transaction.category else None,
            "attachment_count": len(transaction.attachments),
        }
    )


async def _load(session: AsyncSession, transaction_id: int) -> Transaction:
    statement = (
        select(Transaction)
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.category),
            selectinload(Transaction.attachments),
        )
        .where(Transaction.id == transaction_id)
        .execution_options(populate_existing=True)
    )
    transaction = (await session.execute(statement)).scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    return transaction


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
async def get_transaction(
    transaction_id: int, session: AsyncSession = Depends(get_session)
) -> TransactionRead:
    return _read(await _load(session, transaction_id))


@router.post("/transactions/with-attachment", response_model=TransactionRead, status_code=201)
async def create_transaction_with_attachment(
    payload_json: str = Form(...),
    file: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_session),
) -> TransactionRead:
    try:
        payload = TransactionCreate.model_validate_json(payload_json)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(), body=payload_json) from exc

    await require_account(session, payload.account_id, writable=True)
    if payload.category_id is not None and await session.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")

    transaction = Transaction(**payload.model_dump())
    session.add(transaction)
    stored_path: str | None = None
    try:
        await session.flush()
        if file is not None:
            original_name, stored_path, size = await store_attachment(file)
            session.add(
                TransactionAttachment(
                    transaction_id=transaction.id,
                    original_name=original_name,
                    stored_path=stored_path,
                    content_type=file.content_type,
                    size=size,
                )
            )
        await session.commit()
    except (HTTPException, OSError, SQLAlchemyError):
        await session.rollback()
        if stored_path is not None:
            remove_attachment(stored_path)
        raise
    return _read(await _load(session, transaction.id))


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    session: AsyncSession = Depends(get_session),
) -> TransactionRead:
    transaction = await _load(session, transaction_id)
    ensure_account_writable(transaction.account)
    data = payload.model_dump(exclude_unset=True)

    if transaction.transfer_group is not None and {
        "amount",
        "account_id",
        "category_id",
    } & data.keys():
        raise HTTPException(
            status_code=409,
            detail="Les montants et comptes d'un transfert lie ne sont pas modifiables",
        )
    if "account_id" in data:
        if data["account_id"] is None:
            raise HTTPException(status_code=422, detail="Compte requis")
        await require_account(session, data["account_id"], writable=True)
    if data.get("category_id") is not None and await session.get(Category, data["category_id"]) is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")

    for field, value in data.items():
        setattr(transaction, field, value)
    await session.commit()
    return _read(await _load(session, transaction_id))


@router.delete("/transactions/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    transaction = await _load(session, transaction_id)
    ensure_account_writable(transaction.account)
    if transaction.transfer_group is not None:
        raise HTTPException(
            status_code=409,
            detail="Un transfert lie ne peut pas etre supprime individuellement",
        )
    attachments = (
        await session.execute(
            select(TransactionAttachment).where(
                TransactionAttachment.transaction_id == transaction_id
            )
        )
    ).scalars().all()
    for attachment in attachments:
        remove_attachment(attachment.stored_path)
    await session.delete(transaction)
    await session.commit()


def _attachment_read(attachment: TransactionAttachment) -> TransactionAttachmentRead:
    return TransactionAttachmentRead(
        id=attachment.id,
        transaction_id=attachment.transaction_id,
        original_name=attachment.original_name,
        storage_path=f"/{attachment.stored_path}",
        content_type=attachment.content_type,
        size=attachment.size,
    )


async def _require_attachment(
    session: AsyncSession,
    transaction_id: int,
    attachment_id: int,
) -> TransactionAttachment:
    attachment = await session.get(TransactionAttachment, attachment_id)
    if attachment is None or attachment.transaction_id != transaction_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    return attachment


@router.get(
    "/transactions/{transaction_id}/attachments",
    response_model=list[TransactionAttachmentRead],
)
async def list_attachments(
    transaction_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[TransactionAttachmentRead]:
    await _load(session, transaction_id)
    rows = (
        await session.execute(
            select(TransactionAttachment)
            .where(TransactionAttachment.transaction_id == transaction_id)
            .order_by(TransactionAttachment.created_at, TransactionAttachment.id)
        )
    ).scalars().all()
    return [_attachment_read(row) for row in rows]


@router.post(
    "/transactions/{transaction_id}/attachments",
    response_model=TransactionAttachmentRead,
    status_code=201,
)
async def upload_attachment(
    transaction_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> TransactionAttachmentRead:
    transaction = await _load(session, transaction_id)
    ensure_account_writable(transaction.account)
    original_name, stored_path, size = await store_attachment(file)
    attachment = TransactionAttachment(
        transaction_id=transaction_id,
        original_name=original_name,
        stored_path=stored_path,
        content_type=file.content_type,
        size=size,
    )
    session.add(attachment)
    try:
        await session.commit()
    except SQLAlchemyError:
        remove_attachment(stored_path)
        raise
    await session.refresh(attachment)
    return _attachment_read(attachment)


@router.get(
    "/transactions/{transaction_id}/attachments/{attachment_id}/download",
    response_model=None,
)
async def download_attachment(
    transaction_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_attachment(session, transaction_id, attachment_id)
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
    "/transactions/{transaction_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_attachment(
    transaction_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    attachment = await _require_attachment(session, transaction_id, attachment_id)
    transaction = await _load(session, transaction_id)
    ensure_account_writable(transaction.account)
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()
