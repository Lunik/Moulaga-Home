"""Schema migration contracts for retiring the operation ledger."""

from __future__ import annotations

import io
import sqlite3
from datetime import date

import pytest
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


def _select_or_create_profile(client: TestClient) -> None:
    profiles = client.get("/api/profiles").json()
    profile = profiles[0] if profiles else client.post(
        "/api/profiles", json={"name": "Profil test"}
    ).json()
    response = client.post(f"/api/profiles/{profile['id']}/select", json={})
    assert response.status_code == 200


def test_legacy_ledger_balance_is_materialized_before_retirement(tmp_path, monkeypatch):
    db_path = tmp_path / "moulaga.db"
    attachment_relative = "attached/aa/bb/hash/recu.txt"
    attachment = tmp_path / attachment_relative
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"test")
    _seed_legacy_db(db_path, attachment_relative)

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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


def test_account_rebuild_preserves_children_and_consolidates_legacy_households(
    tmp_path, monkeypatch
):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
        account = client.post(
            "/api/accounts",
            json={"name": "Compte partage historique", "initial_balance": "10.00"},
        ).json()
        snapshot = client.put(
            f"/api/accounts/{account['id']}/snapshots",
            json={"period": "2026-01", "balance": "12.00"},
        ).json()

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE UNIQUE INDEX legacy_unique_account_name ON accounts(name)"
        )
        other_household_id = connection.execute(
            "INSERT INTO households (name, created_at) VALUES ('Ancien foyer', CURRENT_TIMESTAMP)"
        ).lastrowid
        bob_id = connection.execute(
            "INSERT INTO household_members "
            "(household_id, name, role, color, active, created_at) "
            "VALUES (?, 'Bob historique', 'member', '#16a34a', 1, CURRENT_TIMESTAMP)",
            (other_household_id,),
        ).lastrowid
        connection.execute(
            "DELETE FROM account_owners WHERE account_id = ?", (account["id"],)
        )
        connection.execute(
            "INSERT INTO shared_account_links "
            "(household_id, account_id, permission, created_at) "
            "VALUES (?, ?, 'edit', CURRENT_TIMESTAMP)",
            (other_household_id, account["id"]),
        )
        connection.execute("PRAGMA user_version = 26")

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        profiles = client.get("/api/profiles").json()
        bob = next(
            profile
            for profile in profiles
            if profile["id"] == bob_id
        )
        first_admin = next(profile for profile in profiles if profile["role"] == "admin")
        assert client.post(
            f"/api/profiles/{first_admin['id']}/select", json={}
        ).status_code == 200
        assert account["id"] in {
            item["id"] for item in client.get("/api/accounts").json()
        }
        assert client.get(
            f"/api/accounts/{account['id']}/snapshots"
        ).json()[0]["id"] == snapshot["id"]
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        assert client.get("/api/accounts").json() == []

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM households").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM shared_account_links").fetchone()[0] == 0


def test_multi_user_restart_does_not_convert_stale_shared_link_to_ownership(
    tmp_path, monkeypatch
):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
        household = client.get("/api/households").json()[0]
        bob = client.post("/api/profiles", json={"name": "Bob"}).json()
        account = client.post(
            "/api/accounts", json={"name": "Ancien compte partage"}
        ).json()

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO shared_account_links "
            "(household_id, account_id, permission, created_at) "
            "VALUES (?, ?, 'edit', CURRENT_TIMESTAMP)",
            (household["id"], account["id"]),
        )

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        profiles = client.get("/api/profiles").json()
        alice = next(profile for profile in profiles if profile["id"] != bob["id"])
        assert client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200
        assert account["id"] in {
            item["id"] for item in client.get("/api/accounts").json()
        }
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        assert client.get("/api/accounts").json() == []


