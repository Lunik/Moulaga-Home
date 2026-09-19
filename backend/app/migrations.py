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
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base

logger = logging.getLogger("moulaga.migrations")

MULTI_USER_SCHEMA_VERSION = 26
SCHEMA_VERSION = 29
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
    "balance_snapshots": {
        "document_ignored": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "real_estate_assets": {
        "icon_path": "VARCHAR(512)",
        "document_ignored": "BOOLEAN DEFAULT 0 NOT NULL",
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
    "household_members": {
        "avatar": "VARCHAR(512)",
        "color": "VARCHAR(16) DEFAULT '#4f46e5' NOT NULL",
        "active": "BOOLEAN DEFAULT 1 NOT NULL",
        "pin_hash": "VARCHAR(256)",
        "pin_failed_attempts": "INTEGER DEFAULT 0 NOT NULL",
        "pin_locked_until": "DATETIME",
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
        "document_ignored": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "work_contracts": {
        "profile_id": "INTEGER REFERENCES household_members(id) ON DELETE RESTRICT",
        "payment_period_months": "INTEGER DEFAULT 12 NOT NULL",
        "recurring_series_id": (
            "INTEGER REFERENCES recurring_series(id) ON DELETE SET NULL"
        ),
        "document_ignored": "BOOLEAN DEFAULT 0 NOT NULL",
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
        "document_ignored": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "pay_slips": {
        "profile_id": "INTEGER REFERENCES household_members(id) ON DELETE RESTRICT",
        "document_ignored": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "pension_profiles": {
        "profile_id": "INTEGER REFERENCES household_members(id) ON DELETE RESTRICT",
        "birth_month": "INTEGER DEFAULT 1 NOT NULL",
        "income_growth_scenario": "VARCHAR(24) DEFAULT 'regular' NOT NULL",
        "future_work_percentage": "INTEGER DEFAULT 100 NOT NULL",
        "planned_unemployment_months": "INTEGER DEFAULT 0 NOT NULL",
    },
    "holding_operations": {
        "occurred_on": "DATE",
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


def _account_name_is_unique(conn: Connection) -> bool:
    """Whether a legacy ``accounts.name`` unique index still needs removal."""
    if not _table_exists(conn, "accounts"):
        return False
    for index in conn.execute(text("PRAGMA index_list(accounts)")).all():
        if not index[2]:
            continue
        columns = [
            row[2]
            for row in conn.execute(text(f"PRAGMA index_info({_quote_identifier(index[1])})")).all()
        ]
        if columns == ["name"]:
            return True
    return False


def _pension_profile_unique_index_missing(conn: Connection) -> bool:
    if (
        not _table_exists(conn, "pension_profiles")
        or "profile_id" not in _existing_columns(conn, "pension_profiles")
    ):
        return False
    for index in conn.execute(text("PRAGMA index_list(pension_profiles)")).all():
        if not index[2]:
            continue
        columns = [
            row[2]
            for row in conn.execute(
                text(f"PRAGMA index_info({_quote_identifier(index[1])})")
            ).all()
        ]
        if columns == ["profile_id"]:
            return False
    return True


def _ensure_pension_profile_unique_index(conn: Connection) -> None:
    if (
        not _table_exists(conn, "pension_profiles")
        or "profile_id" not in _existing_columns(conn, "pension_profiles")
    ):
        return
    duplicate = conn.execute(
        text(
            "SELECT profile_id FROM pension_profiles "
            "WHERE profile_id IS NOT NULL "
            "GROUP BY profile_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Plusieurs profils de retraite existent pour le meme profil utilisateur"
        )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pension_profile_owner "
            "ON pension_profiles (profile_id)"
        )
    )


def _rebuild_accounts_without_name_uniqueness(conn: Connection) -> None:
    """Replace the legacy unique-name accounts table without copying data out."""
    account_table = Base.metadata.tables["accounts"]
    existing_columns = _existing_columns(conn, "accounts")
    copied_columns = [column.name for column in account_table.columns if column.name in existing_columns]
    columns = ", ".join(_quote_identifier(column) for column in copied_columns)
    select_columns = ", ".join(
        (
            f"COALESCE({_quote_identifier(column)}, CURRENT_TIMESTAMP) "
            f"AS {_quote_identifier(column)}"
        )
        if column == "created_at"
        else _quote_identifier(column)
        for column in copied_columns
    )

    for index in conn.execute(text("PRAGMA index_list(accounts)")).all():
        index_name = str(index[1])
        if not index_name.startswith("sqlite_autoindex_"):
            conn.execute(text(f"DROP INDEX {_quote_identifier(index_name)}"))

    conn.execute(text("PRAGMA legacy_alter_table=ON"))
    try:
        conn.execute(text("ALTER TABLE accounts RENAME TO accounts_legacy"))
        account_table.create(conn)
        conn.execute(
            text(
                f"INSERT INTO accounts ({columns}) SELECT {select_columns} FROM accounts_legacy"
            )
        )
    finally:
        conn.execute(text("PRAGMA legacy_alter_table=OFF"))


def _drop_legacy_accounts(conn: Connection) -> None:
    if _table_exists(conn, "accounts_legacy"):
        conn.execute(text("DROP TABLE accounts_legacy"))


def _rename_owner_profile_columns(conn: Connection) -> None:
    """Adopt the stable member_id association vocabulary without data loss."""
    for table in ("account_owners", "real_estate_owners", "debt_owners"):
        if _table_exists(conn, table):
            columns = _existing_columns(conn, table)
            if "profile_id" in columns and "member_id" not in columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {_quote_identifier(table)} "
                        "RENAME COLUMN profile_id TO member_id"
                    )
                )


def _backfill_multi_user_data(
    conn: Connection,
    bootstrap_profile: bool,
    assign_all_to_first_admin: bool,
) -> int | None:
    """Create the first admin and attach legacy resources without dropping rows."""
    if not _table_exists(conn, "households") or not _table_exists(conn, "household_members"):
        return None

    household_id = conn.execute(text("SELECT id FROM households ORDER BY id LIMIT 1")).scalar()
    if household_id is None:
        if not bootstrap_profile:
            return None
        result = conn.execute(
            text("INSERT INTO households (name, created_at) VALUES ('Foyer', :created_at)"),
            {"created_at": datetime.now(UTC)},
        )
        household_id = result.lastrowid

    household_ids = list(
        conn.execute(text("SELECT id FROM households ORDER BY id")).scalars()
    )
    if _table_exists(conn, "shared_account_links"):
        # The old household link granted access, not financial ownership. Carrying
        # it forward would silently turn every household member into an owner.
        conn.execute(text("DELETE FROM shared_account_links"))
    if len(household_ids) > 1:
        if _table_exists(conn, "goals"):
            conn.execute(
                text(
                    "UPDATE goals SET household_id = :household_id "
                    "WHERE household_id != :household_id"
                ),
                {"household_id": household_id},
            )
        conn.execute(
            text(
                "UPDATE household_members SET household_id = :household_id "
                "WHERE household_id != :household_id"
            ),
            {"household_id": household_id},
        )
        conn.execute(
            text("DELETE FROM households WHERE id != :household_id"),
            {"household_id": household_id},
        )

    # Legacy owner is the new administrator; legacy unsupported roles become members.
    conn.execute(
        text(
            "UPDATE household_members SET role = CASE "
            "WHEN role IN ('owner', 'admin') THEN 'admin' ELSE 'member' END"
        )
    )
    profile_id = conn.execute(
        text(
            "SELECT id FROM household_members "
            "WHERE household_id = :household_id "
            "ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, active DESC, id LIMIT 1"
        ),
        {"household_id": household_id},
    ).scalar()
    if profile_id is None:
        if not bootstrap_profile:
            return None
        result = conn.execute(
            text(
                "INSERT INTO household_members "
                "(household_id, name, role, color, active, created_at) "
                "VALUES (:household_id, 'Profil principal', 'admin', '#4f46e5', 1, :created_at)"
            ),
            {"household_id": household_id, "created_at": datetime.now(UTC)},
        )
        profile_id = result.lastrowid

    conn.execute(
        text(
            "UPDATE household_members SET role = 'admin', active = 1 "
            "WHERE id = :profile_id"
        ),
        {"profile_id": profile_id},
    )

    for table, resource_column, owner_table in (
        ("accounts", "account_id", "account_owners"),
        ("real_estate_assets", "asset_id", "real_estate_owners"),
        ("debts", "debt_id", "debt_owners"),
    ):
        if _table_exists(conn, table):
            if assign_all_to_first_admin:
                conn.execute(text(f"DELETE FROM {_quote_identifier(owner_table)}"))
                missing_owner_filter = ""
            else:
                missing_owner_filter = (
                    f"WHERE NOT EXISTS ("
                    f"SELECT 1 FROM {_quote_identifier(owner_table)} AS owner "
                    f"WHERE owner.{_quote_identifier(resource_column)} = resource.id"
                    ")"
                )
            conn.execute(
                text(
                    f"INSERT INTO {_quote_identifier(owner_table)} "
                    f"({_quote_identifier(resource_column)}, member_id, weight) "
                    f"SELECT resource.id, :profile_id, 1.0 "
                    f"FROM {_quote_identifier(table)} AS resource "
                    f"{missing_owner_filter}"
                ),
                {"profile_id": profile_id},
            )

    for table in ("work_contracts", "pay_slips", "pension_profiles"):
        if _table_exists(conn, table) and "profile_id" in _existing_columns(conn, table):
            profile_filter = "" if assign_all_to_first_admin else " WHERE profile_id IS NULL"
            conn.execute(
                text(
                    f"UPDATE {_quote_identifier(table)} SET profile_id = :profile_id"
                    f"{profile_filter}"
                ),
                {"profile_id": profile_id},
            )
    return int(profile_id)


def _validate_multi_user_backfill(
    conn: Connection,
    profile_id: int | None,
    assign_all_to_first_admin: bool,
) -> None:
    if profile_id is None:
        return
    for table, resource_column, owner_table in (
        ("accounts", "account_id", "account_owners"),
        ("real_estate_assets", "asset_id", "real_estate_owners"),
        ("debts", "debt_id", "debt_owners"),
    ):
        orphan = conn.execute(
            text(
                f"SELECT resource.id FROM {_quote_identifier(table)} AS resource "
                f"LEFT JOIN {_quote_identifier(owner_table)} AS owner "
                f"ON owner.{_quote_identifier(resource_column)} = resource.id "
                f"GROUP BY resource.id HAVING COUNT(owner.id) = 0 LIMIT 1"
            )
        ).first()
        if orphan is not None:
            raise RuntimeError(f"La migration a laisse une ressource sans proprietaire: {table}")
        if assign_all_to_first_admin:
            incorrect_owner = conn.execute(
                text(
                    f"SELECT resource.id FROM {_quote_identifier(table)} AS resource "
                    f"JOIN {_quote_identifier(owner_table)} AS owner "
                    f"ON owner.{_quote_identifier(resource_column)} = resource.id "
                    "GROUP BY resource.id "
                    "HAVING COUNT(owner.id) != 1 "
                    "OR MIN(owner.member_id) != :profile_id LIMIT 1"
                ),
                {"profile_id": profile_id},
            ).first()
            if incorrect_owner is not None:
                raise RuntimeError(
                    f"La migration classique n'a pas attribue exclusivement {table} "
                    "au premier administrateur"
                )
    for table in ("work_contracts", "pay_slips", "pension_profiles"):
        profile_filter = (
            "profile_id IS NULL OR profile_id != :profile_id"
            if assign_all_to_first_admin
            else "profile_id IS NULL"
        )
        unassigned = conn.execute(
            text(
                f"SELECT id FROM {_quote_identifier(table)} "
                f"WHERE {profile_filter} LIMIT 1"
            ),
            {"profile_id": profile_id},
        ).first()
        if unassigned is not None:
            raise RuntimeError(f"La migration a laisse une ressource personnelle orpheline: {table}")


def _remove_legacy_profile_triggers(conn: Connection) -> None:
    """Remove transitional triggers superseded by profile-aware routers."""
    for trigger in (
        "assign_default_account_owner",
        "assign_default_real_estate_owner",
        "assign_default_debt_owner",
        "assign_default_work_contract_profile",
        "assign_default_pay_slip_profile",
        "assign_default_pension_profile",
    ):
        conn.execute(
            text(f"DROP TRIGGER IF EXISTS {_quote_identifier(trigger)}")
        )


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


def _backfill_holding_operations(conn: Connection) -> None:
    if not _table_exists(conn, "holdings"):
        return
    conn.execute(
        text(
            "INSERT INTO holding_operations "
            "(holding_id, operation_type, quantity, unit_price, occurred_on, created_at) "
            "SELECT id, 'buy', quantity, average_price, DATE(created_at), created_at "
            "FROM holdings "
            "WHERE quantity > 0 "
            "AND NOT EXISTS ("
            "SELECT 1 FROM holding_operations "
            "WHERE holding_operations.holding_id = holdings.id"
            ")"
        )
    )


def _backfill_holding_operation_dates(conn: Connection) -> None:
    conn.execute(
        text(
            "UPDATE holding_operations "
            "SET occurred_on = DATE(created_at) "
            "WHERE occurred_on IS NULL"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_holding_operations_occurred_on "
            "ON holding_operations (occurred_on)"
        )
    )


async def run_migrations(engine: AsyncEngine, db_path: Path | None) -> None:
    """Reconcile the persistent schema, backing up existing data first."""
    pre_existing = db_path is not None and db_path.exists() and db_path.stat().st_size > 0

    async with engine.connect() as conn:
        version = await conn.scalar(text("PRAGMA user_version"))
        current_version = int(version or 0)
        pending = await conn.run_sync(_pending_columns)
        missing_tables = await conn.run_sync(_missing_tables)
        obsolete_tables = await conn.run_sync(_existing_obsolete_tables)
        obsolete_columns = await conn.run_sync(_existing_obsolete_columns)
        requires_holding_operation_backfill = "holding_operations" in missing_tables
        requires_holding_operation_date_backfill = (
            "occurred_on" in pending.get("holding_operations", {})
        )
        requires_real_estate_rebuild = await conn.run_sync(_real_estate_requires_rebuild)
        requires_account_rebuild = await conn.run_sync(_account_name_is_unique)
        requires_balance_backfill = await conn.run_sync(
            _requires_balance_snapshot_backfill,
            current_version,
        )
        requires_pension_profile_index = await conn.run_sync(
            _pension_profile_unique_index_missing
        )
        retired_attachment_paths = await conn.run_sync(_retired_attachment_paths)
        requires_schema_version_upgrade = pre_existing and current_version < SCHEMA_VERSION
        classic_profile_upgrade = (
            pre_existing and current_version < MULTI_USER_SCHEMA_VERSION
        )

    migration_required = (
        pending
        or missing_tables
        or obsolete_tables
        or obsolete_columns
        or requires_real_estate_rebuild
        or requires_account_rebuild
        or requires_balance_backfill
        or requires_pension_profile_index
        or requires_schema_version_upgrade
    )
    if migration_required and pre_existing and db_path is not None:
        _backup(db_path, current_version)

    async with engine.connect() as conn:
        try:
            if requires_account_rebuild:
                # SQLite otherwise rewrites every child FK to ``accounts_legacy``
                # when the parent table is renamed.
                await conn.execute(text("PRAGMA foreign_keys=OFF"))
                await conn.commit()
            async with conn.begin():
                await conn.run_sync(_apply_columns, pending)
                if requires_account_rebuild:
                    await conn.run_sync(_rebuild_accounts_without_name_uniqueness)
                await conn.run_sync(Base.metadata.create_all)
                if requires_holding_operation_backfill:
                    await conn.run_sync(_backfill_holding_operations)
                if requires_holding_operation_date_backfill:
                    await conn.run_sync(_backfill_holding_operation_dates)
                if requires_real_estate_rebuild:
                    await conn.run_sync(_rebuild_real_estate_assets)
                if requires_balance_backfill:
                    await conn.run_sync(_backfill_current_balance_snapshots)
                await conn.run_sync(_drop_obsolete_columns, obsolete_columns)
                for table in sorted(obsolete_tables):
                    await conn.execute(text(f"DROP TABLE {table}"))
                if requires_account_rebuild:
                    await conn.run_sync(_drop_legacy_accounts)
                await conn.run_sync(_rename_owner_profile_columns)
                first_admin_id = await conn.run_sync(
                    _backfill_multi_user_data,
                    classic_profile_upgrade,
                    classic_profile_upgrade,
                )
                await conn.run_sync(_ensure_pension_profile_unique_index)
                await conn.run_sync(
                    _validate_multi_user_backfill,
                    first_admin_id,
                    classic_profile_upgrade,
                )
                await conn.run_sync(_remove_legacy_profile_triggers)
                violations = (
                    await conn.execute(text("PRAGMA foreign_key_check"))
                ).all()
                if violations:
                    raise RuntimeError("La migration a rompu des cles etrangeres")
                await conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
                await conn.execute(text("PRAGMA optimize"))
        finally:
            if requires_account_rebuild:
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                await conn.commit()

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

    if migration_required:
        logger.info("Schema mis a jour vers la version %s", SCHEMA_VERSION)
