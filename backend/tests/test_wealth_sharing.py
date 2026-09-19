"""Focused contracts for deterministic wealth ownership allocation."""

from __future__ import annotations

from decimal import Decimal
from http.cookies import SimpleCookie
from types import SimpleNamespace

import pytest
from conftest import load_app
from fastapi.testclient import TestClient

from app.routers.wealth import _equal_owner_shares, _real_estate_owner_values


@pytest.fixture
def client(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app()) as test_client:
        yield test_client


def _activate_profile(client: TestClient, profile_id: int) -> None:
    response = client.post(f"/api/profiles/{profile_id}/select", json={})
    assert response.status_code == 200
    cookie = SimpleCookie(response.headers["set-cookie"])
    client.cookies.set("moulaga_profile_session", cookie["moulaga_profile_session"].value)


def _profiles(client: TestClient) -> tuple[dict, dict, dict]:
    alice = client.post("/api/profiles", json={"name": "Alice"}).json()
    _activate_profile(client, alice["id"])
    bob = client.post("/api/profiles/manage", json={"name": "Bob"}).json()
    clara = client.post("/api/profiles/manage", json={"name": "Clara"}).json()
    return alice, bob, clara


def test_equal_owner_shares_preserve_total_and_allocate_remainder_by_profile_id():
    shares = _equal_owner_shares(Decimal("100.00"), [9, 2, 5])

    assert shares == {
        2: Decimal("33.34"),
        5: Decimal("33.33"),
        9: Decimal("33.33"),
    }
    assert sum(shares.values()) == Decimal("100.00")


def test_equal_owner_shares_handles_negative_totals_without_losing_cents():
    shares = _equal_owner_shares(Decimal("-100.00"), [3, 1, 2])

    assert shares == {
        1: Decimal("-33.34"),
        2: Decimal("-33.33"),
        3: Decimal("-33.33"),
    }
    assert sum(shares.values()) == Decimal("-100.00")


def test_equal_owner_shares_requires_unique_owners():
    with pytest.raises(ValueError, match="proprietaire"):
        _equal_owner_shares(Decimal("100.00"), [1, 1])


def test_real_estate_share_applies_external_household_share_before_profiles():
    asset = SimpleNamespace(
        purchase_price=Decimal("300000.00"),
        current_value=Decimal("360000.00"),
        ownership_share=Decimal("50.00"),
    )

    assert _real_estate_owner_values(asset, [20, 10]) == {
        10: (Decimal("75000.00"), Decimal("90000.00")),
        20: (Decimal("75000.00"), Decimal("90000.00")),
    }


def test_shared_debt_and_property_are_visible_proportionally_to_each_owner(client):
    alice, bob, _ = _profiles(client)
    debt = client.post(
        "/api/debts",
        json={
            "name": "Emprunt commun",
            "principal": "90000.00",
            "balance": "60000.00",
            "owner_profile_ids": [bob["id"], alice["id"]],
        },
    )
    assert debt.status_code == 201
    assert debt.json()["active_profile_balance"] == "30000.00"
    assert debt.json()["total_balance"] == "60000.00"
    assert [owner["id"] for owner in debt.json()["owners"]] == [alice["id"], bob["id"]]

    property_response = client.post(
        "/api/real-estate",
        json={
            "name": "Maison en indivision",
            "purchase_price": "300000.00",
            "current_value": "360000.00",
            "ownership_share": "50.00",
            "debt_ids": [debt.json()["id"]],
            "owner_profile_ids": [bob["id"], alice["id"]],
        },
    )
    assert property_response.status_code == 201
    assert property_response.json()["active_profile_owned_value"] == "90000.00"
    assert property_response.json()["total_owned_value"] == "180000.00"
    assert property_response.json()["active_profile_net_equity"] == "60000.00"
    assert property_response.json()["total_net_equity"] == "120000.00"

    _activate_profile(client, bob["id"])
    assert client.get("/api/debts").json()[0]["active_profile_balance"] == "30000.00"
    assert client.get("/api/real-estate").json()[0]["active_profile_owned_value"] == "90000.00"
    assert client.get("/api/networth/overview").json()["debts"] == "30000.00"
    assert client.get("/api/networth/overview").json()["real_estate"] == "90000.00"

    edited = client.patch(f"/api/debts/{debt.json()['id']}", json={"balance": "50000.00"})
    assert edited.status_code == 200
    assert edited.json()["active_profile_balance"] == "25000.00"
    edited_property = client.patch(
        f"/api/real-estate/{property_response.json()['id']}",
        json={"current_value": "400000.00"},
    )
    assert edited_property.status_code == 200
    assert edited_property.json()["active_profile_owned_value"] == "100000.00"


def test_non_owner_cannot_read_shared_resource_attachments(client):
    alice, _, clara = _profiles(client)
    debt = client.post(
        "/api/debts",
        json={
            "name": "Dette personnelle",
            "principal": "100.00",
            "balance": "100.00",
        },
    ).json()
    attachment = client.post(
        f"/api/debts/{debt['id']}/attachments",
        files={"file": ("preuve.txt", b"synthetique", "text/plain")},
    )
    assert attachment.status_code == 201
    asset = client.post(
        "/api/real-estate",
        json={"name": "Bien personnel", "purchase_price": "100.00"},
    ).json()
    property_attachment = client.post(
        f"/api/real-estate/{asset['id']}/attachments",
        files={"file": ("acte.txt", b"synthetique", "text/plain")},
    )
    assert property_attachment.status_code == 201

    _activate_profile(client, clara["id"])
    assert client.get(f"/api/debts/{debt['id']}/attachments").status_code == 404
    assert (
        client.get(
            f"/api/debts/{debt['id']}/attachments/{attachment.json()['id']}/download"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/real-estate/{asset['id']}/attachments/"
            f"{property_attachment.json()['id']}/download"
        ).status_code
        == 404
    )


