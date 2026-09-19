"""Focused account ownership, visibility and recurring-share contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import load_app
from fastapi.testclient import TestClient

from app.account_access import allocate_equal_shares


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "false")
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as test_client:
        yield test_client


def _select_profile(client: TestClient, profile_id: int) -> None:
    response = client.post(f"/api/profiles/{profile_id}/select", json={})
    assert response.status_code == 200


def _create_profiles(client: TestClient) -> tuple[int, int]:
    alice = client.post("/api/profiles", json={"name": "Alice"}).json()
    _select_profile(client, alice["id"])
    bob = client.post("/api/profiles", json={"name": "Bob"}).json()
    return alice["id"], bob["id"]


def test_equal_share_allocation_assigns_residual_cents_by_profile_id():
    assert allocate_equal_shares(Decimal("100.00"), [9, 2, 5]) == {
        2: Decimal("33.34"),
        5: Decimal("33.33"),
        9: Decimal("33.33"),
    }
    assert allocate_equal_shares(Decimal("-100.00"), [9, 2, 5]) == {
        2: Decimal("-33.34"),
        5: Decimal("-33.33"),
        9: Decimal("-33.33"),
    }


def test_accounts_and_recurring_series_are_visible_and_split_by_owner(
    client: TestClient,
):
    alice_id, bob_id = _create_profiles(client)
    account = client.post(
        "/api/accounts",
        json={"name": "Compte commun partage", "initial_balance": "101.00"},
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]

    category = client.post(
        "/api/categories",
        json={"name": "Logement test", "kind": "expense", "monthly_budget": "200.00"},
    ).json()
    due = date.today().replace(day=1).isoformat()
    recurring = client.post(
        "/api/recurring",
        json={
            "label": "Loyer test",
            "account_id": account_id,
            "category_id": category["id"],
            "next_due": due,
            "amount": "-101.00",
            "recurring_type": "rent",
        },
    )
    assert recurring.status_code == 201

    _select_profile(client, bob_id)
    assert client.get("/api/accounts").json() == []
    assert client.get(f"/api/accounts/{account_id}").status_code == 404
    assert client.get("/api/recurring").json() == []
    assert client.get(f"/api/recurring/{recurring.json()['id']}/attachments").status_code == 404

    _select_profile(client, alice_id)
    ownership = client.put(
        f"/api/accounts/{account_id}/owners",
        json={"profile_ids": [bob_id, alice_id]},
    )
    assert ownership.status_code == 200
    assert ownership.json()["balance"] == "50.50"
    assert ownership.json().get("total_balance", "101.00") == "101.00"

    _select_profile(client, bob_id)
    assert client.get("/api/accounts").json()[0]["balance"] == "50.50"
    bob_recurring = client.get("/api/recurring").json()[0]
    assert bob_recurring["amount"] == "-50.50"
    assert bob_recurring["profile_share"] == "-50.50"
    assert bob_recurring["total_amount"] == "-101.00"

    edited = client.patch(
        f"/api/recurring/{bob_recurring['id']}",
        json={"amount": bob_recurring["total_amount"]},
    )
    assert edited.status_code == 200
    assert edited.json()["amount"] == "-50.50"
    assert edited.json()["profile_share"] == "-50.50"
    assert edited.json()["total_amount"] == "-101.00"
    assert client.get("/api/recurring").json()[0]["total_amount"] == "-101.00"

    assert client.get("/api/overview").json()["expenses_current_month"] == "50.50"
    envelope = next(
        item
        for item in client.get("/api/budget/envelopes").json()
        if item["category_id"] == category["id"]
    )
    assert envelope["planned"] == "101.00"


def test_account_can_be_transferred_to_another_profile(client: TestClient):
    alice_id, bob_id = _create_profiles(client)
    account = client.post(
        "/api/accounts",
        json={"name": "Compte a transferer", "initial_balance": "42.00"},
    ).json()

    transferred = client.patch(
        f"/api/accounts/{account['id']}",
        json={"owner_profile_ids": [bob_id]},
    )
    assert transferred.status_code == 200
    assert transferred.json()["profile_share"] == "0.00"
    assert transferred.json()["owner_profile_ids"] == [bob_id]
    assert client.get(f"/api/accounts/{account['id']}").status_code == 404

    _select_profile(client, bob_id)
    visible = client.get("/api/accounts").json()
    assert [item["id"] for item in visible] == [account["id"]]
    assert visible[0]["balance"] == "42.00"


def test_recurring_projection_allocates_each_base_occurrence_before_scaling(
    client: TestClient,
):
    alice_id, bob_id = _create_profiles(client)
    clara = client.post("/api/profiles", json={"name": "Clara"}).json()
    account = client.post(
        "/api/accounts",
        json={
            "name": "Compte arrondi",
            "owner_profile_ids": [alice_id, bob_id, clara["id"]],
        },
    ).json()
    recurring = client.post(
        "/api/recurring",
        json={
            "label": "Revenu avec centime residuel",
            "account_id": account["id"],
            "frequency": "monthly",
            "next_due": date.today().replace(day=1).isoformat(),
            "amount": "100.00",
            "recurring_type": "salary",
        },
    )
    assert recurring.status_code == 201, recurring.text

    cashflow = client.get("/api/budget/cashflow?months=12&by=source")
    assert cashflow.status_code == 200, cashflow.text
    assert cashflow.json() == [
        {
            "key": f"account:{account['id']}",
            "label": "Compte arrondi",
            "inflow": "400.08",
            "outflow": "0.00",
            "net": "400.08",
        }
    ]
