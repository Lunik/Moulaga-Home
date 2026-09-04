"""Test for the developer-only demo seeding command."""

from __future__ import annotations

import asyncio
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
    assert result.accounts == 5
    assert result.transactions > 100
    assert result.snapshots == 9
    assert result.debts == 3
    assert result.holdings == 2
    assert result.households == 1
    assert result.portfolio_snapshots > 0
    assert result.merchants > 0
    assert result.transaction_attachments == 2
    assert result.snapshot_attachments == 2

    with TestClient(main.create_app()) as client:
        accounts = client.get("/api/accounts").json()
        assert len(accounts) == 4
        savings = next(account for account in accounts if account["type"] == "savings")
        assert next(account for account in accounts if account["name"] == "PEA demo")["type"] == "pea"
        assert savings["savings_product"] == "Livret A"
        assert savings["legal_cap"] == "22950.00"
        assert client.get("/api/debts").json()
        assert client.get("/api/holdings").json()
        assert client.get("/api/rules").json()
        assert client.get("/api/recurring").json()
        assert client.get("/api/recurring/changes", params={"status": "pending"}).json()
        assert client.get("/api/portfolio/performance").json()
        assert client.get("/api/merchants").json()
        assert client.get("/api/contributions").json()
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
        assert len(active_accounts) == 4
        assert len(all_accounts) == 5

        checking = next(
            account for account in all_accounts if account["name"] == "Compte courant demo"
        )
        savings = next(
            account for account in all_accounts if account["name"] == "Livret epargne demo"
        )
        pea = next(account for account in all_accounts if account["name"] == "PEA demo")
        archived = next(account for account in all_accounts if account["archived"])
        sandbox = next(
            account for account in all_accounts if account["name"] == "Compte bac a sable demo"
        )

        assert checking["account_number"] == "DEMO-COURANT-001"
        assert checking["transaction_count"] > 100
        assert savings["institution"] == checking["institution"] == "BNP Paribas"
        assert savings["annual_interest_rate"] == "1.700"
        assert savings["legal_cap"] == "22950.00"
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
        receipt_transaction = next(
            transaction
            for transaction in checking_transactions
            if transaction["attachment_count"] == 1
        )
        assert receipt_transaction["notes"] == "Ticket de caisse synthetique joint."
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
