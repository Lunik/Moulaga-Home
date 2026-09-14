"""Schema migration contracts for retiring the operation ledger."""

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
    transfer_group VARCHAR(64),
    created_at DATETIME,
    CONSTRAINT uq_transactions_source_hash UNIQUE (source_hash)
);
CREATE TABLE transaction_attachments (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    original_name VARCHAR(255) NOT NULL,
    stored_path VARCHAR(512) NOT NULL UNIQUE,
    content_type VARCHAR(160),
    size INTEGER NOT NULL,
    created_at DATETIME
);
CREATE TABLE categorization_rules (
    id INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    match_type VARCHAR(16) NOT NULL,
    pattern VARCHAR(200) NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id)
);
CREATE TABLE merchant_identities (
    id INTEGER PRIMARY KEY,
    label VARCHAR(120) NOT NULL,
    pattern VARCHAR(200) NOT NULL
);
"""


def _seed_legacy_db(db_path, attachment_path: str | None = None) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO accounts (id, name, type, currency, initial_balance) "
            "VALUES (1, 'Compte historique', 'checking', 'EUR', '100.00')"
        )
        connection.execute(
            "INSERT INTO categories (id, name, kind, color) "
            "VALUES (1, 'Courses', 'expense', '#f97316')"
        )
        connection.execute(
            "INSERT INTO transactions "
            "(id, booked_at, description, amount, account_id, category_id) "
            "VALUES (1, '2026-01-05', 'Depense historique', '-30.00', 1, 1)"
        )
        if attachment_path is not None:
            connection.execute(
                "INSERT INTO transaction_attachments "
                "(id, transaction_id, original_name, stored_path, size) "
                "VALUES (1, 1, 'recu.txt', ?, 4)",
                (attachment_path,),
            )
        connection.execute(
            "INSERT INTO categorization_rules "
            "(id, name, match_type, pattern, category_id) "
            "VALUES (1, 'Historique', 'keyword', 'TEST', 1)"
        )
        connection.execute(
            "INSERT INTO merchant_identities (id, label, pattern) "
            "VALUES (1, 'Marchand', 'TEST')"
        )
        connection.execute("PRAGMA user_version = 15")


def test_legacy_ledger_balance_is_materialized_before_retirement(tmp_path, monkeypatch):
    db_path = tmp_path / "moulaga.db"
    attachment_relative = "attached/aa/bb/hash/recu.txt"
    attachment = tmp_path / attachment_relative
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"test")
    _seed_legacy_db(db_path, attachment_relative)

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        account = next(
            item for item in client.get("/api/accounts").json()
            if item["name"] == "Compte historique"
        )
        assert account["balance"] == "70.00"
        statements = client.get(f"/api/accounts/{account['id']}/snapshots").json()
        assert statements[-1]["period"] == date.today().strftime("%Y-%m")
        assert statements[-1]["balance"] == "70.00"

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {
        "transactions",
        "transaction_attachments",
        "categorization_rules",
        "merchant_identities",
    }.isdisjoint(tables)
    assert version >= 16
    assert not attachment.exists()
    assert list(tmp_path.glob("moulaga.backup-*.db"))


def test_fresh_database_omits_retired_tables_and_is_idempotent(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        paths = client.get("/api/openapi.json").json()["paths"]
        assert client.get("/api/accounts").json()
        assert client.get("/api/categories").json()
        assert client.get("/api/preferences").json()["budget_cycle_start_day"] == 1
        assert not any("transaction" in path for path in paths)

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "transactions" not in tables
    assert "categorization_rules" not in tables
    assert version >= 16

    with TestClient(main.create_app()):
        pass
    assert list(tmp_path.glob("moulaga.backup-*.db")) == []


def test_v20_database_adds_contract_attachment_support(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        contract = client.post(
            "/api/work/contracts",
            json={
                "employer": "Employeur historique",
                "position": "Poste historique",
                "start_date": "2025-01-01",
            },
        ).json()

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE work_contract_attachments")
        connection.execute("ALTER TABLE work_contracts DROP COLUMN document_ignored")
        connection.execute("PRAGMA user_version = 20")

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        migrated_contract = client.get(
            f"/api/work/contracts/{contract['id']}"
        ).json()
        assert migrated_contract["employer"] == "Employeur historique"
        assert migrated_contract["attachment_count"] == 0
        assert client.get(
            f"/api/work/contracts/{contract['id']}/attachments"
        ).json() == []

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(work_contracts)")
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "work_contract_attachments" in tables
    assert "document_ignored" in columns
    assert version >= 21
    assert len(list(tmp_path.glob("moulaga.backup-*.db"))) == 1


def test_v21_database_backfills_existing_holding_as_initial_purchase(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        account = client.post(
            "/api/accounts",
            json={"name": "PEA historique", "type": "pea", "initial_balance": "0.00"},
        ).json()
        holding = client.post(
            "/api/holdings",
            json={
                "account_id": account["id"],
                "name": "ETF historique",
                "symbol": "OLD",
                "asset_class": "equity",
                "quantity": "7.5",
                "average_price": "42.25",
                "current_price": "50.00",
            },
        ).json()

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE holding_operations")
        connection.execute("PRAGMA user_version = 21")

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        migrated = next(
            item for item in client.get("/api/holdings").json()
            if item["id"] == holding["id"]
        )
        operations = client.get(f"/api/holdings/{holding['id']}/operations").json()

    assert migrated["quantity"] == "7.500000"
    assert migrated["average_price"] == "42.250000"
    assert migrated["operation_count"] == 1
    assert len(operations) == 1
    assert operations[0]["operation_type"] == "buy"
    assert operations[0]["quantity"] == "7.500000"
    assert operations[0]["unit_price"] == "42.25"
    assert len(list(tmp_path.glob("moulaga.backup-*.db"))) == 1


def test_v16_database_drops_obsolete_recurring_columns(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        account_id = client.get("/api/accounts").json()[0]["id"]

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "ALTER TABLE recurring_series "
            "ADD COLUMN confidence NUMERIC(3, 2) NOT NULL"
        )
        connection.execute(
            "ALTER TABLE recurring_series ADD COLUMN match_key VARCHAR(64)"
        )
        connection.execute(
            "CREATE INDEX ix_recurring_series_match_key "
            "ON recurring_series (match_key)"
        )
        connection.execute(
            "INSERT INTO recurring_series "
            "(label, account_id, category_id, frequency, next_due, amount, "
            "amount_type, status, recurring_type, custom_type, "
            "credit_insurance_rate, created_at, confidence, match_key) "
            "VALUES (?, ?, NULL, 'monthly', '2026-09-01', '1200.00', "
            "'fixed', 'active', 'salary', NULL, NULL, "
            "'2026-09-01 08:00:00', '0.95', 'legacy-salary')",
            ("Salaire historique", account_id),
        )
        connection.execute("PRAGMA user_version = 16")

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as client:
        created = client.post(
            "/api/recurring",
            json={
                "label": "Nouveau salaire",
                "account_id": account_id,
                "frequency": "monthly",
                "next_due": "2026-09-11",
                "amount": "100000.00",
                "recurring_type": "salary",
            },
        )
        assert created.status_code == 201
        assert {item["label"] for item in client.get("/api/recurring").json()} == {
            "Salaire historique",
            "Nouveau salaire",
        }

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(recurring_series)")
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"confidence", "match_key"}.isdisjoint(columns)
    assert version >= 17
    backups = list(tmp_path.glob("moulaga.backup-*.db"))
    assert len(backups) == 1

    with TestClient(main.create_app()):
        pass
    assert list(tmp_path.glob("moulaga.backup-*.db")) == backups
