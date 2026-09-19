"""Household compatibility routes are scoped by the active profile session."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_household_routes_use_active_profile_not_actor_id(app_factory):
    main, _, _ = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        assert client.get("/api/households").status_code == 401
        assert client.post(
            "/api/households", json={"name": "Autre foyer", "owner_name": "Mallory"}
        ).status_code == 401

        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200

        household = client.get("/api/households").json()[0]
        household_id = household["id"]
        assert household["members"][0]["id"] == alice["id"]
        assert client.post(
            "/api/households", json={"name": "Autre foyer", "owner_name": "Mallory"}
        ).status_code == 409
        assert client.get(f"/api/households/{household_id + 100}").status_code == 404

        goal = client.post(
            f"/api/households/{household_id}/goals?actor_id=999",
            json={"name": "Vacances", "target_amount": "1000.00"},
        )
        assert goal.status_code == 201
        contribution = client.post(
            f"/api/households/{household_id}/goals/{goal.json()['id']}/contributions",
            json={"amount": "100.00", "occurred_on": "2026-09-18"},
        )
        assert contribution.status_code == 201
        assert contribution.json()["member_id"] == alice["id"]

        bob = client.post("/api/profiles/manage", json={"name": "Bob"}).json()
        charlie = client.post("/api/profiles/manage", json={"name": "Charlie"}).json()
        assert client.patch(
            f"/api/profiles/{charlie['id']}", json={"active": False}
        ).status_code == 200
        assert client.patch(
            f"/api/households/{household_id}/members/{alice['id']}",
            json={"role": "member"},
        ).status_code == 409
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        visible_member_ids = {
            member["id"] for member in client.get("/api/households").json()[0]["members"]
        }
        assert charlie["id"] not in visible_member_ids
        assert [item["id"] for item in client.get(f"/api/households/{household_id}/goals").json()] == [
            goal.json()["id"]
        ]
        assert client.post(
            f"/api/households/{household_id}/goals/{goal.json()['id']}/contributions",
            json={
                "amount": "10.00",
                "occurred_on": "2026-09-18",
                "member_id": alice["id"],
            },
        ).status_code == 403
        assert client.get(f"/api/households/{household_id}/shared-accounts").status_code == 410
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        assert client.delete(
            f"/api/households/{household_id}/members/{bob['id']}"
        ).status_code == 409
