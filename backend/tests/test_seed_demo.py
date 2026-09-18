"""Contracts for the transaction-free synthetic demonstration seed."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import load_app
from fastapi.testclient import TestClient


def _load_seed(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    import app.commands.seed_demo as seed

    importlib.reload(seed)
    return main, seed


def _month_period(offset: int) -> str:
    today = date.today()
    month_index = today.year * 12 + today.month - 1 + offset
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def test_seed_demo_populates_current_product_contract(tmp_path, monkeypatch):
    main, seed = _load_seed(tmp_path, monkeypatch)
    result = asyncio.run(seed.seed_demo())
    assert result.accounts == 10
    assert result.snapshots == 309
    assert result.categories == 12
    assert result.recurring == 16
    assert result.debts == 4
    assert result.real_estate_assets == 2
    assert result.holdings == 7
    assert result.holding_operations == 12
    assert result.households == 1
    assert result.snapshot_attachments == 2
    assert result.recurring_attachments == 2
    assert result.debt_attachments == 1
    assert result.real_estate_attachments == 1
    assert result.contracts == 4
    assert result.contract_attachments == 1
    assert result.payslips == 8
    assert result.payslip_attachments == 1

    with TestClient(main.create_app()) as client:
        accounts = client.get("/api/accounts").json()
        assert len(accounts) == 9
        assert len({account["balance"] for account in accounts}) > 6
        assert next(account for account in accounts if account["name"] == "PEA demo")[
            "balance"
        ] == "2634.00"
        assert next(
            account for account in accounts if account["name"] == "Livret epargne demo"
        )["missing_snapshot_periods"] == [_month_period(-2)]
        assert next(
            account for account in accounts if account["name"] == "Wallet crypto demo"
        )["missing_snapshot_periods"] == [_month_period(-1)]
        archived_account = next(
            account
            for account in client.get("/api/accounts?include_archived=true").json()
            if account["name"] == "Compte cloture demo"
        )
        assert archived_account["missing_snapshot_periods"] == []
        institution_history = client.get("/api/accounts/institution-history").json()
        assert [
            point["balance"]
            for point in institution_history
            if point["institution"] == "Crédit Agricole"
        ] == ["900.00", "600.00", "250.00", "0.00"]

        recurring = client.get("/api/recurring").json()
        assert len(recurring) == 16
        assert any(item["amount_type"] == "variable" for item in recurring)
        assert sum(item["recurring_type"] == "salary" for item in recurring) == 1
        assert {item["frequency"] for item in recurring} == {
            "weekly",
            "monthly",
            "quarterly",
            "yearly",
        }
        salary = next(item for item in recurring if item["label"] == "Salaire mensuel")
        assert salary["amount"] == "3126.50"
        internet_series = next(
            item for item in recurring if item["label"] == "Abonnement internet"
        )
        categories = {
            item["name"]: item for item in client.get("/api/categories").json()
        }
        assert categories["Charges du logement"]["parent_id"] == categories["Logement"][
            "id"
        ]
        assert categories["Electricite"]["parent_id"] == categories[
            "Charges du logement"
        ]["id"]
        assert categories["Internet"]["parent_id"] == categories[
            "Charges du logement"
        ]["id"]
        assert internet_series["category_id"] == categories["Internet"]["id"]

        contracts = client.get("/api/work/contracts").json()
        assert len(contracts) == 4
        assert {item["contract_type"] for item in contracts} == {
            "Alternance",
            "CDD",
            "CDI",
            "Stage",
        }
        current_contract = next(item for item in contracts if item["status"] == "active")
        previous_contract = next(
            item for item in contracts if item["contract_type"] == "CDD"
        )
        apprenticeship_contract = next(
            item for item in contracts if item["contract_type"] == "Alternance"
        )
        internship_contract = next(
            item for item in contracts if item["contract_type"] == "Stage"
        )
        assert current_contract["recurring_series_id"] == salary["id"]
        assert current_contract["payment_period_months"] == 12
        assert current_contract["attachment_count"] == 1
        assert previous_contract["recurring_series_id"] is None
        assert previous_contract["attachment_count"] == 0
        assert previous_contract["end_date"] == "2021-08-31"
        assert apprenticeship_contract["position"] == "Développeur en alternance"
        assert apprenticeship_contract["status"] == "ended"
        assert internship_contract["position"] == "Stagiaire développement web"
        assert internship_contract["status"] == "ended"

        payslips = client.get("/api/work/payslips").json()
        assert len(payslips) == 8
        assert payslips[0]["period"] == "2026-09"
        assert payslips[0]["net_after_tax"] == salary["amount"]
        assert len(payslips[0]["attachments"]) == 1
        assert "2026-08" not in {
            item["period"]
            for item in payslips
            if item["contract_id"] == current_contract["id"]
        }
        assert {item["contract_id"] for item in payslips} == {
            current_contract["id"],
            previous_contract["id"],
            apprenticeship_contract["id"],
        }

        work_summary = client.get("/api/work/summary").json()
        assert work_summary["active_contracts_count"] == 1
        assert work_summary["latest_net_after_tax"] == salary["amount"]
        assert work_summary["declared_validated_quarters"] == 59
        assert work_summary["payslip_quarters"] == 11
        assert work_summary["validated_quarters"] == 70

        pension = client.get("/api/work/pension").json()
        assert pension["birth_month"] == 8
        assert pension["estimated_total_quarters"] == 70
        assert pension["quarter_calculation"] == [
            {
                "year": 2026,
                "gross_salary": "21666.65",
                "quarter_threshold": "1803.00",
                "validated_quarters": 4,
                "next_quarter_remaining": None,
            },
            {
                "year": 2021,
                "gross_salary": "3500.00",
                "quarter_threshold": "1537.50",
                "validated_quarters": 2,
                "next_quarter_remaining": "1112.50",
            },
            {
                "year": 2011,
                "gross_salary": "1800.00",
                "quarter_threshold": "1800.00",
                "validated_quarters": 1,
                "next_quarter_remaining": "1800.00",
            },
            {
                "year": 2010,
                "gross_salary": "7088.00",
                "quarter_threshold": "1772.00",
                "validated_quarters": 4,
                "next_quarter_remaining": None,
            },
        ]
        projection = pension["projection"]
        assert projection["reference_annual_gross"] == "51999.96"
        assert projection["simulated_end_annual_gross"] == "75208.71"
        assert projection["payslip_count"] == 8
        assert projection["covered_years"] == [2026, 2021, 2011, 2010]
        assert [scenario["kind"] for scenario in projection["scenarios"]] == [
            "long_career",
            "legal_age",
            "full_rate_automatic",
        ]
        assert projection["scenarios"][0]["projected_quarters"] == 177
        assert projection["long_career"] == {
            "status": "eligible",
            "cutoff_year": 2011,
            "required_early_quarters": 5,
            "entered_early_quarters": 5,
            "projected_quarters_at_63": 177,
            "required_total_quarters": 172,
        }

        documents = client.get("/api/documents").json()
        assert documents["stats"]["total_documents"] == 8
        assert documents["stats"]["missing_resources"] > 12
        assert {item["kind"] for item in documents["documents"]} == {
            "snapshot",
            "recurring",
            "debt",
            "real_estate",
            "work_contract",
            "payslip",
        }
        assert any(
            item["original_name"] == "bulletin-salaire-demo.txt"
            for item in documents["documents"]
        )
        assert any(
            item["kind"] == "work_contract"
            and item["original_name"] == "contrat-travail-demo.txt"
            and item["reference"] == "2021-09-01"
            for item in documents["documents"]
        )
        assert any(
            item["kind"] == "payslip"
            and item["original_name"] == "bulletin-paie-2026-09-demo.txt"
            and item["reference"] == "2026-09"
            for item in documents["documents"]
        )
        assert len(documents["kinds"]) == 6
        assert len(documents["ignored_resources"]) == 1
        assert documents["ignored_resources"][0]["label"] == "Budget carburant"
        assert all(
            item["label"] != "Budget carburant"
            for item in documents["resources_without_documents"]
        )

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
        monthly_source_flows = client.get(
            "/api/budget/cashflow",
            params={"by": "source", "months": 1},
        ).json()
        yearly_source_flows = client.get(
            "/api/budget/cashflow",
            params={"by": "source", "months": 12},
        ).json()
        assert sum(Decimal(flow["inflow"]) for flow in yearly_source_flows) == (
            12 * sum(Decimal(flow["inflow"]) for flow in monthly_source_flows)
        )
        assert client.get("/api/budget/spending").json()

        net_worth = client.get("/api/networth/overview").json()
        assert net_worth["net_worth"] != "0.00"
        assert client.get("/api/networth/history").json()
        holdings = client.get("/api/holdings").json()
        assert len({item["account_id"] for item in holdings}) == 3
        assert any(float(item["gain"]) > 0 for item in holdings)
        assert any(float(item["gain"]) < 0 for item in holdings)
        assert any(
            item["quantity"] == "0.0000000000" and float(item["realized_gain"]) > 0
            for item in holdings
        )
        assert any(
            item["quantity"] == "0.0000000000" and float(item["realized_gain"]) < 0
            for item in holdings
        )
        assert len({item["market_value"] for item in holdings}) > 1
        etfs = [item for item in holdings if item["name"] == "ETF Monde"]
        assert len(etfs) == 2
        assert len({item["account_id"] for item in etfs}) == 2
        etf = next(item for item in etfs if item["quantity"] == "12.0000000000")
        assert etf["quantity"] == "12.0000000000"
        assert etf["average_price"] == "85.000000"
        assert etf["operation_count"] == 4
        bitcoin = next(item for item in holdings if item["symbol"] == "BTC")
        assert bitcoin["asset_class"] == "crypto"
        assert bitcoin["quantity"] == "0.1250000001"
        assert bitcoin["operation_count"] == 1
        operations = client.get(f"/api/holdings/{etf['id']}/operations").json()
        assert len(operations) == 4
        assert {item["operation_type"] for item in operations} == {"buy", "sell"}
        all_operations = client.get("/api/holding-operations").json()
        assert len(all_operations) == 12
        assert any(
            item["operation_type"] == "sell" and float(item["realized_gain"] or 0) > 0
            for item in all_operations
        )
        assert any(
            item["operation_type"] == "sell" and float(item["realized_gain"] or 0) < 0
            for item in all_operations
        )
        assert [item["occurred_on"] for item in all_operations] == sorted(
            [item["occurred_on"] for item in all_operations],
            reverse=True,
        )
        assert {item["holding_id"] for item in all_operations}.issuperset(
            {item["id"] for item in etfs}
        )
        asset_performance = client.get("/api/holdings/performance").json()
        assert len(asset_performance) == 4
        assert [item["period"] for item in asset_performance] == sorted(
            item["period"] for item in asset_performance
        )
        assert all(float(item["market_value"]) > 0 for item in asset_performance)
        assert any(float(item["gain"]) != 0 for item in asset_performance)
        portfolio_performance = client.get("/api/portfolio/performance").json()
        assert len(portfolio_performance) == 4
        assert all(float(item["market_value"]) > 0 for item in portfolio_performance)

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

        payslip_document = next(
            document
            for document in client.get("/api/documents").json()["documents"]
            if document["kind"] == "payslip"
        )
        payslip_download = client.get(payslip_document["download_url"])
        assert payslip_download.status_code == 200
        assert b"entierement synthetique" in payslip_download.content

        contract_document = next(
            document
            for document in client.get("/api/documents").json()["documents"]
            if document["kind"] == "work_contract"
        )
        contract_download = client.get(contract_document["download_url"])
        assert contract_download.status_code == 200
        assert b"entierement synthetique" in contract_download.content


def test_seed_demo_refuses_overwrite_and_reset_reseeds(tmp_path, monkeypatch):
    _, seed = _load_seed(tmp_path, monkeypatch)
    asyncio.run(seed.seed_demo())
    old_files = {
        path for path in (tmp_path / "attached").rglob("*") if path.is_file()
    }
    assert len(old_files) == 9
    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())

    result = asyncio.run(seed.seed_demo(reset=True))
    assert result.households == 1
    new_files = {
        path for path in (tmp_path / "attached").rglob("*") if path.is_file()
    }
    assert len(new_files) == 9


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
