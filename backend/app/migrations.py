"""Deterministic, built-in schema migration runner for the SQLite database.

The application historically relied on ``Base.metadata.create_all`` which
creates *missing tables* but never alters *existing* ones. To evolve the
Account/Category schema on databases that already contain user data, this
module performs a tiny, safe, idempotent reconciliation:

* new tables are created by ``create_all``;
* missing columns on pre-existing tables are added with ``ALTER TABLE ... ADD
  COLUMN`` (a non-destructive SQLite operation);
* constrained tables are rebuilt transactionally when columns or constraints
  must change;
* tables belonging to explicitly retired features are removed after the backup;
* legacy ledger-derived balances are materialized before account statements
  become authoritative;
* a timestamped copy of the database file is taken *before* any structural
  change so an upgrade can never lose data.

The persistent schema version is tracked with ``PRAGMA user_version`` so
re-running the app is a no-op once a database is up to date.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base

logger = logging.getLogger("moulaga.migrations")

SCHEMA_VERSION = 19
OBSOLETE_TABLES = frozenset(
    {
        "categorization_rules",
        "debt_schedule_entries",
        "merchant_identities",
        "recurring_changes",
        "recurring_schedule_entries",
        "transaction_attachments",
        "transactions",
    }
)
OBSOLETE_COLUMNS: dict[str, frozenset[str]] = {
    "recurring_series": frozenset({"confidence", "match_key"}),
}

# Columns that may be missing on databases created before this schema version.
# Values are the SQLite column definitions used by ``ALTER TABLE ADD COLUMN``.
EXPECTED_COLUMNS: dict[str, dict[str, str]] = {
    "real_estate_assets": {
        "icon_path": "VARCHAR(512)",
    },
    "accounts": {
        "institution": "VARCHAR(120)",
        "regional_entity": "VARCHAR(120)",
        "account_number": "VARCHAR(120)",
        "color": "VARCHAR(16) DEFAULT '#4f46e5' NOT NULL",
        "archived": "BOOLEAN DEFAULT 0 NOT NULL",
        "savings_product": "VARCHAR(64)",
        "annual_interest_rate": "NUMERIC(6, 3)",
        "legal_cap": "NUMERIC(12, 2)",
    },
    "categories": {
        "parent_id": "INTEGER REFERENCES categories(id)",
        "archived": "BOOLEAN DEFAULT 0 NOT NULL",
        "is_default": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "recurring_series": {
        "recurring_type": "VARCHAR(32) DEFAULT 'uncategorized' NOT NULL",
        "custom_type": "VARCHAR(120)",
        "credit_insurance_rate": "NUMERIC(6, 3)",
    },
    "work_contracts": {
        "payment_period_months": "INTEGER DEFAULT 12 NOT NULL",
        "recurring_series_id": (
            "INTEGER REFERENCES recurring_series(id) ON DELETE SET NULL"
        ),
    },
    "debts": {
        "debt_type": "VARCHAR(32) DEFAULT 'other' NOT NULL",
        "recurring_series_repayment_id": (
            "INTEGER REFERENCES recurring_series(id) ON DELETE SET NULL"
        ),
        "recurring_series_insurance_id": (
            "INTEGER REFERENCES recurring_series(id) ON DELETE SET NULL"
        ),
        "due_date": "DATE",
        "color": "VARCHAR(16) DEFAULT '#ef4444' NOT NULL",
        "archived": "BOOLEAN DEFAULT 0 NOT NULL",
    },
}


def sqlite_file_path(sqlalchemy_url: str) -> Path | None:
    """Return the on-disk path for a file-backed SQLite URL, else ``None``."""
    if "sqlite" not in sqlalchemy_url or ":///" not in sqlalchemy_url:
        return None
    raw = sqlalchemy_url.split(":///", 1)[1]
    if not raw or raw == ":memory:":
        return None
    return Path(raw)


def _table_exists(conn: Connection, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table},
    ).first()
    return row is not None


def _existing_columns(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {row[1] for row in rows}


def _pending_columns(conn: Connection) -> dict[str, dict[str, str]]:
    """Missing columns per pre-existing table (empty for fresh databases)."""
    pending: dict[str, dict[str, str]] = {}
    for table, columns in EXPECTED_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        present = _existing_columns(conn, table)
        missing = {name: ddl for name, ddl in columns.items() if name not in present}
        if missing:
            pending[table] = missing
    return pending


def _missing_tables(conn: Connection) -> set[str]:
    return {table for table in Base.metadata.tables if not _table_exists(conn, table)}


def _existing_obsolete_tables(conn: Connection) -> set[str]:
    return {table for table in OBSOLETE_TABLES if _table_exists(conn, table)}


def _existing_obsolete_columns(conn: Connection) -> dict[str, set[str]]:
    obsolete: dict[str, set[str]] = {}
    for table, columns in OBSOLETE_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        present = _existing_columns(conn, table)
        found = present.intersection(columns)
        if found:
            obsolete[table] = found
    return obsolete


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _drop_obsolete_columns(
    conn: Connection, obsolete_columns: dict[str, set[str]]
) -> None:
    for table, columns in obsolete_columns.items():
        indexes = conn.execute(text(f"PRAGMA index_list({_quote_identifier(table)})")).all()
        for index in indexes:
            index_name = index[1]
            indexed_columns = {
                row[2]
                for row in conn.execute(
                    text(f"PRAGMA index_info({_quote_identifier(index_name)})")
                ).all()
            }
            if indexed_columns.intersection(columns):
                conn.execute(text(f"DROP INDEX {_quote_identifier(index_name)}"))
        for column in sorted(columns):
            conn.execute(
                text(
                    f"ALTER TABLE {_quote_identifier(table)} "
                    f"DROP COLUMN {_quote_identifier(column)}"
                )
            )


def _requires_balance_snapshot_backfill(conn: Connection, version: int) -> bool:
    return (
        version < 16
        and _table_exists(conn, "accounts")
        and _table_exists(conn, "transactions")
    )


def _retired_attachment_paths(conn: Connection) -> list[str]:
    if not _table_exists(conn, "transaction_attachments"):
        return []
    return list(
        conn.execute(
            text("SELECT stored_path FROM transaction_attachments ORDER BY id")
        ).scalars()
    )


def _apply_columns(conn: Connection, pending: dict[str, dict[str, str]]) -> None:
    for table, columns in pending.items():
        for name, ddl in columns.items():
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _real_estate_requires_rebuild(conn: Connection) -> bool:
    if not _table_exists(conn, "real_estate_assets"):
        return False
    rows = conn.execute(text("PRAGMA table_info(real_estate_assets)")).all()
    return any(row[1] == "debt_id" for row in rows) or any(
        row[1] == "current_value" and bool(row[3]) for row in rows
    )


def _rebuild_real_estate_assets(conn: Connection) -> None:
    asset_table = Base.metadata.tables["real_estate_assets"]
    link_table = Base.metadata.tables["real_estate_debt_links"]
    attachment_table = Base.metadata.tables["real_estate_attachments"]
    legacy_table = "real_estate_assets_legacy"
    existing_columns = _existing_columns(conn, "real_estate_assets")
    links: set[tuple[int, int]] = set()
    attachments: list[dict[str, object]] = []
    if "debt_id" in existing_columns:
        links.update(
            (asset_id, debt_id)
            for asset_id, debt_id in conn.execute(
                text(
                    "SELECT id, debt_id FROM real_estate_assets "
                    "WHERE debt_id IS NOT NULL"
                )
            )
        )
    if _table_exists(conn, "real_estate_debt_links"):
        links.update(
            (asset_id, debt_id)
            for asset_id, debt_id in conn.execute(
                text("SELECT asset_id, debt_id FROM real_estate_debt_links")
            )
        )
        conn.execute(text("DROP TABLE real_estate_debt_links"))
    if _table_exists(conn, "real_estate_attachments"):
        attachments = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM real_estate_attachments"))
        ]
        conn.execute(text("DROP TABLE real_estate_attachments"))

    copied_columns = [
        column.name for column in asset_table.columns if column.name in existing_columns
    ]
    columns = ", ".join(copied_columns)

    conn.execute(text(f"ALTER TABLE real_estate_assets RENAME TO {legacy_table}"))
    conn.execute(text("DROP INDEX IF EXISTS ix_real_estate_assets_debt_id"))
    asset_table.create(conn)
    conn.execute(
        text(
            f"INSERT INTO real_estate_assets ({columns}) "
            f"SELECT {columns} FROM {legacy_table}"
        )
    )
    conn.execute(text(f"DROP TABLE {legacy_table}"))
    link_table.create(conn)
    attachment_table.create(conn)
    if links:
        conn.execute(
            link_table.insert(),
            [
                {"asset_id": asset_id, "debt_id": debt_id}
                for asset_id, debt_id in sorted(links)
            ],
        )
    if attachments:
        attachment_columns = [
            column.name
            for column in attachment_table.columns
            if column.name in attachments[0]
        ]
        columns_sql = ", ".join(attachment_columns)
        values_sql = ", ".join(f":{column}" for column in attachment_columns)
        conn.execute(
            text(
                f"INSERT INTO real_estate_attachments ({columns_sql}) "
                f"VALUES ({values_sql})"
            ),
            attachments,
        )


def _backfill_current_balance_snapshots(conn: Connection) -> None:
    """Preserve ledger-derived balances before statements become authoritative."""
    current_day = date.today()
    current_period = current_day.strftime("%Y-%m")
    created_at = datetime.now().astimezone().isoformat()
    account_rows = conn.execute(
        text("SELECT id, initial_balance FROM accounts ORDER BY id")
    ).all()

    for account_id, initial_balance in account_rows:
        latest_snapshot = conn.execute(
            text(
                "SELECT period, balance FROM balance_snapshots "
                "WHERE account_id = :account_id AND period <= :current_period "
                "ORDER BY period DESC LIMIT 1"
            ),
            {
                "account_id": account_id,
                "current_period": current_period,
            },
        ).first()
        latest_period = latest_snapshot[0] if latest_snapshot is not None else None
        balance = Decimal(
            str(latest_snapshot[1] if latest_snapshot is not None else initial_balance)
        )
        transaction_total = conn.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM transactions "
                "WHERE account_id = :account_id "
                "AND booked_at <= :current_day "
                "AND (:latest_period IS NULL "
                "OR strftime('%Y-%m', booked_at) > :latest_period)"
            ),
            {
                "account_id": account_id,
                "current_day": current_day.isoformat(),
                "latest_period": latest_period,
            },
        ).scalar_one()
        balance += Decimal(str(transaction_total or 0))
        conn.execute(
            text(
                "INSERT INTO balance_snapshots "
                "(account_id, period, balance, created_at) "
                "VALUES (:account_id, :period, :balance, :created_at) "
                "ON CONFLICT(account_id, period) DO UPDATE "
                "SET balance = excluded.balance"
            ),
            {
                "account_id": account_id,
                "period": current_period,
                "balance": str(balance.quantize(Decimal("0.01"))),
                "created_at": created_at,
            },
        )


def _backup(db_path: Path, from_version: int) -> None:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}.backup-{stamp}-v{from_version}.db")
    shutil.copy2(db_path, backup)
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            shutil.copy2(side, backup.with_name(backup.name + suffix))
    # Never log the concrete path: it can reveal a private data directory.
    logger.info("Sauvegarde de securite creee avant migration du schema")


async def run_migrations(engine: AsyncEngine, db_path: Path | None) -> None:
    """Reconcile the persistent schema, backing up existing data first."""
    pre_existing = db_path is not None and db_path.exists() and db_path.stat().st_size > 0

    async with engine.connect() as conn:
        version = await conn.scalar(text("PRAGMA user_version"))
        pending = await conn.run_sync(_pending_columns)
        missing_tables = await conn.run_sync(_missing_tables)
        obsolete_tables = await conn.run_sync(_existing_obsolete_tables)
        obsolete_columns = await conn.run_sync(_existing_obsolete_columns)
        requires_real_estate_rebuild = await conn.run_sync(_real_estate_requires_rebuild)
        requires_balance_backfill = await conn.run_sync(
            _requires_balance_snapshot_backfill,
            int(version or 0),
        )
        retired_attachment_paths = await conn.run_sync(_retired_attachment_paths)

    if (
        pending
        or missing_tables
        or obsolete_tables
        or obsolete_columns
        or requires_real_estate_rebuild
        or requires_balance_backfill
    ) and pre_existing and db_path is not None:
        _backup(db_path, int(version or 0))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_columns, pending)
        if requires_real_estate_rebuild:
            await conn.run_sync(_rebuild_real_estate_assets)
        if requires_balance_backfill:
            await conn.run_sync(_backfill_current_balance_snapshots)
        await conn.run_sync(_drop_obsolete_columns, obsolete_columns)
        for table in sorted(obsolete_tables):
            await conn.execute(text(f"DROP TABLE {table}"))
        await conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        await conn.execute(text("PRAGMA optimize"))

    if db_path is not None:
        data_root = db_path.parent.resolve()
        failed_attachment_removals = 0
        for stored_path in retired_attachment_paths:
            attachment_path = (data_root / stored_path).resolve()
            if not attachment_path.is_relative_to(data_root):
                failed_attachment_removals += 1
                continue
            try:
                attachment_path.unlink(missing_ok=True)
            except OSError:
                failed_attachment_removals += 1
        if failed_attachment_removals:
            logger.warning(
                "%s piece(s) jointe(s) de transactions n'ont pas pu etre supprimees",
                failed_attachment_removals,
            )

    if (
        pending
        or missing_tables
        or obsolete_tables
        or obsolete_columns
        or requires_real_estate_rebuild
        or requires_balance_backfill
    ):
        logger.info("Schema mis a jour vers la version %s", SCHEMA_VERSION)
