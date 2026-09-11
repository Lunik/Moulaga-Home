"""Recurring budget series: CRUD, attachments and forecasting."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account
from ..attachments import attachment_path, remove_attachment, store_attachment
from ..common import add_month, money
from ..db import get_session
from ..debt_recurring import debt_payment, recurring_amount
from ..models import (
    Account,
    Category,
    Debt,
    RecurringSeries,
    RecurringSeriesAttachment,
)
from ..recurring_budget import recurrence_dates
from ..schemas import (
    ForecastPoint,
    RecurringCreate,
    RecurringRead,
    RecurringSeriesAttachmentRead,
    RecurringUpdate,
)

router = APIRouter(tags=["recurring"])


async def _require_account(session: AsyncSession, account_id: int) -> None:
    await require_account(session, account_id, writable=True)


async def _require_category(session: AsyncSession, category_id: int) -> None:
    if await session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")


async def _account_name(session: AsyncSession, account_id: int) -> str:
    account = await session.get(Account, account_id)
    return account.name if account else ""


async def _category_name(session: AsyncSession, category_id: int | None) -> str | None:
    if category_id is None:
        return None
    category = await session.get(Category, category_id)
    return category.name if category else None


async def _series_read(session: AsyncSession, series: RecurringSeries) -> RecurringRead:
    attachment_count = await session.scalar(
        select(func.count())
        .select_from(RecurringSeriesAttachment)
        .where(RecurringSeriesAttachment.series_id == series.id)
    )
    return RecurringRead(
        id=series.id,
        label=series.label,
        account_id=series.account_id,
        category_id=series.category_id,
        frequency=series.frequency,
        next_due=series.next_due,
        amount=series.amount,
        amount_type=series.amount_type,
        status=series.status,
        recurring_type=series.recurring_type,
        custom_type=series.custom_type,
        credit_insurance_rate=series.credit_insurance_rate,
        account_name=await _account_name(session, series.account_id),
        category_name=await _category_name(session, series.category_id),
        attachment_count=int(attachment_count or 0),
    )

# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
@router.get("/recurring", response_model=list[RecurringRead])
async def list_series(session: AsyncSession = Depends(get_session)) -> list[RecurringRead]:
    rows = (
        await session.execute(select(RecurringSeries).order_by(RecurringSeries.next_due))
    ).scalars().all()
    accounts = {
        acc.id: acc.name for acc in (await session.execute(select(Account))).scalars().all()
    }
    categories = {
        cat.id: cat.name for cat in (await session.execute(select(Category))).scalars().all()
    }
    attachment_counts = {
        series_id: count
        for series_id, count in (
            await session.execute(
                select(
                    RecurringSeriesAttachment.series_id,
                    func.count(RecurringSeriesAttachment.id),
                ).group_by(RecurringSeriesAttachment.series_id)
            )
        ).all()
    }
    return [
        RecurringRead(
            id=row.id,
            label=row.label,
            account_id=row.account_id,
            category_id=row.category_id,
            frequency=row.frequency,
            next_due=row.next_due,
            amount=row.amount,
            amount_type=row.amount_type,
            status=row.status,
            recurring_type=row.recurring_type,
            custom_type=row.custom_type,
            credit_insurance_rate=row.credit_insurance_rate,
            account_name=accounts.get(row.account_id, ""),
            category_name=categories.get(row.category_id) if row.category_id else None,
            attachment_count=int(attachment_counts.get(row.id, 0)),
        )
        for row in rows
    ]


@router.post("/recurring", response_model=RecurringRead, status_code=201)
async def create_series(
    payload: RecurringCreate, session: AsyncSession = Depends(get_session)
) -> RecurringRead:
    await _require_account(session, payload.account_id)
    if payload.category_id is not None:
        await _require_category(session, payload.category_id)
    series = RecurringSeries(**payload.model_dump())
    session.add(series)
    await session.commit()
    await session.refresh(series)
    return await _series_read(session, series)


@router.patch("/recurring/{series_id}", response_model=RecurringRead)
async def update_series(
    series_id: int, payload: RecurringUpdate, session: AsyncSession = Depends(get_session)
) -> RecurringRead:
    series = await session.get(RecurringSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Serie introuvable")
    await require_account(session, series.account_id, writable=True)
    data = payload.model_dump(exclude_unset=True)
    for required_field in (
        "label",
        "account_id",
        "frequency",
        "next_due",
        "amount_type",
        "status",
        "recurring_type",
    ):
        if required_field in data and data[required_field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Le champ {required_field} ne peut pas être nul",
            )
    if "account_id" in data:
        await _require_account(session, data["account_id"])
    if data.get("category_id") is not None:
        await _require_category(session, data["category_id"])
    recurring_type = data.get("recurring_type", series.recurring_type)
    custom_type = data.get("custom_type", series.custom_type)
    rate = data.get("credit_insurance_rate", series.credit_insurance_rate)
    if recurring_type == "other" and not custom_type and (
        "recurring_type" in data or "custom_type" in data
    ):
        raise HTTPException(
            status_code=422,
            detail="Le type libre est requis lorsque le type « Autre » est sélectionné",
        )
    if recurring_type != "credit_insurance" and rate is not None and (
        "credit_insurance_rate" in data
    ):
        raise HTTPException(
            status_code=422,
            detail="Le taux est réservé aux assurances crédit",
        )
    if recurring_type != "other" and "recurring_type" in data:
        data["custom_type"] = None
    if recurring_type != "credit_insurance" and "recurring_type" in data:
        data["credit_insurance_rate"] = None
    linked_debts: list[Debt] = []
    if "amount" in data:
        linked_debts = list(
            (
                await session.execute(
                    select(Debt).where(Debt.recurring_series_repayment_id == series_id)
                )
            ).scalars().all()
        )
        for debt in linked_debts:
            if debt.account_id is not None:
                await require_account(session, debt.account_id, writable=True)
        if linked_debts:
            data["amount"] = recurring_amount(data["amount"])
    for field, value in data.items():
        setattr(series, field, value)
    if "amount" in data:
        for debt in linked_debts:
            debt.minimum_payment = debt_payment(series.amount)
    await session.commit()
    await session.refresh(series)
    return await _series_read(session, series)


@router.delete("/recurring/{series_id}", status_code=204)
async def delete_series(series_id: int, session: AsyncSession = Depends(get_session)) -> None:
    series = await session.get(RecurringSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Serie introuvable")
    await require_account(session, series.account_id, writable=True)
    attachments = (
        await session.execute(
            select(RecurringSeriesAttachment).where(
                RecurringSeriesAttachment.series_id == series_id
            )
        )
    ).scalars().all()
    for attachment in attachments:
        remove_attachment(attachment.stored_path)
    await session.delete(series)
    await session.commit()


async def _require_series(
    session: AsyncSession,
    series_id: int,
) -> RecurringSeries:
    series = await session.get(RecurringSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    return series


def _attachment_read(
    attachment: RecurringSeriesAttachment,
) -> RecurringSeriesAttachmentRead:
    return RecurringSeriesAttachmentRead(
        id=attachment.id,
        series_id=attachment.series_id,
        original_name=attachment.original_name,
        storage_path=f"/{attachment.stored_path}",
        content_type=attachment.content_type,
        size=attachment.size,
    )


async def _require_attachment(
    session: AsyncSession,
    series_id: int,
    attachment_id: int,
) -> RecurringSeriesAttachment:
    attachment = await session.get(RecurringSeriesAttachment, attachment_id)
    if attachment is None or attachment.series_id != series_id:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable")
    return attachment


@router.get(
    "/recurring/{series_id}/attachments",
    response_model=list[RecurringSeriesAttachmentRead],
)
async def list_attachments(
    series_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[RecurringSeriesAttachmentRead]:
    await _require_series(session, series_id)
    rows = (
        await session.execute(
            select(RecurringSeriesAttachment)
            .where(RecurringSeriesAttachment.series_id == series_id)
            .order_by(
                RecurringSeriesAttachment.created_at,
                RecurringSeriesAttachment.id,
            )
        )
    ).scalars().all()
    return [_attachment_read(row) for row in rows]


@router.post(
    "/recurring/{series_id}/attachments",
    response_model=RecurringSeriesAttachmentRead,
    status_code=201,
)
async def upload_attachment(
    series_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> RecurringSeriesAttachmentRead:
    series = await _require_series(session, series_id)
    await require_account(session, series.account_id, writable=True)
    content_type = file.content_type
    original_name, stored_path, size = await store_attachment(file)
    attachment = RecurringSeriesAttachment(
        series_id=series_id,
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
    return _attachment_read(attachment)


@router.get(
    "/recurring/{series_id}/attachments/{attachment_id}/download",
    response_model=None,
)
async def download_attachment(
    series_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await _require_attachment(session, series_id, attachment_id)
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
    "/recurring/{series_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_attachment(
    series_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    series = await _require_series(session, series_id)
    await require_account(session, series.account_id, writable=True)
    attachment = await _require_attachment(session, series_id, attachment_id)
    remove_attachment(attachment.stored_path)
    await session.delete(attachment)
    await session.commit()


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
@router.get("/recurring/forecast", response_model=list[ForecastPoint])
async def forecast(
    months: int = Query(default=3, ge=1, le=24),
    session: AsyncSession = Depends(get_session),
) -> list[ForecastPoint]:
    today = date.today()
    horizon = add_month(today, months)
    series = (
        await session.execute(
            select(RecurringSeries).where(RecurringSeries.status == "active")
        )
    ).scalars().all()
    accounts = {
        acc.id: acc.name for acc in (await session.execute(select(Account))).scalars().all()
    }
    categories = {
        cat.id: cat.name for cat in (await session.execute(select(Category))).scalars().all()
    }
    points: list[ForecastPoint] = []
    for item in series:
        for due in recurrence_dates(item.next_due, item.frequency, today, horizon):
            points.append(
                ForecastPoint(
                    series_id=item.id,
                    label=item.label,
                    due_date=due,
                    amount=money(item.amount),
                    account_name=accounts.get(item.account_id, ""),
                    category_name=categories.get(item.category_id) if item.category_id else None,
                    status=item.status,
                )
            )
    points.sort(key=lambda point: (point.due_date, point.series_id))
    return points
