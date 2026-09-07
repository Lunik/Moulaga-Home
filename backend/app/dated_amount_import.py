"""Strict parsing shared by pasted TSV imports containing a date and an amount."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

MAX_IMPORT_ROWS = 1000
MAX_AMOUNT = Decimal("10000000000")
_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_AMOUNT_PATTERN = re.compile(
    r"^[+-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d{1,2})?$"
)


class DatedAmountImportError(ValueError):
    """Raised when pasted date/amount TSV data cannot be imported safely."""


@dataclass(frozen=True)
class DatedAmountImportRow:
    due_date: date
    amount: Decimal
    source_line: int


def parse_dated_amount_tsv(
    content: str,
    *,
    amount_headers: frozenset[str] = frozenset({"montant"}),
) -> list[DatedAmountImportRow]:
    rows: list[DatedAmountImportRow] = []
    source_line_by_date: dict[date, int] = {}
    first_non_empty_line = True

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue

        columns = raw_line.split("\t")
        if len(columns) != 2:
            raise DatedAmountImportError(
                f"Ligne {line_number} : deux colonnes séparées par une tabulation sont requises."
            )

        raw_date = columns[0].strip().lstrip("\ufeff")
        raw_amount = columns[1].strip()
        if first_non_empty_line:
            first_non_empty_line = False
            if raw_date.casefold() == "date" and raw_amount.casefold() in amount_headers:
                continue

        if len(rows) >= MAX_IMPORT_ROWS:
            raise DatedAmountImportError(
                f"Ligne {line_number} : l'import est limité à {MAX_IMPORT_ROWS} lignes."
            )

        if not _DATE_PATTERN.fullmatch(raw_date):
            raise DatedAmountImportError(
                f"Ligne {line_number} : la date doit respecter le format DD/MM/YYYY."
            )
        try:
            parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
        except ValueError as exc:
            raise DatedAmountImportError(
                f"Ligne {line_number} : la date « {raw_date} » est invalide."
            ) from exc

        previous_line = source_line_by_date.get(parsed_date)
        if previous_line is not None:
            raise DatedAmountImportError(
                f"Ligne {line_number} : la date {raw_date} est déjà présente "
                f"à la ligne {previous_line}."
            )

        numeric_amount = raw_amount.removesuffix("€").strip()
        if not _AMOUNT_PATTERN.fullmatch(numeric_amount):
            raise DatedAmountImportError(
                f"Ligne {line_number} : le montant « {raw_amount} » est invalide."
            )
        normalized_amount = re.sub(
            r"[ \u00a0\u202f]", "", numeric_amount
        ).replace(",", ".")
        amount = Decimal(normalized_amount)
        if abs(amount) >= MAX_AMOUNT:
            raise DatedAmountImportError(
                f"Ligne {line_number} : le montant est hors limites."
            )

        rows.append(
            DatedAmountImportRow(
                due_date=parsed_date,
                amount=amount,
                source_line=line_number,
            )
        )
        source_line_by_date[parsed_date] = line_number

    if not rows:
        raise DatedAmountImportError("Aucune ligne à importer.")
    return rows