def test_v25_classic_data_is_preserved_and_assigned_to_first_admin(
    tmp_path, monkeypatch
):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice historique"}).json()
        assert client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200
        bob = client.post("/api/profiles", json={"name": "Bob historique"}).json()
        household = client.get("/api/households").json()[0]

        account = client.post(
            "/api/accounts",
            json={
                "name": "Compte classique",
                "type": "checking",
                "initial_balance": "1234.56",
            },
        ).json()
        snapshot = client.put(
            f"/api/accounts/{account['id']}/snapshots",
            json={"period": "2026-08", "balance": "1300.00"},
        ).json()
        snapshot_attachment = client.post(
            f"/api/accounts/{account['id']}/snapshots/{snapshot['id']}/attachments",
            files={
                "file": (
                    "releve-classique.txt",
                    io.BytesIO(b"releve synthetique"),
                    "text/plain",
                )
            },
        ).json()
        recurring = client.post(
            "/api/recurring",
            json={
                "label": "Salaire classique",
                "account_id": account["id"],
                "frequency": "monthly",
                "next_due": "2026-10-01",
                "amount": "3200.00",
                "recurring_type": "salary",
            },
        ).json()
        recurring_attachment = client.post(
            f"/api/recurring/{recurring['id']}/attachments",
            files={
                "file": (
                    "salaire-classique.txt",
                    io.BytesIO(b"recurrent synthetique"),
                    "text/plain",
                )
            },
        ).json()
        investment = client.post(
            "/api/accounts",
            json={
                "name": "PEA classique",
                "type": "pea",
                "initial_balance": "0.00",
            },
        ).json()
        holding = client.post(
            "/api/holdings",
            json={
                "account_id": investment["id"],
                "name": "ETF classique",
                "symbol": "SYN",
                "asset_class": "equity",
                "quantity": "4",
                "average_price": "100.00",
                "current_price": "125.00",
            },
        ).json()
        assert client.post(
            "/api/contributions",
            json={
                "holding_id": holding["id"],
                "amount": "400.00",
                "occurred_on": "2026-01-15",
                "note": "Apport classique",
            },
        ).status_code == 201

        debt = client.post(
            "/api/debts",
            json={
                "name": "Dette classique",
                "principal": "90000.00",
                "balance": "75000.00",
                "account_id": account["id"],
            },
        ).json()
        debt_attachment = client.post(
            f"/api/debts/{debt['id']}/attachments",
            files={
                "file": (
                    "dette-classique.txt",
                    io.BytesIO(b"dette synthetique"),
                    "text/plain",
                )
            },
        ).json()
        asset = client.post(
            "/api/real-estate",
            json={
                "name": "Maison classique",
                "purchase_price": "200000.00",
                "current_value": "240000.00",
                "ownership_share": "100.00",
                "debt_ids": [debt["id"]],
            },
        ).json()
        asset_attachment = client.post(
            f"/api/real-estate/{asset['id']}/attachments",
            files={
                "file": (
                    "maison-classique.txt",
                    io.BytesIO(b"bien synthetique"),
                    "text/plain",
                )
            },
        ).json()

        goal = client.post(
            f"/api/households/{household['id']}/goals",
            json={
                "name": "Projet classique",
                "target_amount": "5000.00",
                "account_id": account["id"],
            },
        ).json()
        assert client.post(
            f"/api/households/{household['id']}/goals/{goal['id']}/contributions",
            json={
                "amount": "250.00",
                "occurred_on": "2026-08-10",
                "note": "Contribution classique",
            },
        ).status_code == 201

        contract = client.post(
            "/api/work/contracts",
            json={
                "employer": "Employeur classique",
                "position": "Poste classique",
                "start_date": "2024-01-15",
                "gross_annual_salary": "48000.00",
            },
        ).json()
        contract_attachment = client.post(
            f"/api/work/contracts/{contract['id']}/attachments",
            files={
                "file": (
                    "contrat-classique.txt",
                    io.BytesIO(b"contrat synthetique"),
                    "text/plain",
                )
            },
        ).json()
        payslip = client.post(
            "/api/work/payslips",
            json={
                "contract_id": contract["id"],
                "period": "2026-08",
                "gross_salary": "4000.00",
                "taxable_net": "3200.00",
                "net_before_tax": "3100.00",
                "pas_rate": "8.00",
                "pas_amount": "248.00",
                "net_after_tax": "2852.00",
            },
        ).json()
        payslip_attachment = client.post(
            f"/api/work/payslips/{payslip['id']}/attachments",
            files={
                "file": (
                    "paie-classique.txt",
                    io.BytesIO(b"paie synthetique"),
                    "text/plain",
                )
            },
        ).json()
        pension = client.put(
            "/api/work/pension",
            json={
                "birth_year": 1988,
                "validated_quarters": 72,
                "required_quarters": 172,
                "target_monthly_income": "2500.00",
            },
        ).json()

    preserved_tables = (
        "accounts",
        "balance_snapshots",
        "balance_snapshot_attachments",
        "categories",
        "preferences",
        "recurring_series",
        "recurring_series_attachments",
        "debts",
        "debt_attachments",
        "real_estate_assets",
        "real_estate_debt_links",
        "real_estate_attachments",
        "holdings",
        "holding_operations",
        "contributions",
        "portfolio_snapshots",
        "households",
        "household_members",
        "goals",
        "goal_contributions",
        "work_contracts",
        "work_contract_attachments",
        "pay_slips",
        "pay_slip_attachments",
        "pension_profiles",
    )

    def preserved_state(connection):
        excluded_columns = {
            "household_members": {"role", "avatar", "color", "active", "pin_hash"},
            "work_contracts": {"profile_id"},
            "pay_slips": {"profile_id"},
            "pension_profiles": {"profile_id"},
        }
        state = {}
        for table in preserved_tables:
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
                if row[1] not in excluded_columns.get(table, set())
            ]
            column_sql = ", ".join(f'"{column}"' for column in columns)
            state[table] = (
                columns,
                connection.execute(
                    f'SELECT {column_sql} FROM "{table}" ORDER BY id'
                ).fetchall(),
            )
        return state

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO portfolio_snapshots "
            "(period, market_value, cost_basis, created_at) "
            "VALUES ('2026-08', '500.00', '400.00', CURRENT_TIMESTAMP)"
        )
        connection.execute("DROP TABLE profile_sessions")
        connection.execute("DROP TABLE account_owners")
        connection.execute("DROP TABLE real_estate_owners")
        connection.execute("DROP TABLE debt_owners")
        connection.execute("DROP INDEX ix_household_members_active")
        connection.execute("ALTER TABLE household_members DROP COLUMN avatar")
        connection.execute("ALTER TABLE household_members DROP COLUMN color")
        connection.execute("ALTER TABLE household_members DROP COLUMN active")
        connection.execute("ALTER TABLE household_members DROP COLUMN pin_hash")
        connection.execute("PRAGMA legacy_alter_table = ON")
        connection.executescript(
            """
            ALTER TABLE work_contracts RENAME TO work_contracts_multi_user;
            CREATE TABLE work_contracts (
                id INTEGER PRIMARY KEY,
                employer VARCHAR(120) NOT NULL,
                position VARCHAR(120) NOT NULL,
                contract_type VARCHAR(32) NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                gross_annual_salary NUMERIC(12, 2) NOT NULL,
                payment_period_months INTEGER DEFAULT 12 NOT NULL,
                work_percentage INTEGER NOT NULL,
                recurring_series_id INTEGER REFERENCES recurring_series(id)
                    ON DELETE SET NULL,
                status VARCHAR(20) NOT NULL,
                notes VARCHAR(500),
                document_ignored BOOLEAN DEFAULT 0 NOT NULL,
                created_at DATETIME
            );
            INSERT INTO work_contracts (
                id, employer, position, contract_type, start_date, end_date,
                gross_annual_salary, payment_period_months, work_percentage,
                recurring_series_id, status, notes, document_ignored, created_at
            )
            SELECT
                id, employer, position, contract_type, start_date, end_date,
                gross_annual_salary, payment_period_months, work_percentage,
                recurring_series_id, status, notes, document_ignored, created_at
            FROM work_contracts_multi_user;
            DROP TABLE work_contracts_multi_user;

            ALTER TABLE pay_slips RENAME TO pay_slips_multi_user;
            CREATE TABLE pay_slips (
                id INTEGER PRIMARY KEY,
                contract_id INTEGER REFERENCES work_contracts(id) ON DELETE SET NULL,
                period VARCHAR(7) NOT NULL,
                gross_salary NUMERIC(12, 2) NOT NULL,
                taxable_net NUMERIC(12, 2) NOT NULL,
                net_before_tax NUMERIC(12, 2) NOT NULL,
                pas_rate NUMERIC(5, 2) NOT NULL,
                pas_amount NUMERIC(12, 2) NOT NULL,
                net_after_tax NUMERIC(12, 2) NOT NULL,
                bonuses NUMERIC(12, 2) NOT NULL,
                employer_contributions NUMERIC(12, 2) NOT NULL,
                employer_profit_sharing NUMERIC(12, 2) NOT NULL,
                hours_worked NUMERIC(6, 2),
                overtime_hours NUMERIC(6, 2),
                notes VARCHAR(500),
                document_ignored BOOLEAN DEFAULT 0 NOT NULL,
                created_at DATETIME
            );
            INSERT INTO pay_slips (
                id, contract_id, period, gross_salary, taxable_net,
                net_before_tax, pas_rate, pas_amount, net_after_tax, bonuses,
                employer_contributions, employer_profit_sharing, hours_worked,
                overtime_hours, notes, document_ignored, created_at
            )
            SELECT
                id, contract_id, period, gross_salary, taxable_net,
                net_before_tax, pas_rate, pas_amount, net_after_tax, bonuses,
                employer_contributions, employer_profit_sharing, hours_worked,
                overtime_hours, notes, document_ignored, created_at
            FROM pay_slips_multi_user;
            DROP TABLE pay_slips_multi_user;
            """
        )
        connection.execute(
            "ALTER TABLE pension_profiles RENAME TO pension_profiles_multi_user"
        )
        connection.execute(
            """
            CREATE TABLE pension_profiles (
                id INTEGER PRIMARY KEY,
                birth_year INTEGER NOT NULL,
                birth_month INTEGER DEFAULT 1 NOT NULL,
                target_retirement_age INTEGER NOT NULL,
                validated_quarters INTEGER NOT NULL,
                required_quarters INTEGER NOT NULL,
                estimated_monthly_pension NUMERIC(12, 2) NOT NULL,
                target_monthly_income NUMERIC(12, 2) NOT NULL,
                income_growth_scenario VARCHAR(24) DEFAULT 'regular' NOT NULL,
                future_annual_gross NUMERIC(12, 2),
                future_work_percentage INTEGER DEFAULT 100 NOT NULL,
                planned_unemployment_months INTEGER DEFAULT 0 NOT NULL,
                notes VARCHAR(500),
                updated_at DATETIME
            )
            """
        )
        connection.execute(
            """
            INSERT INTO pension_profiles (
                id, birth_year, birth_month, target_retirement_age,
                validated_quarters, required_quarters, estimated_monthly_pension,
                target_monthly_income, income_growth_scenario, future_annual_gross,
                future_work_percentage, planned_unemployment_months, notes, updated_at
            )
            SELECT
                id, birth_year, birth_month, target_retirement_age,
                validated_quarters, required_quarters, estimated_monthly_pension,
                target_monthly_income, income_growth_scenario, future_annual_gross,
                future_work_percentage, planned_unemployment_months, notes, updated_at
            FROM pension_profiles_multi_user
            """
        )
        connection.execute("DROP TABLE pension_profiles_multi_user")
        connection.execute("PRAGMA legacy_alter_table = OFF")
        connection.execute(
            "UPDATE household_members SET role = CASE "
            "WHEN id = ? THEN 'owner' ELSE 'member' END",
            (alice["id"],),
        )
        connection.execute(
            "INSERT INTO shared_account_links "
            "(household_id, account_id, permission, created_at) "
            "VALUES (?, ?, 'edit', CURRENT_TIMESTAMP)",
            (household["id"], account["id"]),
        )
        connection.execute(
            "CREATE UNIQUE INDEX legacy_unique_account_name ON accounts(name)"
        )
        connection.execute("PRAGMA user_version = 25")
        classic_state = preserved_state(connection)

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        profiles = client.get("/api/profiles").json()
        migrated_alice = next(item for item in profiles if item["id"] == alice["id"])
        assert migrated_alice["role"] == "admin"
        assert migrated_alice["active"] is True
        assert client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200
        assert {item["name"] for item in client.get("/api/accounts").json()} >= {
            "Compte classique",
            "PEA classique",
        }
        assert {item["label"] for item in client.get("/api/recurring").json()} == {
            "Salaire classique"
        }
        assert {item["name"] for item in client.get("/api/debts").json()} == {
            "Dette classique"
        }
        assert {item["name"] for item in client.get("/api/real-estate").json()} == {
            "Maison classique"
        }
        assert {item["name"] for item in client.get("/api/holdings").json()} == {
            "ETF classique"
        }
        assert client.get("/api/work/contracts").json()[0]["employer"] == (
            "Employeur classique"
        )
        assert client.get("/api/work/payslips").json()[0]["period"] == "2026-08"
        assert client.get("/api/work/pension").json()["id"] == pension["id"]
        assert client.get(
            f"/api/accounts/{account['id']}/snapshots/{snapshot['id']}/"
            f"attachments/{snapshot_attachment['id']}/download"
        ).content == b"releve synthetique"
        assert client.get(
            f"/api/recurring/{recurring['id']}/attachments/"
            f"{recurring_attachment['id']}/download"
        ).content == b"recurrent synthetique"
        assert client.get(
            f"/api/debts/{debt['id']}/attachments/"
            f"{debt_attachment['id']}/download"
        ).content == b"dette synthetique"
        assert client.get(
            f"/api/real-estate/{asset['id']}/attachments/"
            f"{asset_attachment['id']}/download"
        ).content == b"bien synthetique"
        assert client.get(
            f"/api/work/contracts/{contract['id']}/attachments/"
            f"{contract_attachment['id']}/download"
        ).content == b"contrat synthetique"
        assert client.get(
            f"/api/work/payslips/{payslip['id']}/attachments/"
            f"{payslip_attachment['id']}/download"
        ).content == b"paie synthetique"

        assert client.post(
            f"/api/profiles/{bob['id']}/select", json={}
        ).status_code == 200
        assert client.get("/api/accounts").json() == []
        assert client.get("/api/recurring").json() == []
        assert client.get("/api/debts").json() == []
        assert client.get("/api/real-estate").json() == []
        assert client.get("/api/holdings").json() == []
        assert client.get("/api/work/contracts").json() == []
        assert client.get("/api/work/payslips").json() == []

    with sqlite3.connect(db_path) as connection:
        assert preserved_state(connection) == classic_state
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 29
        assert connection.execute(
            "SELECT COUNT(*) FROM shared_account_links"
        ).fetchone()[0] == 0
        for table, resource_column, owner_table in (
            ("accounts", "account_id", "account_owners"),
            ("real_estate_assets", "asset_id", "real_estate_owners"),
            ("debts", "debt_id", "debt_owners"),
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {owner_table}"
            ).fetchone()[0] == connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            assert connection.execute(
                f"SELECT DISTINCT member_id FROM {owner_table}"
            ).fetchall() == [(alice["id"],)]
            assert connection.execute(
                f"SELECT COUNT(DISTINCT {resource_column}) FROM {owner_table}"
            ).fetchone()[0] == len(classic_state[table][1])
        for table in ("work_contracts", "pay_slips", "pension_profiles"):
            assert connection.execute(
                f"SELECT DISTINCT profile_id FROM {table}"
            ).fetchall() == [(alice["id"],)]
        pension_unique_indexes = [
            row[1]
            for row in connection.execute("PRAGMA index_list(pension_profiles)")
            if row[2]
        ]
        assert pension_unique_indexes
        ownership_state = {
            owner_table: connection.execute(
                f"SELECT * FROM {owner_table} ORDER BY id"
            ).fetchall()
            for owner_table in ("account_owners", "real_estate_owners", "debt_owners")
        }

    backups = list(tmp_path.glob("moulaga.backup-*-v25.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 25
        assert preserved_state(backup) == classic_state
        assert backup.execute(
            "SELECT COUNT(*) FROM shared_account_links"
        ).fetchone()[0] == 1
        backup_tables = {
            row[0]
            for row in backup.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "account_owners",
            "real_estate_owners",
            "debt_owners",
            "profile_sessions",
        }.isdisjoint(backup_tables)

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()):
        pass
    assert list(tmp_path.glob("moulaga.backup-*.db")) == backups
    with sqlite3.connect(db_path) as connection:
        assert preserved_state(connection) == classic_state
        assert {
            owner_table: connection.execute(
                f"SELECT * FROM {owner_table} ORDER BY id"
            ).fetchall()
            for owner_table in ("account_owners", "real_estate_owners", "debt_owners")
        } == ownership_state


def test_migration_rolls_back_before_version_update_on_foreign_key_failure(
    tmp_path, monkeypatch
):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200
        household = client.get("/api/households").json()[0]
        account = client.get("/api/accounts").json()[0]

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO goals "
            "(household_id, name, target_amount, current_amount, account_id, created_at) "
            "VALUES (?, 'Relation invalide', '100.00', '0.00', 999999, CURRENT_TIMESTAMP)",
            (household["id"],),
        )
        connection.execute(
            "INSERT INTO shared_account_links "
            "(household_id, account_id, permission, created_at) "
            "VALUES (?, ?, 'edit', CURRENT_TIMESTAMP)",
            (household["id"], account["id"]),
        )
        connection.execute("PRAGMA user_version = 27")

    main, _ = load_app(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="cles etrangeres"), TestClient(
        main.create_app()
    ):
        pass

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 27
        assert connection.execute(
            "SELECT COUNT(*) FROM shared_account_links"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT account_id FROM goals WHERE name = 'Relation invalide'"
        ).fetchone()[0] == 999999
    assert len(list(tmp_path.glob("moulaga.backup-*-v27.db"))) == 1


