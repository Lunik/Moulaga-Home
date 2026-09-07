"""Schema migration and persistence tests (upgrade from the legacy schema)."""

from __future__ import annotations

import sqlite3
from datetime import date

from conftest import load_app
from fastapi.testclient import TestClient

LEGACY_SCHEMA = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    type VARCHAR(32) DEFAULT 'checking',
    currency VARCHAR(3) DEFAULT 'EUR',
    initial_balance NUMERIC(12, 2) DEFAULT '0.00',
    created_at DATETIME
);
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    color VARCHAR(16) DEFAULT '#4f46e5',
    monthly_budget NUMERIC(12, 2),
    CONSTRAINT uq_categories_name_kind UNIQUE (name, kind)
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    booked_at DATE NOT NULL,
    description TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    notes TEXT,
    source_hash VARCHAR(64),
    created_at DATETIME,
    CONSTRAINT uq_transactions_source_hash UNIQUE (source_hash)
);
"""


def _seed_legacy_db(db_path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO accounts (id, name, type, currency, initial_balance) "
            "VALUES (1, 'Compte historique', 'checking', 'EUR', '100.00')"
        )
        connection.execute(
            "INSERT INTO categories (id, name, kind, color) VALUES (1, 'Courses', 'expense', '#f97316')"
        )
        connection.execute(
            "INSERT INTO transactions (booked_at, description, amount, account_id, category_id) "
            "VALUES ('2026-01-05', 'Depense historique', '-30.00', 1, 1)"
        )
        connection.execute("PRAGMA user_version = 0")
        connection.commit()
    finally:
        connection.close()


def test_legacy_database_upgrades_without_data_loss(tmp_path, monkeypatch):
    db_path = tmp_path / "moulaga.db"
    _seed_legacy_db(db_path)

    main, _ = load_app(tmp_path, monkeypatch)

    with TestClient(main.create_app()) as client:
        accounts = client.get("/api/accounts").json()
        historic = next(a for a in accounts if a["name"] == "Compte historique")
        assert historic["archived"] is False
        assert historic["color"] == "#4f46e5"
        assert historic["balance"] == "70.00"  # 100.00 initial - 30.00 expense preserved
        assert historic["account_number"] is None
        assert historic["regional_entity"] is None
        assert historic["savings_product"] is None
        assert historic["annual_interest_rate"] is None
        assert historic["legal_cap"] is None

        transactions = client.get("/api/transactions").json()
        assert any(t["description"] == "Depense historique" for t in transactions)

    connection = sqlite3.connect(db_path)
    try:
        account_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(accounts)")
        }
        transaction_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(transactions)")
        }
        attachment_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ("
                "'transaction_attachments', 'balance_snapshot_attachments', "
                "'recurring_series_attachments', 'debt_attachments', "
                "'real_estate_attachments')"
            )
        }
        real_estate_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'real_estate_assets'"
        ).fetchone()
        real_estate_debt_link_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'real_estate_debt_links'"
        ).fetchone()
    finally:
        connection.close()
    assert "account_number" in account_columns
    assert "regional_entity" in account_columns
    assert "transfer_group" in transaction_columns
    assert attachment_tables == {
        "transaction_attachments",
        "balance_snapshot_attachments",
        "recurring_series_attachments",
        "debt_attachments",
        "real_estate_attachments",
    }
    assert real_estate_table is not None
    assert real_estate_debt_link_table is not None

    # A safety backup must have been produced before altering the existing DB.
    backups = list(tmp_path.glob("moulaga.backup-*.db"))
    assert backups, "expected a pre-migration backup copy"

    # New columns are usable: patching the migrated category succeeds.
    with TestClient(main.create_app()) as client:
        category = next(c for c in client.get("/api/categories").json() if c["name"] == "Courses")
        response = client.patch(f"/api/categories/{category['id']}", json={"archived": True})
        assert response.status_code == 200
        assert response.json()["archived"] is True
        account = client.get("/api/accounts").json()[0]
        savings = client.patch(
            f"/api/accounts/{account['id']}",
            json={
                "savings_product": "Livret A",
                "annual_interest_rate": "1.700",
                "legal_cap": "22950.00",
            },
        )
        assert savings.status_code == 200
        assert savings.json()["legal_cap"] == "22950.00"


def test_schema_version_is_stamped_and_idempotent(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()):
        pass

    connection = sqlite3.connect(tmp_path / "moulaga.db")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    assert version >= 12

    # Re-opening a current database performs no backup (nothing pending).
    with TestClient(main.create_app()):
        pass
    assert list(tmp_path.glob("moulaga.backup-*.db")) == []


def test_real_estate_schema_migrates_debt_link_without_data_loss(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "moulaga.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE debts (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                principal NUMERIC(12, 2) NOT NULL DEFAULT 0,
                balance NUMERIC(12, 2) NOT NULL DEFAULT 0,
                interest_rate NUMERIC(5, 2),
                minimum_payment NUMERIC(12, 2),
                account_id INTEGER,
                due_date DATE,
                color VARCHAR(16) NOT NULL DEFAULT '#ef4444',
                archived BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME
            );
            INSERT INTO debts (
                id, name, principal, balance, color, archived
            ) VALUES (
                1, 'Pret historique', 100000, 80000, '#ef4444', 0
            );
            CREATE TABLE real_estate_assets (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                property_type VARCHAR(32) NOT NULL DEFAULT 'primary_residence',
                address VARCHAR(200),
                acquired_on DATE,
                purchase_price NUMERIC(12, 2) NOT NULL DEFAULT 0,
                current_value NUMERIC(12, 2) NOT NULL DEFAULT 0,
                ownership_share NUMERIC(5, 2) NOT NULL DEFAULT 100,
                debt_id INTEGER,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(debt_id) REFERENCES debts(id) ON DELETE SET NULL
            );
            CREATE UNIQUE INDEX ix_real_estate_assets_debt_id
                ON real_estate_assets (debt_id);
            INSERT INTO real_estate_assets (
                id, name, property_type, purchase_price, current_value,
                ownership_share, debt_id, created_at
            ) VALUES (
                1, 'Bien historique', 'primary_residence', 250000, 275000,
                100, 1, '2026-01-01 00:00:00'
            );
            CREATE TABLE real_estate_attachments (
                id INTEGER NOT NULL PRIMARY KEY,
                asset_id INTEGER NOT NULL REFERENCES real_estate_assets(id)
                    ON DELETE CASCADE,
                original_name VARCHAR(255) NOT NULL,
                stored_path VARCHAR(512) NOT NULL UNIQUE,
                content_type VARCHAR(160),
                size INTEGER NOT NULL,
                created_at DATETIME
            );
            INSERT INTO real_estate_attachments (
                id, asset_id, original_name, stored_path, content_type, size,
                created_at
            ) VALUES (
                1, 1, 'acte-historique.txt',
                'attached/aa/bb/hash/acte-historique.txt',
                'text/plain', 12, '2026-01-01 00:00:00'
            );
            PRAGMA user_version = 10;
            """
        )
        connection.commit()
    finally:
        connection.close()

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        asset = client.get("/api/real-estate").json()[0]
        assert asset["name"] == "Bien historique"
        assert asset["current_value"] == "275000.00"
        assert asset["debt_ids"] == [1]
        assert asset["debts"][0]["name"] == "Pret historique"
        assert asset["debt_balance"] == "80000.00"
        assert client.get("/api/real-estate/1/attachments").json()[0][
            "original_name"
        ] == "acte-historique.txt"

        cleared = client.patch(
            "/api/real-estate/1",
            json={"current_value": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["current_value"] is None
        assert cleared.json()["owned_value"] == "250000.00"

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(real_estate_assets)")
        }
        debt_links = connection.execute(
            "SELECT asset_id, debt_id FROM real_estate_debt_links"
        ).fetchall()
        attachments = connection.execute(
            "SELECT asset_id, original_name FROM real_estate_attachments"
        ).fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    assert columns["current_value"][3] == 0
    assert "debt_id" not in columns
    assert debt_links == [(1, 1)]
    assert attachments == [(1, "acte-historique.txt")]
    assert version >= 14
    assert list(tmp_path.glob("moulaga.backup-*.db"))


def test_missing_table_is_recreated_after_safety_backup(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()):
        pass

    db_path = tmp_path / "moulaga.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("DROP TABLE real_estate_assets")
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
    finally:
        connection.close()

    with TestClient(main.create_app()):
        pass

    connection = sqlite3.connect(db_path)
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'real_estate_assets'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert table is not None
    assert version >= 12
    assert list(tmp_path.glob("moulaga.backup-*.db"))


def test_legacy_rule_is_exposed_as_a_single_pattern_after_upgrade(tmp_path, monkeypatch):
    db_path = tmp_path / "moulaga.db"
    _seed_legacy_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE categorization_rules (
                id INTEGER PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                match_type VARCHAR(16) NOT NULL,
                pattern VARCHAR(200) NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id),
                priority INTEGER NOT NULL DEFAULT 100,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME
            );
            INSERT INTO categorization_rules (
                id, name, match_type, pattern, category_id, priority, enabled
            ) VALUES (1, 'Regle historique', 'keyword', 'HISTORIQUE', 1, 100, 1);
            PRAGMA user_version = 8;
            """
        )
        connection.commit()
    finally:
        connection.close()

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        rule = client.get("/api/rules").json()[0]
        assert rule["pattern"] == "HISTORIQUE"
        assert rule["patterns"] == ["HISTORIQUE"]

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(categorization_rules)")
        }
    finally:
        connection.close()
    assert "patterns_json" in columns
    assert list(tmp_path.glob("moulaga.backup-*.db"))


def test_recurring_and_debt_schema_upgrade_removes_schedules(tmp_path, monkeypatch):
    db_path = tmp_path / "moulaga.db"
    _seed_legacy_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE recurring_series (
                id INTEGER PRIMARY KEY,
                label VARCHAR(200) NOT NULL,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                category_id INTEGER REFERENCES categories(id),
                frequency VARCHAR(16) NOT NULL DEFAULT 'monthly',
                next_due DATE NOT NULL,
                amount NUMERIC(12, 2),
                amount_type VARCHAR(16) NOT NULL DEFAULT 'fixed',
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                confidence NUMERIC(3, 2) NOT NULL DEFAULT '1.00',
                match_key VARCHAR(64),
                created_at DATETIME
            );
            CREATE TABLE debts (
                id INTEGER PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                principal NUMERIC(12, 2) NOT NULL DEFAULT '0.00',
                balance NUMERIC(12, 2) NOT NULL DEFAULT '0.00',
                interest_rate NUMERIC(5, 2),
                minimum_payment NUMERIC(12, 2),
                account_id INTEGER REFERENCES accounts(id),
                due_date DATE,
                color VARCHAR(16) NOT NULL DEFAULT '#ef4444',
                archived BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME
            );
            CREATE TABLE recurring_schedule_entries (
                id INTEGER PRIMARY KEY,
                series_id INTEGER NOT NULL REFERENCES recurring_series(id),
                due_date DATE NOT NULL,
                amount NUMERIC(12, 2) NOT NULL
            );
            CREATE TABLE debt_schedule_entries (
                id INTEGER PRIMARY KEY,
                debt_id INTEGER NOT NULL REFERENCES debts(id),
                due_date DATE NOT NULL,
                remaining_balance NUMERIC(12, 2) NOT NULL
            );
            INSERT INTO recurring_series (
                id, label, account_id, frequency, next_due, amount,
                amount_type, status, confidence
            ) VALUES (
                1, 'Serie historique', 1, 'monthly', '2026-10-01',
                '-25.00', 'fixed', 'active', '1.00'
            );
            INSERT INTO debts (
                id, name, principal, balance, minimum_payment, account_id,
                due_date, color, archived
            ) VALUES (
                1, 'Dette historique', '1000.00', '750.00', '50.00', 1,
                '2028-01-01', '#ef4444', 0
            );
            INSERT INTO recurring_schedule_entries (
                id, series_id, due_date, amount
            ) VALUES (1, 1, '2026-10-01', '-25.00');
            INSERT INTO debt_schedule_entries (
                id, debt_id, due_date, remaining_balance
            ) VALUES (1, 1, '2026-10-01', '700.00');
            PRAGMA user_version = 9;
            """
        )
        connection.commit()
    finally:
        connection.close()

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        recurring = client.get("/api/recurring").json()
        assert recurring[0]["label"] == "Serie historique"
        assert recurring[0]["recurring_type"] == "uncategorized"
        assert recurring[0]["attachment_count"] == 0
        debts = client.get("/api/debts").json()
        assert debts[0]["name"] == "Dette historique"
        assert debts[0]["debt_type"] == "other"
        assert debts[0]["recurring_series_id"] is None
        assert debts[0]["attachment_count"] == 0

    connection = sqlite3.connect(db_path)
    try:
        recurring_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(recurring_series)")
        }
        debt_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(debts)")
        }
        schedule_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('recurring_schedule_entries', 'debt_schedule_entries')"
            )
        }
        attachment_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ("
                "'recurring_series_attachments', 'debt_attachments', "
                "'real_estate_attachments')"
            )
        }
    finally:
        connection.close()

    assert {
        "recurring_type",
        "custom_type",
        "credit_insurance_rate",
    } <= recurring_columns
    assert {"debt_type", "recurring_series_id"} <= debt_columns
    assert schedule_tables == set()
    assert attachment_tables == {
        "recurring_series_attachments",
        "debt_attachments",
        "real_estate_attachments",
    }
    assert list(tmp_path.glob("moulaga.backup-*.db"))


