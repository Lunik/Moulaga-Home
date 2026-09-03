"""Transaction mutations that complement the core ledger in ``budget.py``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_session
from ..models import Account, Category, Transaction
from ..schemas import TransactionRead, TransactionUpdate

router = APIRouter(tags=["transactions"])


def _read(transaction: Transaction) -> TransactionRead:
    return TransactionRead.model_validate(transaction).model_copy(
        update={
            "account_name": transaction.account.name,
            "category_name": transaction.category.name if transaction.category else None,
            "category_kind": transaction.category.kind if transaction.category else None,
        }
    )


async def _load(session: AsyncSession, transaction_id: int) -> Transaction:
    statement = (
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.category))
        .where(Transaction.id == transaction_id)
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


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    session: AsyncSession = Depends(get_session),
) -> TransactionRead:
    transaction = await _load(session, transaction_id)
    data = payload.model_dump(exclude_unset=True)

    if "account_id" in data and await session.get(Account, data["account_id"]) is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
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
    transaction = await session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    await session.delete(transaction)
    await session.commit()
