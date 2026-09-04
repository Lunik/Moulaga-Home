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
        attachment_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'transaction_attachments'"
        ).fetchone()
        snapshot_attachment_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'balance_snapshot_attachments'"
        ).fetchone()
        real_estate_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'real_estate_assets'"
        ).fetchone()
    finally:
        connection.close()
    assert "account_number" in account_columns
    assert "transfer_group" in transaction_columns
    assert attachment_table is not None
    assert snapshot_attachment_table is not None
    assert real_estate_table is not None

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
    assert version >= 9

    # Re-opening a current database performs no backup (nothing pending).
    with TestClient(main.create_app()):
        pass
    assert list(tmp_path.glob("moulaga.backup-*.db")) == []


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
    assert version >= 9
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
