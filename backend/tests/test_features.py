"""Feature contracts for statements, recurring budgets, wealth and households."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import load_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as test_client:
        yield test_client


def _account_id(client: TestClient) -> int:
    return client.get("/api/accounts").json()[0]["id"]


def _category(client: TestClient, name: str) -> dict:
    return next(item for item in client.get("/api/categories").json() if item["name"] == name)


def _month_period(offset: int) -> str:
    today = date.today()
    month_index = today.year * 12 + today.month - 1 + offset
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def test_preferences_patch_validates_and_persists(client):
    response = client.patch(
        "/api/preferences",
        json={"theme": "dark", "budget_cycle_start_day": 15},
    )
    assert response.status_code == 200
    assert response.json()["theme"] == "dark"
    assert response.json()["budget_cycle_start_day"] == 15
    assert client.patch(
        "/api/preferences",
        json={"budget_cycle_start_day": 31},
    ).status_code == 422


def test_statements_are_authoritative_for_accounts_and_net_worth(client):
    account_id = _account_id(client)
    assert client.get(f"/api/accounts/{account_id}").json()["balance"] == "0.00"

    statement = client.put(
        f"/api/accounts/{account_id}/snapshots",
        json={"period": date.today().strftime("%Y-%m"), "balance": "325.50"},
    )
    assert statement.status_code == 200
    assert client.get(f"/api/accounts/{account_id}").json()["balance"] == "325.50"
    assert client.get("/api/overview").json()["balance"] == "325.50"
    assert client.get("/api/networth/overview").json()["cash"] == "325.50"

    updated = client.patch(
        f"/api/accounts/{account_id}",
        json={"balance": "350.00"},
    )
    assert updated.status_code == 200
    assert updated.json()["balance"] == "350.00"
    snapshots = client.get(f"/api/accounts/{account_id}/snapshots").json()
    assert len(snapshots) == 1
    assert snapshots[0]["balance"] == "350.00"


def test_active_accounts_report_internal_and_recent_missing_statements(client):
    account_id = _account_id(client)
    for offset, balance in ((-4, "100.00"), (-2, "120.00"), (0, "140.00")):
        response = client.put(
            f"/api/accounts/{account_id}/snapshots",
            json={"period": _month_period(offset), "balance": balance},
        )
        assert response.status_code == 200

    expected = [_month_period(-3), _month_period(-1)]
    detail = client.get(f"/api/accounts/{account_id}").json()
    assert detail["missing_snapshot_periods"] == expected
    listed = client.get("/api/accounts").json()
    assert next(item for item in listed if item["id"] == account_id)[
        "missing_snapshot_periods"
    ] == expected

    archived = client.post(
        "/api/accounts",
        json={"name": "Compte archive avec trous", "initial_balance": "50.00"},
    ).json()
    for offset in (-4, 0):
        assert client.put(
            f"/api/accounts/{archived['id']}/snapshots",
            json={"period": _month_period(offset), "balance": "50.00"},
        ).status_code == 200
    assert client.post(f"/api/accounts/{archived['id']}/archive").status_code == 200
    assert client.get(f"/api/accounts/{archived['id']}").json()[
        "missing_snapshot_periods"
    ] == []
    archived_list = client.get("/api/accounts?include_archived=true").json()
    assert next(item for item in archived_list if item["id"] == archived["id"])[
        "missing_snapshot_periods"
    ] == []


def test_institution_history_keeps_archived_accounts_in_totals(client):
    active = client.post(
        "/api/accounts",
        json={
            "name": "Livret actif",
            "type": "savings",
            "institution": "Banque Test",
        },
    ).json()
    archived = client.post(
        "/api/accounts",
        json={
            "name": "Livret archive",
            "type": "savings",
            "institution": "Banque Test",
        },
    ).json()
    for account_id, snapshots in (
        (active["id"], (("2026-01", "100.00"), ("2026-03", "120.00"))),
        (archived["id"], (("2026-01", "50.00"), ("2026-02", "40.00"))),
    ):
        for period, balance in snapshots:
            response = client.put(
                f"/api/accounts/{account_id}/snapshots",
                json={"period": period, "balance": balance},
            )
            assert response.status_code == 200

    assert client.post(f"/api/accounts/{archived['id']}/archive").status_code == 200

    history = client.get(
        "/api/accounts/institution-history",
        params={"account_type": "savings"},
    )
    assert history.status_code == 200
    assert history.json() == [
        {"period": "2026-01", "institution": "Banque Test", "balance": "150.00"},
        {"period": "2026-02", "institution": "Banque Test", "balance": "140.00"},
        {"period": "2026-03", "institution": "Banque Test", "balance": "160.00"},
    ]


def test_document_center_indexes_missing_resources_and_uploaded_files(client):
    account_id = _account_id(client)
    statement = client.put(
        f"/api/accounts/{account_id}/snapshots",
        json={"period": "2026-08", "balance": "325.50"},
    ).json()

    initial = client.get("/api/documents")
    assert initial.status_code == 200
    assert initial.json()["stats"] == {
        "total_documents": 0,
        "total_size": 0,
        "total_resources": 1,
        "covered_resources": 0,
        "missing_resources": 1,
    }
    assert initial.json()["resources_without_documents"][0] == {
        "kind": "snapshot",
        "resource_id": statement["id"],
        "account_id": account_id,
        "label": "Compte courant",
        "context": "Relevé de compte",
        "reference": "2026-08",
        "can_upload": True,
    }
    assert initial.json()["ignored_resources"] == []

    ignored = client.post(
        f"/api/documents/resources/snapshot/{statement['id']}/ignored"
    )
    assert ignored.status_code == 204
    ignored_center = client.get("/api/documents").json()
    assert ignored_center["stats"]["missing_resources"] == 0
    assert ignored_center["resources_without_documents"] == []
    assert ignored_center["ignored_resources"] == [
        initial.json()["resources_without_documents"][0]
    ]

    restored = client.post(
        f"/api/documents/resources/snapshot/{statement['id']}/ignored",
        params={"ignored": False},
    )
    assert restored.status_code == 204
    restored_center = client.get("/api/documents").json()
    assert restored_center["stats"]["missing_resources"] == 1
    assert restored_center["ignored_resources"] == []

    upload = client.post(
        f"/api/accounts/{account_id}/snapshots/{statement['id']}/attachments",
        files={
            "file": (
                "releve-synthetique.txt",
                b"Releve bancaire entierement synthetique.",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 201

    indexed = client.get("/api/documents").json()
    assert indexed["stats"]["covered_resources"] == 1
    assert indexed["stats"]["missing_resources"] == 0
    assert indexed["resources_without_documents"] == []
    assert indexed["documents"][0]["original_name"] == "releve-synthetique.txt"
    assert indexed["documents"][0]["download_url"].endswith(
        f"/attachments/{upload.json()['id']}/download"
    )
    assert client.get(indexed["documents"][0]["download_url"]).status_code == 200
    cannot_ignore = client.post(
        f"/api/documents/resources/snapshot/{statement['id']}/ignored"
    )
    assert cannot_ignore.status_code == 409


def test_statement_import_is_atomic_and_upserts(client):
    account_id = _account_id(client)
    response = client.post(
        f"/api/accounts/{account_id}/snapshots/import",
        json={
            "content": (
                "\ufeffDate\tMontant\r\n"
                "31/01/2026\t1\u202f234,56 €\r\n"
                "28/02/2026\t-42.5€"
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["created_count"] == 2
    assert [
        (item["period"], item["balance"])
        for item in response.json()["snapshots"]
    ] == [("2026-01", "1234.56"), ("2026-02", "-42.50")]

    invalid = client.post(
        f"/api/accounts/{account_id}/snapshots/import",
        json={"content": "31/03/2026\t300,00\n31/03/2026\t310,00"},
    )
    assert invalid.status_code == 422
    assert len(client.get(f"/api/accounts/{account_id}/snapshots").json()) == 2


def test_recurring_budget_drives_overview_monthly_stats_and_cashflow(client):
    account_id = _account_id(client)
    income_category = _category(client, "Salaire")
    expense_category = _category(client, "Courses")
    client.patch(
        f"/api/categories/{expense_category['id']}/budget",
        json={"monthly_budget": "500.00"},
    )
    today = date.today()
    for label, amount, category_id, recurring_type in (
        ("Salaire prévu", "2400.00", income_category["id"], "salary"),
        ("Courses prévues", "-350.00", expense_category["id"], "other"),
        ("Virement interne", "-900.00", None, "transfer"),
    ):
        payload = {
            "label": label,
            "account_id": account_id,
            "category_id": category_id,
            "frequency": "monthly",
            "next_due": today.isoformat(),
            "amount": amount,
            "recurring_type": recurring_type,
        }
        if recurring_type == "other":
            payload["custom_type"] = "Courses"
        assert client.post("/api/recurring", json=payload).status_code == 201

    overview = client.get("/api/overview").json()
    assert overview["income_current_month"] == "2400.00"
    assert overview["expenses_current_month"] == "350.00"
    assert overview["net_current_month"] == "2050.00"
    assert overview["budget_remaining"] == "150.00"

    points = client.get("/api/stats/monthly").json()
    assert len(points) == 12
    assert points[0]["income"] == "2400.00"
    assert points[0]["expenses"] == "350.00"

    source_flows = client.get("/api/budget/cashflow", params={"by": "source"}).json()
    category_flows = client.get(
        "/api/budget/cashflow",
        params={"by": "category"},
    ).json()
    assert source_flows == [
        {
            "key": f"account:{account_id}",
            "label": "Compte courant",
            "inflow": "2400.00",
            "outflow": "350.00",
            "net": "2050.00",
        }
    ]
    assert {flow["label"] for flow in category_flows} == {"Courses", "Salaire"}
    assert all(flow["label"] != "Sans categorie" for flow in category_flows)


def test_cashflow_projection_normalizes_recurring_frequencies(client):
    account_id = _account_id(client)
    income_category = _category(client, "Salaire")
    expense_category = _category(client, "Courses")
    next_due = (date.today() + timedelta(days=366)).isoformat()
    for label, amount, frequency, category_id in (
        ("Mission hebdomadaire", "100.00", "weekly", income_category["id"]),
        ("Prime trimestrielle", "300.00", "quarterly", income_category["id"]),
        ("Abonnement mensuel", "-90.00", "monthly", expense_category["id"]),
        ("Assurance annuelle", "-100.00", "yearly", expense_category["id"]),
    ):
        response = client.post(
            "/api/recurring",
            json={
                "label": label,
                "account_id": account_id,
                "category_id": category_id,
                "frequency": frequency,
                "next_due": next_due,
                "amount": amount,
            },
        )
        assert response.status_code == 201

    expected = {
        1: ("500.00", "98.33"),
        3: ("1500.00", "295.00"),
        6: ("3000.00", "590.00"),
        12: ("6000.00", "1180.00"),
    }
    for months, (inflow, outflow) in expected.items():
        response = client.get(
            "/api/budget/cashflow",
            params={"by": "source", "months": months},
        )
        assert response.status_code == 200
        assert response.json() == [
            {
                "key": f"account:{account_id}",
                "label": "Compte courant",
                "inflow": inflow,
                "outflow": outflow,
                "net": f"{Decimal(inflow) - Decimal(outflow):.2f}",
            }
        ]

    assert client.get("/api/budget/cashflow", params={"months": 2}).status_code == 422


def test_budget_cycle_and_envelopes_use_recurring_occurrences(client):
    account_id = _account_id(client)
    parent = _category(client, "Logement")
    child = client.post(
        "/api/categories",
        json={
            "name": "Electricite",
            "kind": "expense",
            "parent_id": parent["id"],
            "monthly_budget": "120.00",
        },
    ).json()
    client.patch(
        f"/api/categories/{parent['id']}",
        json={"monthly_budget": "500.00"},
    )
    for label, amount, category_id in (
        ("Loyer", "-300.00", parent["id"]),
        ("Electricité", "-120.00", child["id"]),
    ):
        assert client.post(
            "/api/recurring",
            json={
                "label": label,
                "account_id": account_id,
                "category_id": category_id,
                "frequency": "monthly",
                "next_due": date.today().isoformat(),
                "amount": amount,
            },
        ).status_code == 201

    envelopes = client.get("/api/budget/envelopes").json()
    logement = next(item for item in envelopes if item["category_id"] == parent["id"])
    electricite = next(item for item in envelopes if item["category_id"] == child["id"])
    assert logement["direct_planned"] == "300.00"
    assert logement["planned"] == "420.00"
    assert logement["available"] == "80.00"
    assert electricite["planned"] == "120.00"

    spending = client.get("/api/budget/spending").json()
    logement_node = next(item for item in spending if item["category_id"] == parent["id"])
    assert logement_node["amount"] == "420.00"
    assert logement_node["occurrence_count"] == 2


def test_recurring_series_crud_forecast_and_archived_guard(client):
    account_id = _account_id(client)
    category_id = _category(client, "Logement")["id"]
    first_due = date.today() + timedelta(days=5)
    created = client.post(
        "/api/recurring",
        json={
            "label": "Loyer",
            "account_id": account_id,
            "category_id": category_id,
            "frequency": "monthly",
            "next_due": first_due.isoformat(),
            "amount": "-750.00",
            "recurring_type": "rent",
        },
    )
    assert created.status_code == 201
    series = created.json()
    assert series["account_name"] == "Compte courant"
    assert series["category_name"] == "Logement"

    forecast = client.get("/api/recurring/forecast", params={"months": 2}).json()
    assert forecast
    assert all(item["series_id"] == series["id"] for item in forecast)

    updated = client.patch(
        f"/api/recurring/{series['id']}",
        json={"amount": "-780.00", "amount_type": "variable"},
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == "-780.00"

    assert client.post(f"/api/accounts/{account_id}/archive").status_code == 200
    assert client.patch(
        f"/api/recurring/{series['id']}",
        json={"status": "paused"},
    ).status_code == 409


def test_account_archive_transfers_statement_balance(client):
    source = client.post(
        "/api/accounts",
        json={"name": "Compte source", "initial_balance": "100.00"},
    ).json()
    destination = client.post(
        "/api/accounts",
        json={"name": "Compte destination", "initial_balance": "25.00"},
    ).json()
    archived = client.post(
        f"/api/accounts/{source['id']}/archive",
        params={"transfer_to_account_id": destination["id"]},
    )
    assert archived.status_code == 200
    assert client.get(f"/api/accounts/{source['id']}").json()["balance"] == "0.00"
    assert client.get(f"/api/accounts/{destination['id']}").json()["balance"] == "125.00"
    assert client.get(f"/api/accounts/{source['id']}/snapshots").json()[-1]["balance"] == "0.00"
    assert (
        client.get(f"/api/accounts/{destination['id']}/snapshots").json()[-1]["balance"]
        == "125.00"
    )


def test_snapshot_and_recurring_attachments_use_hashed_paths(client, tmp_path):
    account_id = _account_id(client)
    snapshot = client.put(
        f"/api/accounts/{account_id}/snapshots",
        json={"period": "2026-09", "balance": "123.45"},
    ).json()
    uploaded = client.post(
        f"/api/accounts/{account_id}/snapshots/{snapshot['id']}/attachments",
        files={"file": ("../../releve septembre.pdf", b"releve synthetique", "application/pdf")},
    )
    assert uploaded.status_code == 201
    snapshot_path = tmp_path / uploaded.json()["storage_path"].lstrip("/")
    assert snapshot_path.is_file()

    recurring = client.post(
        "/api/recurring",
        json={
            "label": "Assurance",
            "account_id": account_id,
            "frequency": "yearly",
            "next_due": "2027-01-15",
            "amount": "-120.00",
        },
    ).json()
    recurring_attachment = client.post(
        f"/api/recurring/{recurring['id']}/attachments",
        files={"file": ("contrat.txt", b"contrat synthetique", "text/plain")},
    )
    assert recurring_attachment.status_code == 201
    recurring_path = tmp_path / recurring_attachment.json()["storage_path"].lstrip("/")
    assert recurring_path.is_file()
    assert client.delete(f"/api/recurring/{recurring['id']}").status_code == 204
    assert not recurring_path.exists()


def test_portfolio_and_net_worth_do_not_double_count_investment_accounts(client):
    cash_account = _account_id(client)
    client.put(
        f"/api/accounts/{cash_account}/snapshots",
        json={"period": date.today().strftime("%Y-%m"), "balance": "500.00"},
    )
    investment = client.post(
        "/api/accounts",
        json={"name": "PEA", "type": "pea", "initial_balance": "1000.00"},
    ).json()
    holding = client.post(
        "/api/holdings",
        json={
            "account_id": investment["id"],
            "name": "ETF Monde",
            "asset_class": "equity",
            "quantity": "10",
            "average_price": "80",
            "current_price": "100",
        },
    ).json()
    assert holding["market_value"] == "1000.00"
    net_worth = client.get("/api/networth/overview").json()
    assert net_worth["cash"] == "500.00"
    assert net_worth["investments"] == "1000.00"
    assert net_worth["net_worth"] == "1500.00"


def test_holding_performance_uses_operations_without_portfolio_snapshots(client):
    investment = client.post(
        "/api/accounts",
        json={"name": "PEA performance", "type": "pea", "initial_balance": "0.00"},
    ).json()
    purchase = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": investment["id"],
                "name": "ETF Performance",
                "symbol": "PERF",
                "asset_class": "equity",
            },
            "operation_type": "buy",
            "quantity": "10",
            "unit_price": "80.00",
            "occurred_on": "2024-01-10",
        },
    ).json()
    holding_id = purchase["holding"]["id"]
    client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding_id,
            "operation_type": "buy",
            "quantity": "5",
            "unit_price": "110.00",
            "occurred_on": "2024-03-10",
        },
    )
    client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding_id,
            "operation_type": "sell",
            "quantity": "5",
            "unit_price": "130.00",
            "occurred_on": "2024-04-10",
        },
    )
    client.patch(f"/api/holdings/{holding_id}", json={"current_price": "120.00"})

    performance = client.get("/api/holdings/performance")
    assert performance.status_code == 200
    points = performance.json()
    assert [point["period"] for point in points] == sorted(
        point["period"] for point in points
    )
    assert points[0] == {
        "period": "2024-01",
        "market_value": "800.00",
        "cost_basis": "800.00",
        "unrealized_cost_basis": "800.00",
        "realized_cost_basis": "0.00",
        "total_cost_basis": "800.00",
        "unrealized_gain": "0.00",
        "realized_gain": "0.00",
        "total_gain": "0.00",
        "gain": "0.00",
    }
    assert points[1] == {
        "period": "2024-03",
        "market_value": "1650.00",
        "cost_basis": "1350.00",
        "unrealized_cost_basis": "1350.00",
        "realized_cost_basis": "0.00",
        "total_cost_basis": "1350.00",
        "unrealized_gain": "300.00",
        "realized_gain": "0.00",
        "total_gain": "300.00",
        "gain": "300.00",
    }
    assert points[2] == {
        "period": "2024-04",
        "market_value": "1300.00",
        "cost_basis": "1350.00",
        "unrealized_cost_basis": "900.00",
        "realized_cost_basis": "450.00",
        "total_cost_basis": "1350.00",
        "unrealized_gain": "400.00",
        "realized_gain": "200.00",
        "total_gain": "600.00",
        "gain": "600.00",
    }
    assert points[-1]["market_value"] == "1200.00"
    assert points[-1]["cost_basis"] == "1350.00"
    assert points[-1]["unrealized_cost_basis"] == "900.00"
    assert points[-1]["realized_cost_basis"] == "450.00"
    assert points[-1]["unrealized_gain"] == "300.00"
    assert points[-1]["realized_gain"] == "200.00"
    assert points[-1]["total_gain"] == "500.00"
    assert points[-1]["gain"] == "500.00"

    portfolio_performance = client.get("/api/portfolio/performance").json()
    assert portfolio_performance[-1]["market_value"] == "1200.00"
    assert portfolio_performance[-1]["cost_basis"] == "1350.00"
    assert portfolio_performance[-1]["realized_gain"] == "200.00"
    assert portfolio_performance[-1]["unrealized_gain"] == "300.00"
    assert portfolio_performance[-1]["total_gain"] == "500.00"


def test_holding_operations_create_and_update_positions(client):
    investment = client.post(
        "/api/accounts",
        json={"name": "PEA operations", "type": "pea", "initial_balance": "0.00"},
    ).json()
    first_purchase = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": investment["id"],
                "name": "ETF Synthétique",
                "symbol": "TEST",
                "asset_class": "equity",
            },
            "operation_type": "buy",
            "quantity": "10",
            "unit_price": "80.00",
            "occurred_on": "2026-01-10",
        },
    )
    assert first_purchase.status_code == 201
    holding = first_purchase.json()["holding"]
    assert holding["quantity"] == "10.0000000000"
    assert holding["average_price"] == "80.000000"
    assert holding["current_price"] == "80.000000"
    assert holding["operation_count"] == 1
    assert first_purchase.json()["operation"]["quantity_delta"] == "10.0000000000"
    assert first_purchase.json()["operation"]["cash_flow"] == "-800.00"
    assert first_purchase.json()["operation"]["occurred_on"] == "2026-01-10"

    second_purchase = client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding["id"],
            "operation_type": "buy",
            "quantity": "5",
            "unit_price": "110.00",
            "occurred_on": "2026-03-10",
        },
    )
    assert second_purchase.status_code == 201
    holding = second_purchase.json()["holding"]
    assert holding["quantity"] == "15.0000000000"
    assert holding["average_price"] == "90.000000"
    assert holding["operation_count"] == 2

    sale = client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding["id"],
            "operation_type": "sell",
            "quantity": "4",
            "unit_price": "120.00",
            "occurred_on": "2026-04-10",
        },
    )
    assert sale.status_code == 201
    assert sale.json()["holding"]["quantity"] == "11.0000000000"
    assert sale.json()["holding"]["average_price"] == "90.000000"
    assert sale.json()["holding"]["realized_gain"] == "120.00"
    assert sale.json()["holding"]["unrealized_gain"] == "-110.00"
    assert sale.json()["holding"]["total_gain"] == "10.00"
    assert sale.json()["operation"]["quantity_delta"] == "-4.0000000000"
    assert sale.json()["operation"]["cash_flow"] == "480.00"
    assert sale.json()["operation"]["realized_cost_basis"] == "360.00"
    assert sale.json()["operation"]["realized_gain"] == "120.00"

    excessive_sale = client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding["id"],
            "operation_type": "sell",
            "quantity": "12",
            "unit_price": "120.00",
        },
    )
    assert excessive_sale.status_code == 422
    refreshed = next(
        item for item in client.get("/api/holdings").json()
        if item["id"] == holding["id"]
    )
    assert refreshed["quantity"] == "11.0000000000"
    assert refreshed["operation_count"] == 3

    operations = client.get(f"/api/holdings/{holding['id']}/operations").json()
    assert len(operations) == 3
    assert [item["operation_type"] for item in operations] == ["sell", "buy", "buy"]
    all_operations = client.get("/api/holding-operations")
    assert all_operations.status_code == 200
    assert [item["id"] for item in all_operations.json()] == [
        item["id"] for item in operations
    ]

    second_purchase_operation = operations[1]
    edited = client.patch(
        f"/api/holdings/{holding['id']}/operations/{second_purchase_operation['id']}",
        json={
            "operation_type": "sell",
            "quantity": "3",
            "unit_price": "115.00",
            "occurred_on": "2026-02-10",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["operation"]["operation_type"] == "sell"
    assert edited.json()["operation"]["cash_flow"] == "345.00"
    assert edited.json()["operation"]["occurred_on"] == "2026-02-10"
    assert edited.json()["operation"]["realized_cost_basis"] == "240.00"
    assert edited.json()["operation"]["realized_gain"] == "105.00"
    assert edited.json()["holding"]["quantity"] == "3.0000000000"
    assert edited.json()["holding"]["average_price"] == "80.000000"
    assert edited.json()["holding"]["realized_gain"] == "265.00"
    assert edited.json()["holding"]["total_gain"] == "265.00"

    initial_purchase_operation = operations[2]
    invalid_edit = client.patch(
        f"/api/holdings/{holding['id']}/operations/{initial_purchase_operation['id']}",
        json={
            "operation_type": "sell",
            "quantity": "1",
            "unit_price": "80.00",
        },
    )
    assert invalid_edit.status_code == 422
    unchanged = next(
        item for item in client.get("/api/holdings").json()
        if item["id"] == holding["id"]
    )
    assert unchanged["quantity"] == "3.0000000000"
    assert unchanged["average_price"] == "80.000000"

    deleted = client.delete(
        f"/api/holdings/{holding['id']}/operations/{sale.json()['operation']['id']}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["quantity"] == "7.0000000000"
    assert deleted.json()["average_price"] == "80.000000"
    assert deleted.json()["operation_count"] == 2
    invalid_delete = client.delete(
        f"/api/holdings/{holding['id']}/operations/{initial_purchase_operation['id']}"
    )
    assert invalid_delete.status_code == 422

    invalid_backdated_sale = client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding["id"],
            "operation_type": "sell",
            "quantity": "1",
            "unit_price": "90.00",
            "occurred_on": "2026-01-01",
        },
    )
    assert invalid_backdated_sale.status_code == 422


def test_closed_holding_keeps_realized_gain_and_stays_out_of_allocation(client):
    investment = client.post(
        "/api/accounts",
        json={"name": "PEA closed", "type": "pea", "initial_balance": "0.00"},
    ).json()
    purchase = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": investment["id"],
                "name": "Action cédée",
                "symbol": "CLOSE",
                "asset_class": "equity",
            },
            "operation_type": "buy",
            "quantity": "2",
            "unit_price": "50.00",
            "occurred_on": "2026-01-10",
        },
    ).json()
    holding_id = purchase["holding"]["id"]
    sale = client.post(
        "/api/holding-operations",
        json={
            "holding_id": holding_id,
            "operation_type": "sell",
            "quantity": "2",
            "unit_price": "70.00",
            "occurred_on": "2026-02-10",
        },
    )
    assert sale.status_code == 201
    closed = next(item for item in client.get("/api/holdings").json() if item["id"] == holding_id)
    assert closed["quantity"] == "0.0000000000"
    assert closed["market_value"] == "0.00"
    assert closed["cost_basis"] == "0.00"
    assert closed["unrealized_gain"] == "0.00"
    assert closed["realized_gain"] == "40.00"
    assert closed["total_gain"] == "40.00"
    assert closed["gain"] == "40.00"

    operations = client.get(f"/api/holdings/{holding_id}/operations").json()
    assert operations[0]["operation_type"] == "sell"
    assert operations[0]["realized_cost_basis"] == "100.00"
    assert operations[0]["realized_gain"] == "40.00"

    summary = client.get("/api/portfolio/summary").json()
    assert summary["market_value"] == "0.00"
    assert summary["realized_gain"] == "40.00"
    assert summary["unrealized_gain"] == "0.00"
    assert summary["total_gain"] == "40.00"

    allocation = client.get("/api/portfolio/allocation").json()
    assert allocation == []


def test_crypto_operations_support_ten_decimal_quantity(client):
    wallet = client.post(
        "/api/accounts",
        json={"name": "Wallet crypto", "type": "wallet", "initial_balance": "0.00"},
    ).json()
    purchase = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": wallet["id"],
                "name": "Bitcoin",
                "symbol": "BTC",
                "asset_class": "crypto",
            },
            "operation_type": "buy",
            "quantity": "0.0000000001",
            "unit_price": "50000.00",
        },
    )

    assert purchase.status_code == 201
    assert purchase.json()["holding"]["quantity"] == "0.0000000001"
    assert purchase.json()["operation"]["quantity"] == "0.0000000001"
    assert purchase.json()["operation"]["quantity_delta"] == "0.0000000001"

    below_minimum = client.post(
        "/api/holding-operations",
        json={
            "holding_id": purchase.json()["holding"]["id"],
            "operation_type": "buy",
            "quantity": "0.00000000001",
            "unit_price": "50000.00",
        },
    )
    assert below_minimum.status_code == 422


def test_holding_edit_only_updates_metadata_and_current_price(client):
    investment = client.post(
        "/api/accounts",
        json={"name": "CTO operations", "type": "securities", "initial_balance": "0.00"},
    ).json()
    created = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": investment["id"],
                "name": "Ancien nom",
                "symbol": "OLD",
            },
            "operation_type": "buy",
            "quantity": "2",
            "unit_price": "50.00",
        },
    ).json()["holding"]
    updated = client.patch(
        f"/api/holdings/{created['id']}",
        json={"name": "Nouveau nom", "symbol": "NEW", "current_price": "75.00"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Nouveau nom"
    assert updated.json()["symbol"] == "NEW"
    assert updated.json()["current_price"] == "75.000000"
    assert updated.json()["quantity"] == "2.0000000000"
    forbidden_position_edit = client.patch(
        f"/api/holdings/{created['id']}",
        json={"quantity": "99"},
    )
    assert forbidden_position_edit.status_code == 200
    assert forbidden_position_edit.json()["quantity"] == "2.0000000000"


def test_holding_and_operations_can_move_between_accounts(client):
    first_account = client.post(
        "/api/accounts",
        json={"name": "PEA source", "type": "pea", "initial_balance": "0.00"},
    ).json()
    second_account = client.post(
        "/api/accounts",
        json={"name": "CTO cible", "type": "securities", "initial_balance": "0.00"},
    ).json()
    moved_holding = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": first_account["id"],
                "name": "Action mobile",
                "symbol": "MOVE",
            },
            "operation_type": "buy",
            "quantity": "2",
            "unit_price": "25.00",
        },
    ).json()["holding"]
    moved = client.patch(
        f"/api/holdings/{moved_holding['id']}",
        json={"account_id": second_account["id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["account_id"] == second_account["id"]

    initial = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": first_account["id"],
                "name": "ETF partagé",
                "symbol": "SHARED",
            },
            "operation_type": "buy",
            "quantity": "10",
            "unit_price": "80.00",
        },
    ).json()
    second_purchase = client.post(
        "/api/holding-operations",
        json={
            "holding_id": initial["holding"]["id"],
            "target_account_id": second_account["id"],
            "operation_type": "buy",
            "quantity": "5",
            "unit_price": "100.00",
        },
    )
    assert second_purchase.status_code == 201
    second_holding = second_purchase.json()["holding"]
    assert second_holding["account_id"] == second_account["id"]
    assert second_holding["quantity"] == "5.0000000000"
    shared_holdings = [
        item for item in client.get("/api/holdings").json()
        if item["symbol"] == "SHARED"
    ]
    assert len(shared_holdings) == 2
    assert {item["account_id"] for item in shared_holdings} == {
        first_account["id"],
        second_account["id"],
    }

    operation = client.get(
        f"/api/holdings/{initial['holding']['id']}/operations"
    ).json()[0]
    moved_operation = client.patch(
        f"/api/holdings/{initial['holding']['id']}/operations/{operation['id']}",
        json={
            "target_account_id": second_account["id"],
            "operation_type": "buy",
            "quantity": "10",
            "unit_price": "80.00",
        },
    )
    assert moved_operation.status_code == 200
    assert moved_operation.json()["holding"]["id"] == second_holding["id"]
    assert moved_operation.json()["holding"]["quantity"] == "15.0000000000"
    assert moved_operation.json()["holding"]["average_price"] == "86.666667"
    source_holding = next(
        item for item in client.get("/api/holdings").json()
        if item["id"] == initial["holding"]["id"]
    )
    assert source_holding["quantity"] == "0.0000000000"
    assert source_holding["operation_count"] == 0

    third_account = client.post(
        "/api/accounts",
        json={"name": "PEA secondaire", "type": "pea", "initial_balance": "0.00"},
    ).json()
    third_holding = client.post(
        "/api/holding-operations",
        json={
            "new_holding": {
                "account_id": third_account["id"],
                "name": "ETF partagé",
                "symbol": "SHARED",
            },
            "operation_type": "buy",
            "quantity": "3",
            "unit_price": "90.00",
        },
    ).json()["holding"]
    merged = client.patch(
        f"/api/holdings/{third_holding['id']}",
        json={"account_id": second_account["id"]},
    )
    assert merged.status_code == 200
    assert merged.json()["id"] == second_holding["id"]
    assert merged.json()["quantity"] == "18.0000000000"
    assert merged.json()["average_price"] == "87.222222"
    shared_holdings = [
        item for item in client.get("/api/holdings").json()
        if item["symbol"] == "SHARED"
    ]
    assert {item["account_id"] for item in shared_holdings} == {
        first_account["id"],
        second_account["id"],
    }


def test_household_roles_shared_balance_and_goals(client):
    account_id = _account_id(client)
    client.put(
        f"/api/accounts/{account_id}/snapshots",
        json={"period": date.today().strftime("%Y-%m"), "balance": "500.00"},
    )
    household = client.post(
        "/api/households",
        json={"name": "Foyer", "owner_name": "Profil principal"},
    ).json()
    owner_id = household["members"][0]["id"]
    shared = client.post(
        f"/api/households/{household['id']}/shared-accounts",
        params={"actor_id": owner_id},
        json={"account_id": account_id, "permission": "edit"},
    )
    assert shared.status_code == 201
    assert shared.json()["balance"] == "500.00"

    goal = client.post(
        f"/api/households/{household['id']}/goals",
        params={"actor_id": owner_id},
        json={"name": "Fonds", "target_amount": "1000.00"},
    ).json()
    contribution = client.post(
        f"/api/households/{household['id']}/goals/{goal['id']}/contributions",
        params={"actor_id": owner_id},
        json={"amount": "250.00", "occurred_on": "2026-01-10", "member_id": owner_id},
    )
    assert contribution.status_code == 201
    assert contribution.json()["member_name"] == "Profil principal"
    assert client.get(f"/api/households/{household['id']}/goals").json()[0][
        "current_amount"
    ] == "250.00"


def test_removed_operation_features_are_not_exposed(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert not any("transaction" in path for path in paths)
    assert not any("categorization" in path for path in paths)
    assert not any(path.startswith("/api/rules") for path in paths)
    assert not any(path.startswith("/api/merchants") for path in paths)
    assert "/api/recurring/detect" not in paths
    assert "/api/recurring/changes" not in paths
