"""One-shot migration of a Banque_v3 CSV export into Moulaga."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal, init_db
from ..models import Account, Category, Transaction

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_AMOUNT = Decimal("10000000000")
SUPPORTED_SUFFIXES = {".csv", ".txt"}


class MigrationError(ValueError):
    """Raised when the source cannot be safely migrated."""


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped_duplicates: int
    errors: tuple[str, ...] = ()


async def migrate_csv(csv_path: Path, account_name: str) -> ImportResult:
    """Import one CSV atomically into the configured persistent database."""
    clean_account_name = account_name.strip()
    if not 1 <= len(clean_account_name) <= 120:
        raise MigrationError("Le nom du compte doit contenir entre 1 et 120 caracteres.")

    rows = _read_rows(csv_path)
    settings.ensure_dirs()
    await init_db()
    async with SessionLocal() as session:
        return await _migrate_rows(session, rows, clean_account_name)


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    if csv_path.suffix.casefold() not in SUPPORTED_SUFFIXES:
        raise MigrationError("Exporte Banque_v3 au format CSV avant de lancer la migration.")
    if not csv_path.is_file():
        raise MigrationError("Le fichier CSV est introuvable.")
    if csv_path.stat().st_size > MAX_IMPORT_BYTES:
        raise MigrationError("Le fichier CSV depasse la limite de 10 Mio.")

    try:
        text = csv_path.read_text(encoding="utf-8-sig")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except UnicodeDecodeError as exc:
        raise MigrationError("Le fichier CSV doit etre encode en UTF-8.") from exc
    except csv.Error as exc:
        raise MigrationError("Le format du fichier CSV est invalide.") from exc

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise MigrationError("Le CSV doit contenir une ligne d'en-tetes.")
    return list(reader)


async def _migrate_rows(
    session: AsyncSession,
    rows: list[dict[str, str]],
    account_name: str,
) -> ImportResult:
    account = await _get_or_create_account(session, account_name)
    categories = (await session.execute(select(Category))).scalars().all()
    category_by_name = {category.name.casefold(): category for category in categories}

    parsed_rows: list[Transaction] = []
    errors: list[str] = []
    error_count = 0
    for line_number, row in enumerate(rows, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            parsed_rows.append(_parse_row(row, account.id, category_by_name))
        except ValueError as exc:
            error_count += 1
            if len(errors) < 50:
                errors.append(f"Ligne {line_number}: {exc}")

    if error_count:
        if error_count > len(errors):
            errors.append(f"{error_count - len(errors)} erreur(s) supplementaire(s) non affichee(s).")
        await session.rollback()
        return ImportResult(imported=0, skipped_duplicates=0, errors=tuple(errors))

    pending: list[Transaction] = []
    seen_hashes: set[str] = set()
    skipped = 0
    for transaction in parsed_rows:
        source_hash = transaction.source_hash
        if source_hash is None or source_hash in seen_hashes:
            skipped += 1
            continue
        exists = await session.scalar(
            select(Transaction.id).where(Transaction.source_hash == source_hash)
        )
        if exists is not None:
            skipped += 1
            continue
        seen_hashes.add(source_hash)
        pending.append(transaction)

    session.add_all(pending)
    await session.commit()
    return ImportResult(imported=len(pending), skipped_duplicates=skipped)


async def _get_or_create_account(session: AsyncSession, name: str) -> Account:
    existing = await session.scalar(select(Account).where(Account.name == name))
    if existing is not None:
        return existing
    account = Account(name=name, type="checking", currency="EUR")
    session.add(account)
    await session.flush()
    return account


def _parse_row(
    row: dict[str, str],
    account_id: int,
    category_by_name: dict[str, Category],
) -> Transaction:
    normalized = {_normalize_header(key): (value or "").strip() for key, value in row.items() if key}
    booked_at = _parse_date(_first(normalized, "date", "operation_date", "booking_date", "jour"))
    description = _first(normalized, "description", "libelle", "label", "operation", "details")
    if len(description) > 500:
        raise ValueError("libelle trop long (500 caracteres maximum)")
    amount = _parse_amount(normalized)
    if abs(amount) >= MAX_AMOUNT:
        raise ValueError("montant hors limites")
    category_name = _optional(normalized, "categorie", "category")
    category = category_by_name.get(category_name.casefold()) if category_name else None
    source = "|".join([booked_at.isoformat(), description, str(amount), str(account_id)])
    return Transaction(
        booked_at=booked_at,
        description=description,
        amount=amount,
        account_id=account_id,
        category_id=category.id if category else None,
        source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value
    raise ValueError(f"colonne manquante: {'/'.join(names)}")


def _optional(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value:
            return value
    return None


def _parse_date(value: str) -> date:
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise ValueError("date invalide")


def _parse_amount(row: dict[str, str]) -> Decimal:
    if row.get("montant") or row.get("amount"):
        return _to_decimal(row.get("montant") or row.get("amount") or "0")
    debit = _to_decimal(row["debit"]) if row.get("debit") else Decimal("0.00")
    credit = _to_decimal(row["credit"]) if row.get("credit") else Decimal("0.00")
    if debit == 0 and credit == 0:
        raise ValueError("montant manquant")
    return credit - abs(debit)


def _to_decimal(value: str) -> Decimal:
    cleaned = (
        value.replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
        .replace("EUR", "")
        .replace("€", "")
    )
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("montant invalide") from exc


def _normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
    return without_accents.replace(" ", "_")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migre une seule fois un export CSV de Banque_v3 vers la base persistante Moulaga."
    )
    parser.add_argument("csv_file", type=Path, help="Chemin local vers l'export CSV confidentiel.")
    parser.add_argument(
        "--account",
        default="Compte courant",
        help="Compte Moulaga cible (defaut: Compte courant).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(migrate_csv(args.csv_file, args.account))
    except MigrationError as exc:
        print(f"Migration annulee: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Migration annulee: impossible de lire le fichier ou la base locale.", file=sys.stderr)
        return 1

    if result.errors:
        print("Migration annulee: aucune ligne n'a ete enregistree.", file=sys.stderr)
        for error in result.errors:
            print(error, file=sys.stderr)
        return 1

    print(
        f"Migration terminee: {result.imported} transaction(s) ajoutee(s), "
        f"{result.skipped_duplicates} doublon(s) ignore(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
