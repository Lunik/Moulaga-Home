"""Deterministic, built-in schema migration runner for the SQLite database.

The application historically relied on ``Base.metadata.create_all`` which
creates *missing tables* but never alters *existing* ones. To evolve the
Account/Category schema on databases that already contain user data, this
module performs a tiny, safe, idempotent reconciliation:

* new tables are created by ``create_all``;
* missing columns on pre-existing tables are added with ``ALTER TABLE ... ADD
  COLUMN`` (a non-destructive SQLite operation);
* a timestamped copy of the database file is taken *before* any structural
  change so an upgrade can never lose data.

The persistent schema version is tracked with ``PRAGMA user_version`` so
re-running the app is a no-op once a database is up to date.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base

logger = logging.getLogger("moulaga.migrations")

SCHEMA_VERSION = 8

# Columns that may be missing on databases created before this schema version.
# Values are the SQLite column definitions used by ``ALTER TABLE ADD COLUMN``.
EXPECTED_COLUMNS: dict[str, dict[str, str]] = {
    "accounts": {
        "institution": "VARCHAR(120)",
        "account_number": "VARCHAR(120)",
        "color": "VARCHAR(16) DEFAULT '#4f46e5' NOT NULL",
        "archived": "BOOLEAN DEFAULT 0 NOT NULL",
        "savings_product": "VARCHAR(64)",
        "annual_interest_rate": "NUMERIC(6, 3)",
        "legal_cap": "NUMERIC(12, 2)",
    },
    "transactions": {
        "transfer_group": "VARCHAR(64)",
    },
    "categories": {
        "parent_id": "INTEGER REFERENCES categories(id)",
        "archived": "BOOLEAN DEFAULT 0 NOT NULL",
        "is_default": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "debts": {
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


def _apply_columns(conn: Connection, pending: dict[str, dict[str, str]]) -> None:
    for table, columns in pending.items():
        for name, ddl in columns.items():
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


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

    if (pending or missing_tables) and pre_existing and db_path is not None:
        _backup(db_path, int(version or 0))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_columns, pending)
        await conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        await conn.execute(text("PRAGMA optimize"))

    if pending or missing_tables:
        logger.info("Schema mis a jour vers la version %s", SCHEMA_VERSION)