def test_v20_database_adds_contract_attachment_support(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
        migrated = next(
            item for item in client.get("/api/holdings").json()
            if item["id"] == holding["id"]
        )
        operations = client.get(f"/api/holdings/{holding['id']}/operations").json()

    assert migrated["quantity"] == "7.5000000000"
    assert migrated["average_price"] == "42.250000"
    assert migrated["operation_count"] == 1
    assert len(operations) == 1
    assert operations[0]["operation_type"] == "buy"
    assert operations[0]["quantity"] == "7.5000000000"
    assert operations[0]["unit_price"] == "42.25"
    assert operations[0]["occurred_on"] == operations[0]["created_at"][:10]
    assert len(list(tmp_path.glob("moulaga.backup-*.db"))) == 1


def test_v22_database_backfills_holding_operation_dates(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
        account = client.post(
            "/api/accounts",
            json={"name": "PEA date", "type": "pea", "initial_balance": "0.00"},
        ).json()
        holding = client.post(
            "/api/holding-operations",
            json={
                "new_holding": {
                    "account_id": account["id"],
                    "name": "ETF date",
                },
                "operation_type": "buy",
                "quantity": "2",
                "unit_price": "25.00",
                "occurred_on": "2026-03-14",
            },
        ).json()["holding"]

    db_path = tmp_path / "moulaga.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX ix_holding_operations_occurred_on")
        connection.execute("ALTER TABLE holding_operations DROP COLUMN occurred_on")
        connection.execute("PRAGMA user_version = 22")

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
        operations = client.get(f"/api/holdings/{holding['id']}/operations").json()

    assert len(operations) == 1
    assert operations[0]["occurred_on"] == operations[0]["created_at"][:10]
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 23
    assert len(list(tmp_path.glob("moulaga.backup-*.db"))) == 1


def test_v16_database_drops_obsolete_recurring_columns(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        _select_or_create_profile(client)
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
