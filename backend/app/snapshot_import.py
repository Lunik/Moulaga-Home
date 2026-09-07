"""Strict parsing for pasted monthly balance snapshots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

MAX_IMPORT_ROWS = 1000
MAX_AMOUNT = Decimal("10000000000")
_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_AMOUNT_PATTERN = re.compile(
    r"^[+-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d{1,2})?$"
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
    first_non_empty_line = True

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue

        columns = raw_line.split("\t")
        if len(columns) != 2:
            raise SnapshotImportError(
                f"Ligne {line_number} : deux colonnes séparées par une tabulation sont requises."
            )

        raw_date = columns[0].strip().lstrip("\ufeff")
        raw_amount = columns[1].strip()
        if first_non_empty_line:
            first_non_empty_line = False
            if raw_date.casefold() == "date" and raw_amount.casefold() in {
                "montant",
                "solde",
            }:
                continue

        if len(rows) >= MAX_IMPORT_ROWS:
            raise SnapshotImportError(
                f"Ligne {line_number} : l'import est limité à {MAX_IMPORT_ROWS} relevés."
            )

        if not _DATE_PATTERN.fullmatch(raw_date):
            raise SnapshotImportError(
                f"Ligne {line_number} : la date doit respecter le format DD/MM/YYYY."
            )
        try:
            parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
        except ValueError as exc:
            raise SnapshotImportError(
                f"Ligne {line_number} : la date « {raw_date} » est invalide."
            ) from exc

        period = parsed_date.strftime("%Y-%m")
        previous_line = source_line_by_period.get(period)
        if previous_line is not None:
            raise SnapshotImportError(
                f"Ligne {line_number} : le mois {parsed_date.strftime('%m/%Y')} "
                f"est déjà présent à la ligne {previous_line}."
            )

        numeric_amount = raw_amount.removesuffix("€").strip()
        if not _AMOUNT_PATTERN.fullmatch(numeric_amount):
            raise SnapshotImportError(
                f"Ligne {line_number} : le montant « {raw_amount} » est invalide."
            )
        normalized_amount = re.sub(
            r"[ \u00a0\u202f]", "", numeric_amount
        ).replace(",", ".")
        balance = Decimal(normalized_amount)
        if abs(balance) >= MAX_AMOUNT:
            raise SnapshotImportError(
                f"Ligne {line_number} : le montant est hors limites."
            )

        rows.append(SnapshotImportRow(period=period, balance=balance))
        source_line_by_period[period] = line_number

    if not rows:
        raise SnapshotImportError("Aucun relevé à importer.")
    return rows
