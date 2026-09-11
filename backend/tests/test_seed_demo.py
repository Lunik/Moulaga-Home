"""Contracts for the transaction-free synthetic demonstration seed."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from pathlib import Path

import pytest
from conftest import load_app
from fastapi.testclient import TestClient


def _load_seed(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    import app.commands.seed_demo as seed

    importlib.reload(seed)
    return main, seed


def test_seed_demo_populates_current_product_contract(tmp_path, monkeypatch):
    main, seed = _load_seed(tmp_path, monkeypatch)
    result = asyncio.run(seed.seed_demo())
    assert result.accounts == 10
    assert result.snapshots == 309
    assert result.categories == 11
    assert result.recurring == 14
    assert result.debts == 4
    assert result.real_estate_assets == 2
    assert result.holdings == 3
    assert result.households == 1
    assert result.snapshot_attachments == 2
    assert result.recurring_attachments == 2
    assert result.contracts == 2
    assert result.payslips == 6
    assert result.payslip_attachments == 1

    with TestClient(main.create_app()) as client:
        accounts = client.get("/api/accounts").json()
        assert len(accounts) == 9
        assert len({account["balance"] for account in accounts}) > 6
        assert next(account for account in accounts if account["name"] == "PEA demo")[
            "balance"
        ] == "2634.00"

        recurring = client.get("/api/recurring").json()
        assert len(recurring) == 14
        assert any(item["amount_type"] == "variable" for item in recurring)
        assert sum(item["recurring_type"] == "salary" for item in recurring) == 1
        salary = next(item for item in recurring if item["label"] == "Salaire mensuel")
        assert salary["amount"] == "3126.50"

        contracts = client.get("/api/work/contracts").json()
        assert len(contracts) == 2
        current_contract = next(item for item in contracts if item["status"] == "active")
        previous_contract = next(item for item in contracts if item["status"] == "ended")
        assert current_contract["recurring_series_id"] == salary["id"]
        assert current_contract["payment_period_months"] == 12
        assert previous_contract["recurring_series_id"] is None
        assert previous_contract["end_date"] == "2021-08-31"

        payslips = client.get("/api/work/payslips").json()
        assert len(payslips) == 6
        assert payslips[0]["period"] == "2026-09"
        assert payslips[0]["net_after_tax"] == salary["amount"]
        assert len(payslips[0]["attachments"]) == 1

        work_summary = client.get("/api/work/summary").json()
        assert work_summary["active_contracts_count"] == 1
        assert work_summary["latest_net_after_tax"] == salary["amount"]

        documents = client.get("/api/documents").json()
        assert documents["stats"]["total_documents"] == 6
        assert documents["stats"]["missing_resources"] > 12
        assert {item["kind"] for item in documents["documents"]} == {
            "snapshot",
            "recurring",
            "debt",
            "real_estate",
        }
        assert any(
            item["original_name"] == "bulletin-salaire-demo.txt"
            for item in documents["documents"]
        )
        assert len(documents["kinds"]) == 4

        overview = client.get("/api/overview").json()
        assert float(overview["income_current_month"]) > 0
        assert float(overview["expenses_current_month"]) > 0
        assert len(client.get("/api/stats/monthly").json()) == 12

        source_flows = client.get(
            "/api/budget/cashflow",
            params={"by": "source"},
        ).json()
        category_flows = client.get(
            "/api/budget/cashflow",
            params={"by": "category"},
        ).json()
        assert any(float(flow["inflow"]) > 0 for flow in source_flows)
        assert any(float(flow["outflow"]) > 0 for flow in category_flows)
        assert client.get("/api/budget/spending").json()

        net_worth = client.get("/api/networth/overview").json()
        assert net_worth["net_worth"] != "0.00"
        assert client.get("/api/networth/history").json()

        paths = client.get("/api/openapi.json").json()["paths"]
        assert not any("transaction" in path for path in paths)
        assert "/api/recurring/detect" not in paths
        assert "/api/recurring/changes" not in paths

    with sqlite3.connect(tmp_path / "moulaga.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "transactions" not in tables
    assert "transaction_attachments" not in tables
    assert "categorization_rules" not in tables
    assert "merchant_identities" not in tables


def test_seed_demo_attachments_are_downloadable(tmp_path, monkeypatch):
    main, seed = _load_seed(tmp_path, monkeypatch)
    asyncio.run(seed.seed_demo())
    with TestClient(main.create_app()) as client:
        savings = next(
            account for account in client.get("/api/accounts").json()
            if account["name"] == "Livret epargne demo"
        )
        statement = next(
            item for item in client.get(f"/api/accounts/{savings['id']}/snapshots").json()
            if item["attachment_count"] == 1
        )
        attachments = client.get(
            f"/api/accounts/{savings['id']}/snapshots/{statement['id']}/attachments"
        ).json()
        assert attachments
        assert client.get(
            f"/api/accounts/{savings['id']}/snapshots/{statement['id']}/attachments/"
            f"{attachments[0]['id']}/download"
        ).status_code == 200

        latest_payslip = client.get("/api/work/payslips").json()[0]
        payslip_attachment = latest_payslip["attachments"][0]
        payslip_download = client.get(
            f"/api/work/attachments/{payslip_attachment['id']}"
        )
        assert payslip_download.status_code == 200
        assert b"entierement synthetique" in payslip_download.content


def test_seed_demo_refuses_overwrite_and_reset_reseeds(tmp_path, monkeypatch):
    _, seed = _load_seed(tmp_path, monkeypatch)
    asyncio.run(seed.seed_demo())
    old_files = {
        path for path in (tmp_path / "attached").rglob("*") if path.is_file()
    }
    assert len(old_files) == 7
    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())

    result = asyncio.run(seed.seed_demo(reset=True))
    assert result.households == 1
    new_files = {
        path for path in (tmp_path / "attached").rglob("*") if path.is_file()
    }
    assert len(new_files) == 7


def test_seed_demo_refuses_default_data_dir(tmp_path, monkeypatch):
    _, seed = _load_seed(tmp_path, monkeypatch)
    monkeypatch.setattr(seed.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(seed.settings, "database_url", None)
    monkeypatch.setattr(seed.settings, "demo_mode", False)
    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())


def test_seed_demo_allows_default_data_dir_only_in_demo_mode(tmp_path, monkeypatch):
    _, seed = _load_seed(tmp_path, monkeypatch)
    monkeypatch.setattr(seed.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(seed.settings, "database_url", None)
    monkeypatch.setattr(seed.settings, "demo_mode", True)
    seed._guard_data_dir()


def test_seed_demo_cli_output_hides_database_path(tmp_path, monkeypatch, capsys):
    _, seed = _load_seed(tmp_path, monkeypatch)
    assert seed.main([]) == 0
    captured = capsys.readouterr()
    assert "Donnees de demo generees" in captured.out
    assert str(tmp_path) not in captured.out
    assert "moulaga.db" not in captured.out
