"""Categorization rules, inbox and a fully-local deterministic suggester.

The "private AI" suggestion endpoint never contacts any network service. It
derives suggestions purely from existing categorization rules and the history
of already-categorized transactions stored locally.
"""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..account_access import require_account
from ..common import get_preferences
from ..db import get_session
from ..models import Account, CategorizationRule, Category, Transaction
from ..schemas import (
    InboxItem,
    RuleApplyResult,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    SuggestionResult,
)

router = APIRouter(tags=["categorization"])


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _tokens(text: str) -> set[str]:
    normalized = _normalize(text)
    token = []
    result: set[str] = set()
    for ch in normalized:
        if ch.isalnum():
            token.append(ch)
        elif token:
            result.add("".join(token))
            token = []
    if token:
        result.add("".join(token))
    return {tok for tok in result if len(tok) >= 3}


def _rule_matches(rule: CategorizationRule, description: str) -> bool:
    normalized_description = _normalize(description)
    return any(_normalize(pattern) in normalized_description for pattern in _rule_patterns(rule))


def _rule_patterns(rule: CategorizationRule) -> list[str]:
    if rule.patterns_json is None:
        return [rule.pattern]
    values = json.loads(rule.patterns_json)
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
    ):
        raise ValueError("Motifs de regle invalides dans la base locale")
    return values


def _patterns_json(patterns: list[str]) -> str:
    return json.dumps(patterns, ensure_ascii=False)


def _rule_read(rule: CategorizationRule) -> RuleRead:
    patterns = _rule_patterns(rule)
    return RuleRead(
        id=rule.id,
        name=rule.name,
        match_type=rule.match_type,
        pattern=patterns[0],
        patterns=patterns,
        category_id=rule.category_id,
        priority=rule.priority,
        enabled=rule.enabled,
    )


async def _require_category(session: AsyncSession, category_id: int) -> None:
    if await session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="Categorie introuvable")


# --------------------------------------------------------------------------- #
# Rules CRUD
# --------------------------------------------------------------------------- #
@router.get("/rules", response_model=list[RuleRead])
async def list_rules(session: AsyncSession = Depends(get_session)) -> list[RuleRead]:
    rows = (
        await session.execute(
            select(CategorizationRule).order_by(
                CategorizationRule.priority.desc(), CategorizationRule.id
            )
        )
    ).scalars().all()
    return [_rule_read(row) for row in rows]


