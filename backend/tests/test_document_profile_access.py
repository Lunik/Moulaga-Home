"""Document-center visibility follows the active profile's resource ownership."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_document_center_hides_other_profiles_resources(app_factory):
    main, _, _ = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        alice_account = client.get("/api/accounts").json()[0]
        alice_snapshot = client.put(
            f"/api/accounts/{alice_account['id']}/snapshots",
            json={"period": "2026-01", "balance": "100.00"},
        ).json()

        bob = client.post("/api/profiles", json={"name": "Bob"}).json()
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        bob_account = client.post("/api/accounts", json={"name": "Compte Bob"}).json()
        bob_snapshot = client.put(
            f"/api/accounts/{bob_account['id']}/snapshots",
            json={"period": "2026-01", "balance": "50.00"},
        ).json()

        bob_documents = client.get("/api/documents")
        assert bob_documents.status_code == 200, bob_documents.text
        bob_resources = bob_documents.json()["resources_without_documents"]
        assert {
            resource["resource_id"]
            for resource in bob_resources
            if resource["kind"] == "snapshot"
        } == {bob_snapshot["id"]}
        assert client.post(
            f"/api/documents/resources/snapshot/{alice_snapshot['id']}/ignored"
        ).status_code == 404

        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        alice_resources = client.get("/api/documents").json()["resources_without_documents"]
        assert {
            resource["resource_id"]
            for resource in alice_resources
            if resource["kind"] == "snapshot"
        } == {alice_snapshot["id"]}


def test_shared_debt_documents_hide_private_repayment_account(app_factory):
    main, _, _ = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        bob = client.post("/api/profiles", json={"name": "Bob"}).json()
        private_account = client.post(
            "/api/accounts",
            json={"name": "Compte prive Alice"},
        ).json()
        debt = client.post(
            "/api/debts",
            json={
                "name": "Dette partagee",
                "principal": "100.00",
                "balance": "100.00",
                "account_id": private_account["id"],
                "owner_profile_ids": [alice["id"], bob["id"]],
            },
        ).json()
        debt_without_document = client.post(
            "/api/debts",
            json={
                "name": "Dette partagee sans document",
                "principal": "50.00",
                "balance": "50.00",
                "account_id": private_account["id"],
                "owner_profile_ids": [alice["id"], bob["id"]],
            },
        ).json()
        assert client.post(
            f"/api/debts/{debt['id']}/attachments",
            files={"file": ("preuve.txt", b"synthetique", "text/plain")},
        ).status_code == 201

        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        center = client.get("/api/documents").json()
        document = next(item for item in center["documents"] if item["kind"] == "debt")
        resource = next(
            item
            for item in center["resources_without_documents"]
            if item["kind"] == "debt"
            and item["resource_id"] == debt_without_document["id"]
        )
        assert document["account_id"] is None
        assert document["resource_context"] == "Compte de remboursement privé ou non associé"
        assert resource["account_id"] is None
        assert resource["context"] == "Compte de remboursement privé ou non associé"
