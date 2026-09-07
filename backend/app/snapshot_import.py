"""Strict parsing for pasted monthly balance snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .dated_amount_import import (
    DatedAmountImportError,
    parse_dated_amount_tsv,
)


class SnapshotImportError(ValueError):
    """Raised when pasted TSV data cannot be imported safely."""


@dataclass(frozen=True)
class SnapshotImportRow:
    period: str
    balance: Decimal


def parse_snapshot_tsv(content: str) -> list[SnapshotImportRow]:
    rows: list[SnapshotImportRow] = []
    source_line_by_period: dict[str, int] = {}
    try:
        imported_rows = parse_dated_amount_tsv(
            content,
            amount_headers=frozenset({"montant", "solde"}),
        )
    except DatedAmountImportError as exc:
        message = str(exc)
        if message == "Aucune ligne à importer.":
            message = "Aucun relevé à importer."
        raise SnapshotImportError(message) from exc

    for imported_row in imported_rows:
        period = imported_row.due_date.strftime("%Y-%m")
        previous_line = source_line_by_period.get(period)
        if previous_line is not None:
            raise SnapshotImportError(
                f"Ligne {imported_row.source_line} : le mois "
                f"{imported_row.due_date.strftime('%m/%Y')} "
                f"est déjà présent à la ligne {previous_line}."
            )

        rows.append(SnapshotImportRow(period=period, balance=imported_row.amount))
        source_line_by_period[period] = imported_row.source_line
    return rows