@router.post("/rules", response_model=RuleRead, status_code=201)
async def create_rule(
    payload: RuleCreate, session: AsyncSession = Depends(get_session)
) -> RuleRead:
    await _require_category(session, payload.category_id)
    rule = CategorizationRule(
        name=payload.name,
        match_type=payload.match_type,
        pattern=payload.patterns[0],
        patterns_json=_patterns_json(payload.patterns),
        category_id=payload.category_id,
        priority=payload.priority,
        enabled=payload.enabled,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _rule_read(rule)


@router.patch("/rules/{rule_id}", response_model=RuleRead)
async def update_rule(
    rule_id: int, payload: RuleUpdate, session: AsyncSession = Depends(get_session)
) -> RuleRead:
    rule = await session.get(CategorizationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regle introuvable")
    data = payload.model_dump(exclude_unset=True, exclude={"pattern", "patterns"})
    if data.get("category_id") is not None:
        await _require_category(session, data["category_id"])
    if payload.patterns is not None:
        rule.pattern = payload.patterns[0]
        rule.patterns_json = _patterns_json(payload.patterns)
    for field, value in data.items():
        setattr(rule, field, value)
    await session.commit()
    await session.refresh(rule)
    return _rule_read(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, session: AsyncSession = Depends(get_session)) -> None:
    rule = await session.get(CategorizationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regle introuvable")
    await session.delete(rule)
    await session.commit()


@router.post("/rules/apply", response_model=RuleApplyResult)
async def apply_rules(
    only_uncategorized: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
) -> RuleApplyResult:
    """Deterministically apply enabled rules ordered by descending priority."""
    rules = (
        await session.execute(
            select(CategorizationRule)
            .where(CategorizationRule.enabled.is_(True))
            .order_by(CategorizationRule.priority.desc(), CategorizationRule.id)
        )
    ).scalars().all()

    statement = (
        select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(
            Transaction.transfer_group.is_(None),
            Account.archived.is_(False),
        )
    )
    if only_uncategorized:
        statement = statement.where(Transaction.category_id.is_(None))
    transactions = (await session.execute(statement)).scalars().all()

    updated = 0
    for transaction in transactions:
        for rule in rules:
            if _rule_matches(rule, transaction.description):
                if transaction.category_id != rule.category_id:
                    transaction.category_id = rule.category_id
                    updated += 1
                break
    await session.commit()
    return RuleApplyResult(updated=updated, scanned=len(transactions))


# --------------------------------------------------------------------------- #
# Inbox + local suggestions
# --------------------------------------------------------------------------- #
@router.get("/categorization/inbox", response_model=list[InboxItem])
async def inbox(
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[InboxItem]:
    rows = (
        await session.execute(
            select(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .where(
                Transaction.category_id.is_(None),
                Transaction.transfer_group.is_(None),
                Account.archived.is_(False),
            )
            .order_by(Transaction.booked_at.desc(), Transaction.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        InboxItem(
            transaction_id=row.id,
            booked_at=row.booked_at,
            description=row.description,
            amount=row.amount,
            account_id=row.account_id,
        )
        for row in rows
    ]


@router.post("/categorization/suggest/{transaction_id}", response_model=SuggestionResult)
async def suggest(
    transaction_id: int, session: AsyncSession = Depends(get_session)
) -> SuggestionResult:
    """Local, deterministic category suggestion. No network calls, ever.

    Honors ``private_categorization_mode``:

    * ``off``    -> the feature is refused (HTTP 403);
    * ``suggest`` -> a suggestion is returned but never written;
    * ``auto``   -> the suggested category is applied to the transaction, but
      only when the computed confidence is >= the configured threshold.
    """
    prefs = await get_preferences(session)
    if not prefs.private_categorization_enabled:
        raise HTTPException(
            status_code=403, detail="Categorisation privee desactivee dans les preferences"
        )
    mode = prefs.private_categorization_mode
    if mode == "off":
        raise HTTPException(
            status_code=403, detail="Mode de categorisation privee desactive (off)"
        )

    transaction = await session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    await require_account(session, transaction.account_id, writable=True)
    if transaction.transfer_group is not None:
        raise HTTPException(
            status_code=409,
            detail="Un transfert interne ne doit pas etre categorise",
        )

    threshold = Decimal(prefs.private_categorization_confidence)

    async def _finalize(
        category_id: int | None,
        category_name: str | None,
        confidence: Decimal,
        explanation: str,
        source: str,
    ) -> SuggestionResult:
        applied = False
        # Only ``auto`` writes, and only above the confidence threshold, and
        # only when a concrete category was resolved.
        if (
            mode == "auto"
            and category_id is not None
            and confidence >= threshold
            and transaction.category_id is None
        ):
            transaction.category_id = category_id
            await session.commit()
            applied = True
        return SuggestionResult(
            transaction_id=transaction_id,
            category_id=category_id,
            category_name=category_name,
            confidence=confidence,
            explanation=explanation,
            source=source,
            applied=applied,
        )

    # 1) An explicit enabled rule is the strongest, deterministic signal.
    rules = (
        await session.execute(
            select(CategorizationRule)
            .where(CategorizationRule.enabled.is_(True))
            .order_by(CategorizationRule.priority.desc(), CategorizationRule.id)
        )
    ).scalars().all()
    for rule in rules:
        if _rule_matches(rule, transaction.description):
            category = await session.get(Category, rule.category_id)
            return await _finalize(
                rule.category_id,
                category.name if category else None,
                Decimal("0.99"),
                f"Regle '{rule.name}' correspondante",
                "rule",
            )

    # 2) Otherwise, score against locally categorized history by token overlap.
    target_tokens = _tokens(transaction.description)
    best_category, confidence, matched = _score_history(
        target_tokens,
        (
            await session.execute(
                select(Transaction.description, Transaction.category_id)
                .join(Account, Transaction.account_id == Account.id)
                .where(
                    Transaction.category_id.is_not(None),
                    Transaction.id != transaction_id,
                    Transaction.transfer_group.is_(None),
                    Account.archived.is_(False),
                )
            )
        ).all(),
    )

    if best_category is None or confidence < threshold:
        return SuggestionResult(
            transaction_id=transaction_id,
            category_id=None,
            category_name=None,
            confidence=confidence,
            explanation="Confiance insuffisante pour une suggestion locale",
            source="none",
            applied=False,
        )

    category = await session.get(Category, best_category)
    return await _finalize(
        best_category,
        category.name if category else None,
        confidence,
        f"{matched} operation(s) similaire(s) deja classee(s)",
        "history",
    )


def _score_history(
    target_tokens: set[str],
    history: list[tuple[str, int | None]],
) -> tuple[int | None, Decimal, int]:
    """Return (category_id, confidence, matching_count) from token overlap."""
    if not target_tokens:
        return None, Decimal("0.00"), 0

    scores: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: dict[int, int] = defaultdict(int)
    for description, category_id in history:
        if category_id is None:
            continue
        overlap = target_tokens & _tokens(description)
        if not overlap:
            continue
        similarity = Decimal(len(overlap)) / Decimal(len(target_tokens))
        scores[category_id] += similarity
        counts[category_id] += 1

    if not scores:
        return None, Decimal("0.00"), 0

    total = sum(scores.values())
    best = max(scores, key=lambda cid: (scores[cid], counts[cid]))
    confidence = (scores[best] / total).quantize(Decimal("0.01")) if total else Decimal("0.00")
    return best, confidence, counts[best]