def test_fresh_database_seeds_defaults_and_preferences(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        assert client.get("/api/accounts").json()
        assert client.get("/api/categories").json()
        prefs = client.get("/api/preferences").json()
        assert prefs["budget_cycle_start_day"] == 1
        assert prefs["private_categorization_enabled"] is False


def test_transaction_ledger_patch_and_delete(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        account = client.get("/api/accounts").json()[0]
        destination = client.post(
            "/api/accounts",
            json={"name": "Compte de destination", "type": "checking", "initial_balance": "0.00"},
        ).json()
        created = client.post(
            "/api/transactions",
            json={
                "booked_at": date.today().isoformat(),
                "description": "Operation initiale",
                "amount": "-10.00",
                "account_id": account["id"],
            },
        ).json()

        patched = client.patch(
            f"/api/transactions/{created['id']}",
            json={
                "amount": "-12.50",
                "description": "Operation corrigee",
                "account_id": destination["id"],
            },
        )
        assert patched.status_code == 200
        assert patched.json()["amount"] == "-12.50"
        assert patched.json()["account_id"] == destination["id"]
        assert patched.json()["account_name"] == "Compte de destination"
        balances = {item["id"]: item["balance"] for item in client.get("/api/accounts").json()}
        assert balances[account["id"]] == "0.00"
        assert balances[destination["id"]] == "-12.50"

        # Foreign-key safety: unknown account is rejected.
        bad = client.patch(f"/api/transactions/{created['id']}", json={"account_id": 9999})
        assert bad.status_code == 404

        deleted = client.delete(f"/api/transactions/{created['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/transactions/{created['id']}").status_code == 404