def test_owner_can_transfer_resource_without_response_failure(client):
    alice, bob, _ = _profiles(client)
    debt = client.post(
        "/api/debts",
        json={
            "name": "Dette transferee",
            "principal": "100.00",
            "balance": "100.00",
        },
    ).json()
    asset = client.post(
        "/api/real-estate",
        json={"name": "Bien transfere", "purchase_price": "100.00"},
    ).json()

    transferred_debt = client.patch(
        f"/api/debts/{debt['id']}",
        json={"owner_profile_ids": [bob["id"]]},
    )
    assert transferred_debt.status_code == 200
    assert transferred_debt.json()["active_profile_balance"] == "0.00"
    transferred_asset = client.patch(
        f"/api/real-estate/{asset['id']}",
        json={"owner_profile_ids": [bob["id"]]},
    )
    assert transferred_asset.status_code == 200
    assert transferred_asset.json()["active_profile_owned_value"] == "0.00"

    assert client.get(f"/api/debts/{debt['id']}").status_code == 404
    assert client.get(f"/api/real-estate/{asset['id']}").status_code == 404
    _activate_profile(client, bob["id"])
    assert [item["id"] for item in client.get("/api/debts").json()] == [debt["id"]]
    assert [item["id"] for item in client.get("/api/real-estate").json()] == [asset["id"]]


def test_shared_property_hides_linked_debts_owned_by_another_profile(client):
    alice, bob, _ = _profiles(client)
    debt = client.post(
        "/api/debts",
        json={
            "name": "Dette Alice",
            "principal": "60000.00",
            "balance": "60000.00",
        },
    ).json()
    asset = client.post(
        "/api/real-estate",
        json={
            "name": "Maison partagee",
            "purchase_price": "180000.00",
            "current_value": "180000.00",
            "debt_ids": [debt["id"]],
            "owner_profile_ids": [alice["id"], bob["id"]],
        },
    ).json()

    _activate_profile(client, bob["id"])
    response = next(
        item for item in client.get("/api/real-estate").json() if item["id"] == asset["id"]
    )
    assert response["debt_ids"] == []
    assert response["debts"] == []
    assert response["debt_balance"] == "0.00"
    assert response["total_net_equity"] == "180000.00"
    assert response["active_profile_net_equity"] == "90000.00"


def test_creator_must_own_new_debt_and_property(client):
    _, bob, _ = _profiles(client)

    debt = client.post(
        "/api/debts",
        json={
            "name": "Dette hors profil",
            "principal": "100.00",
            "balance": "100.00",
            "owner_profile_ids": [bob["id"]],
        },
    )
    assert debt.status_code == 422

    asset = client.post(
        "/api/real-estate",
        json={
            "name": "Bien hors profil",
            "purchase_price": "100.00",
            "owner_profile_ids": [bob["id"]],
        },
    )
    assert asset.status_code == 422
    assert client.get("/api/debts").json() == []
    assert client.get("/api/real-estate").json() == []


def test_shared_debt_cannot_mutate_series_on_a_private_account(client):
    alice, bob, _ = _profiles(client)
    account = client.post(
        "/api/accounts",
        json={"name": "Compte prive Alice"},
    ).json()
    debt = client.post(
        "/api/debts",
        json={
            "name": "Dette partagee",
            "principal": "1000.00",
            "balance": "900.00",
            "minimum_payment": "100.00",
            "account_id": account["id"],
            "owner_profile_ids": [alice["id"], bob["id"]],
        },
    )
    assert debt.status_code == 201, debt.text

    _activate_profile(client, bob["id"])
    visible_debt = client.get("/api/debts").json()[0]
    assert visible_debt["account_id"] is None
    assert visible_debt["recurring_series_repayment_id"] is None
    assert visible_debt["recurring_series_insurance_id"] is None
    assert visible_debt["recurring_series_name_repayment"] is None
    assert visible_debt["recurring_series_name_insurance"] is None
    unlink = client.patch(
        f"/api/debts/{debt.json()['id']}",
        json={"recurring_series_repayment_id": None},
    )
    assert unlink.status_code == 404
    update = client.patch(
        f"/api/debts/{debt.json()['id']}",
        json={"minimum_payment": "80.00"},
    )
    assert update.status_code == 404


def test_shared_holding_exposes_profile_allocations_and_totals(client):
    alice, bob, _ = _profiles(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "PEA partage",
            "type": "pea",
            "owner_profile_ids": [alice["id"], bob["id"]],
        },
    ).json()
    holding = client.post(
        "/api/holdings",
        json={
            "account_id": account["id"],
            "name": "Indice synthetique",
            "quantity": "3.0000000000",
            "average_price": "100.00",
            "current_price": "120.00",
        },
    )
    assert holding.status_code == 201, holding.text
    assert holding.json()["quantity"] == "3.0000000000"
    assert holding.json()["active_profile_quantity"] == "1.5000000000"
    assert holding.json()["market_value"] == "360.00"
    assert holding.json()["active_profile_market_value"] == "180.00"
    assert holding.json()["active_profile_total_gain"] == "30.00"

    _activate_profile(client, bob["id"])
    visible = client.get("/api/holdings").json()[0]
    assert visible["active_profile_quantity"] == "1.5000000000"
    assert visible["active_profile_market_value"] == "180.00"
