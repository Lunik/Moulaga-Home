"""Test for the developer-only demo seeding command."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest
from conftest import load_app
from fastapi.testclient import TestClient


def test_seed_demo_populates_all_domains(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)

    result = asyncio.run(seed.seed_demo())
    assert result.accounts == 10
    assert result.transactions > 100
    assert result.snapshots == 309
    assert result.debts == 4
    assert result.real_estate_assets == 1
    assert result.holdings == 2
    assert result.households == 1
    assert result.portfolio_snapshots > 0
    assert result.merchants > 0
    assert result.transaction_attachments == 2
    assert result.snapshot_attachments == 2

    with TestClient(main.create_app()) as client:
        accounts = client.get("/api/accounts").json()
        assert len(accounts) == 9
        assert len({account["balance"] for account in accounts}) > 6
        assert sum(float(account["balance"]) > 0 for account in accounts) > 6
        savings = next(account for account in accounts if account["type"] == "savings")
        pea = next(account for account in accounts if account["name"] == "PEA demo")
        assert pea["type"] == "pea"
        assert pea["institution"] == "Boursobank"
        assert next(
            account for account in accounts if account["name"] == "PEG Amundi demo"
        )["type"] == "peg"
        assert next(
            account for account in accounts if account["name"] == "PER/PERCOL Amundi demo"
        )["type"] == "percol"
        assert next(
            account for account in accounts if account["name"] == "Assurance vie Boursobank demo"
        )["type"] == "life_insurance"
        assert next(
            account for account in accounts if account["name"] == "Wallet crypto demo"
        )["type"] == "wallet"
        assert savings["savings_product"] == "Livret A"
        assert savings["legal_cap"] == "22950.00"
        assert client.get("/api/debts").json()
        real_estate = client.get("/api/real-estate").json()
        assert len(real_estate) == 1
        assert real_estate[0]["debt_name"] == "Pret immobilier demo"
        assert client.get("/api/holdings").json()
        rules = client.get("/api/rules").json()
        assert any(len(rule["patterns"]) >= 3 for rule in rules)
        recurring = client.get("/api/recurring").json()
        assert len(recurring) == 3
        assert any(series["amount_type"] == "variable" for series in recurring)
        assert client.get("/api/recurring/detect").json()
        envelopes = client.get("/api/budget/envelopes").json()
        unlimited = next(envelope for envelope in envelopes if envelope["category_name"] == "Transport")
        assert unlimited["budget"] is None
        assert unlimited["remaining"] is None
        assert unlimited["spent"] == "58.40"
        logement = next(envelope for envelope in envelopes if envelope["category_name"] == "Logement")
        assert logement["children_budget"] == "160.00"
        assert logement["remainder_budget"] == "740.00"
        assert logement["direct_spent"] == "750.00"
        assert logement["spent"] == "884.99"
        budget_overview = client.get("/api/budget/overview").json()
        assert budget_overview["budget_total"] == "1350.00"
        dashboard_overview = client.get("/api/overview").json()
        assert float(dashboard_overview["income_current_month"]) >= 2500
        assert float(dashboard_overview["expenses_current_month"]) >= 0
        assert float(dashboard_overview["budget_remaining"]) == pytest.approx(
            float(dashboard_overview["budget_current_month"])
            - float(dashboard_overview["expenses_current_month"])
        )
        monthly_stats = client.get("/api/stats/monthly").json()
        assert len(monthly_stats) == 4
        assert monthly_stats[-1] == {
            "month": date.today().strftime("%Y-%m"),
            "income": dashboard_overview["income_current_month"],
            "expenses": dashboard_overview["expenses_current_month"],
            "net": dashboard_overview["net_current_month"],
        }
        net_worth_overview = client.get("/api/networth/overview").json()
        assert net_worth_overview["net_worth"] != "0.00"
        net_worth_history = client.get("/api/networth/history").json()
        assert len(net_worth_history) >= 4
        assert net_worth_history[-1]["period"] == date.today().strftime("%Y-%m")
        assert net_worth_history[-1]["net_worth"] == net_worth_overview["net_worth"]
        recent_transactions = client.get(
            "/api/transactions",
            params={"end": date.today().isoformat(), "limit": 6},
        ).json()
        assert len(recent_transactions) == 6
        assert all(
            transaction["booked_at"] <= date.today().isoformat()
            for transaction in recent_transactions
        )
        categories = client.get("/api/categories").json()
        archived_category = next(
            category for category in categories if category["name"] == "Ancienne categorie demo"
        )
        assert archived_category["archived"] is True
        archived_history = client.get(
            "/api/transactions",
            params={"category_id": archived_category["id"], "limit": 1000},
        ).json()
        assert len(archived_history) == 1
        assert client.get("/api/recurring/changes", params={"status": "pending"}).json()
        assert client.get("/api/portfolio/performance").json()
        assert client.get("/api/merchants").json()
        assert client.get("/api/contributions").json()
        visual_read_models = [
            "/api/accounts/institution-history",
            "/api/budget/cashflow?period=cycle&by=source",
            "/api/budget/cashflow?period=year&by=category",
            "/api/budget/spending?period=cycle",
            "/api/recurring/forecast?months=3",
            "/api/portfolio/summary",
            "/api/portfolio/allocation",
            "/api/networth/overview",
            "/api/networth/history",
        ]
        for path in visual_read_models:
            response = client.get(path)
            assert response.status_code == 200
            assert response.json()
        households = client.get("/api/households").json()
        assert households
        goals = client.get(f"/api/households/{households[0]['id']}/goals").json()
        assert goals and goals[0]["current_amount"] == "750.00"


def test_seed_demo_covers_every_account_page_state(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)
    asyncio.run(seed.seed_demo())

    with TestClient(main.create_app()) as client:
        active_accounts = client.get("/api/accounts").json()
        all_accounts = client.get(
            "/api/accounts", params={"include_archived": True}
        ).json()
        assert len(active_accounts) == 9
        assert len(all_accounts) == 10

        checking = next(
            account for account in all_accounts if account["name"] == "Compte courant demo"
        )
        savings = next(
            account for account in all_accounts if account["name"] == "Livret epargne demo"
        )
        pea = next(account for account in all_accounts if account["name"] == "PEA demo")
        peg = next(account for account in all_accounts if account["name"] == "PEG Amundi demo")
        percol = next(
            account for account in all_accounts if account["name"] == "PER/PERCOL Amundi demo"
        )
        boursobank_checking = next(
            account
            for account in all_accounts
            if account["name"] == "Compte courant Boursobank demo"
        )
        life_insurance = next(
            account
            for account in all_accounts
            if account["name"] == "Assurance vie Boursobank demo"
        )
        crypto_wallet = next(
            account for account in all_accounts if account["name"] == "Wallet crypto demo"
        )
        archived = next(account for account in all_accounts if account["archived"])
        sandbox = next(
            account for account in all_accounts if account["name"] == "Compte bac a sable demo"
        )

        assert checking["account_number"] == "DEMO-COURANT-001"
        assert checking["transaction_count"] > 100
        assert checking["institution"] == savings["institution"] == "Caisse d’Épargne"
        assert checking["regional_entity"] == "Loire Drôme Ardèche"
        assert savings["regional_entity"] == "Rhône Alpes"
        assert savings["annual_interest_rate"] == "1.700"
        assert savings["legal_cap"] == "22950.00"
        assert pea["institution"] == "Boursobank"
        assert pea["balance"] == "2634.00"
        assert peg["type"] == "peg"
        assert peg["institution"] == "Amundi"
        assert peg["initial_balance"] == "0.00"
        assert peg["balance"] == "7800.00"
        assert percol["type"] == "percol"
        assert percol["institution"] == "Amundi"
        assert percol["balance"] == "11200.00"
        assert boursobank_checking["type"] == "checking"
        assert boursobank_checking["institution"] == "Boursobank"
        assert boursobank_checking["balance"] == "2750.00"
        assert boursobank_checking["transaction_count"] == 8
        assert life_insurance["type"] == "life_insurance"
        assert life_insurance["institution"] == "Boursobank"
        assert life_insurance["balance"] == "18500.00"
        assert crypto_wallet["type"] == "wallet"
        assert crypto_wallet["institution"] == "Revolut"
        assert crypto_wallet["balance"] == "4200.00"
        assert archived["name"] == "Compte cloture demo"
        assert archived["transaction_count"] == 2
        assert sandbox["type"] == "cash"
        assert sandbox["institution"] is None
        assert sandbox["balance"] == "125.00"
        assert sandbox["transaction_count"] == 0

        checking_transactions = client.get(
            "/api/transactions",
            params={"account_id": checking["id"], "limit": 1000},
        ).json()
        boursobank_transactions = client.get(
            "/api/transactions",
            params={"account_id": boursobank_checking["id"], "limit": 1000},
        ).json()
        assert len(boursobank_transactions) == 8
        assert sum(
            transaction["amount"] == "500.00"
            for transaction in boursobank_transactions
        ) == 4
        receipt_transaction = next(
            transaction
            for transaction in checking_transactions
            if transaction["attachment_count"] == 1
        )
        assert receipt_transaction["notes"] == "Ticket de caisse synthetique joint."
        complete_ledger = client.get("/api/transactions", params={"limit": 1000}).json()
        assert any(transaction["attachment_count"] > 0 for transaction in complete_ledger)
        assert len({transaction["account_id"] for transaction in complete_ledger}) > 1
        receipt_attachments = client.get(
            f"/api/transactions/{receipt_transaction['id']}/attachments"
        ).json()
        assert [item["original_name"] for item in receipt_attachments] == [
            "justificatif-courses-demo.txt"
        ]
        receipt_download = client.get(
            f"/api/transactions/{receipt_transaction['id']}/attachments/"
            f"{receipt_attachments[0]['id']}/download"
        )
        assert receipt_download.status_code == 200
        assert b"entierement synthetique" in receipt_download.content

        savings_transactions = client.get(
            "/api/transactions",
            params={"account_id": savings["id"], "limit": 1000},
        ).json()
        transfers = [
            transaction
            for transaction in checking_transactions + savings_transactions
            if transaction["transfer_group"] is not None
        ]
        transfer_groups = {transaction["transfer_group"] for transaction in transfers}
        assert len(transfer_groups) == 4
        assert all(
            len(
                [
                    transaction
                    for transaction in transfers
                    if transaction["transfer_group"] == transfer_group
                ]
            )
            == 2
            for transfer_group in transfer_groups
        )
        assert client.get(
            "/api/transactions/count",
            params={"account_id": checking["id"], "uncategorized": True},
        ).json()["count"] == 4

        source_cashflow = client.get(
            "/api/budget/cashflow", params={"by": "source"}
        ).json()
        positive_sources = {
            flow["label"] for flow in source_cashflow if flow["inflow"] != "0.00"
        }
        assert positive_sources == {
            "Compte courant demo",
            "Compte courant Boursobank demo",
        }
        boursobank_flow = next(
            flow
            for flow in source_cashflow
            if flow["label"] == "Compte courant Boursobank demo"
        )
        assert boursobank_flow["inflow"] == "500.00"
        assert boursobank_flow["outflow"] == "330.00"
        assert boursobank_flow["net"] == "170.00"

        for account in (life_insurance, pea, percol):
            assert len(
                client.get(f"/api/accounts/{account['id']}/snapshots").json()
            ) == 4
        for account in (checking, boursobank_checking, peg, crypto_wallet):
            assert len(
                client.get(f"/api/accounts/{account['id']}/snapshots").json()
            ) == 73

        institution_history = client.get(
            "/api/accounts/institution-history"
        ).json()
        assert {
            point["institution"] for point in institution_history
        } == {
            "Amundi",
            "Boursobank",
            "Caisse d’Épargne · Loire Drôme Ardèche",
            "Caisse d’Épargne · Rhône Alpes",
            "Revolut",
        }
        assert sum(
            point["institution"] == "Boursobank"
            for point in institution_history
        ) == 73
        history_periods = sorted({point["period"] for point in institution_history})
        assert len(history_periods) == 73
        oldest_year, oldest_month = map(int, history_periods[0].split("-"))
        latest_year, latest_month = map(int, history_periods[-1].split("-"))
        assert (latest_year - oldest_year) * 12 + latest_month - oldest_month == 72
        latest_period = max(point["period"] for point in institution_history)
        assert next(
            point["balance"]
            for point in institution_history
            if point["period"] == latest_period
            and point["institution"] == "Boursobank"
        ) == "23884.00"
        assert next(
            point["balance"]
            for point in institution_history
            if point["period"] == latest_period
            and point["institution"] == "Amundi"
        ) == "19000.00"
        assert next(
            point["balance"]
            for point in institution_history
            if point["period"] == latest_period
            and point["institution"] == "Caisse d’Épargne · Loire Drôme Ardèche"
        ) == "5562.44"
        assert next(
            point["balance"]
            for point in institution_history
            if point["period"] == latest_period
            and point["institution"] == "Caisse d’Épargne · Rhône Alpes"
        ) == "6000.00"
        year, month = latest_period.split("-")
        quick_import = client.post(
            f"/api/accounts/{peg['id']}/snapshots/import",
            json={"content": f"Date\tMontant\n28/{month}/{year}\t7 850,00 €"},
        )
        assert quick_import.status_code == 200
        assert quick_import.json()["imported_count"] == 1
        assert quick_import.json()["updated_count"] == 1
        assert quick_import.json()["snapshots"][0]["balance"] == "7850.00"
        assert client.get(f"/api/accounts/{peg['id']}").json()["balance"] == "7850.00"

        savings_snapshots = client.get(
            f"/api/accounts/{savings['id']}/snapshots"
        ).json()
        assert len(savings_snapshots) == 4
        savings_statement = next(
            snapshot for snapshot in savings_snapshots if snapshot["attachment_count"] == 1
        )
        savings_attachments = client.get(
            f"/api/accounts/{savings['id']}/snapshots/{savings_statement['id']}/attachments"
        ).json()
        assert [item["original_name"] for item in savings_attachments] == [
            "releve-livret-demo.txt"
        ]
        assert client.get(
            f"/api/accounts/{savings['id']}/snapshots/{savings_statement['id']}/"
            f"attachments/{savings_attachments[0]['id']}/download"
        ).status_code == 200

        holdings = client.get("/api/holdings", params={"account_id": pea["id"]}).json()
        assert len(holdings) == 2
        assert any(float(holding["gain"]) > 0 for holding in holdings)
        assert any(float(holding["gain"]) < 0 for holding in holdings)

        archived_transactions = client.get(
            "/api/transactions",
            params={"account_id": archived["id"], "limit": 1000},
        ).json()
        archived_receipt = next(
            transaction
            for transaction in archived_transactions
            if transaction["attachment_count"] == 1
        )
        assert client.get(
            f"/api/transactions/{archived_receipt['id']}/attachments"
        ).json()
        archived_snapshots = client.get(
            f"/api/accounts/{archived['id']}/snapshots"
        ).json()
        assert len(archived_snapshots) == 1
        assert archived_snapshots[0]["attachment_count"] == 1
        assert client.patch(
            f"/api/accounts/{archived['id']}",
            json={"name": "Modification interdite"},
        ).status_code == 409

        assert client.delete(f"/api/accounts/{sandbox['id']}").status_code == 204
        assert client.post(
            f"/api/accounts/{archived['id']}/archive",
            params={"archived": False},
        ).status_code == 200


def test_seed_demo_refuses_to_overwrite_without_reset(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)

    asyncio.run(seed.seed_demo())
    old_attachment_files = {
        path for path in (tmp_path / "attached").rglob("*") if path.is_file()
    }
    assert len(old_attachment_files) == 4
    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())

    # --reset wipes and reseeds without raising.
    result = asyncio.run(seed.seed_demo(reset=True))
    assert result.households == 1
    new_attachment_files = {
        path for path in (tmp_path / "attached").rglob("*") if path.is_file()
    }
    assert len(new_attachment_files) == 4
    assert old_attachment_files.isdisjoint(new_attachment_files)


def test_seed_demo_refuses_default_data_dir(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed
    import app.config

    importlib.reload(seed)
    # Simulate the production default path to ensure the guard trips.
    monkeypatch.setattr(app.config.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(app.config.settings, "database_url", None)
    monkeypatch.setattr(app.config.settings, "demo_mode", False)
    monkeypatch.setattr(seed.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(seed.settings, "database_url", None)
    monkeypatch.setattr(seed.settings, "demo_mode", False)

    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())


def test_seed_demo_allows_default_data_dir_only_in_demo_mode(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)
    monkeypatch.setattr(seed.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(seed.settings, "database_url", None)
    monkeypatch.setattr(seed.settings, "demo_mode", True)

    seed._guard_data_dir()


def test_seed_demo_cli_output_hides_database_path(tmp_path, monkeypatch, capsys):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)

    exit_code = seed.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Donnees de demo generees" in captured.out
    # The concrete database path must never be printed.
    assert str(tmp_path) not in captured.out
    assert "moulaga.db" not in captured.out
