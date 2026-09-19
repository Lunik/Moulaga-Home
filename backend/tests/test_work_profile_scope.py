"""Profile isolation for work and retirement resources."""

from __future__ import annotations

import io

from conftest import load_app
from fastapi.testclient import TestClient


def _select_profile(client: TestClient, profile_id: int) -> None:
    response = client.post(f"/api/profiles/{profile_id}/select", json={})
    assert response.status_code == 200


def test_work_resources_are_isolated_by_active_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "false")
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        assert client.get("/api/work/summary").status_code == 401

        alice = client.post(
            "/api/profiles",
            json={"name": "Alice", "color": "#4f46e5"},
        )
        assert alice.status_code == 201
        alice_id = alice.json()["id"]
        _select_profile(client, alice_id)

        alice_contract = client.post(
            "/api/work/contracts",
            json={
                "employer": "Alice Employeur",
                "position": "Ingénieure",
                "start_date": "2020-01-01",
            },
        )
        assert alice_contract.status_code == 201
        alice_contract_id = alice_contract.json()["id"]
        alice_contract_attachment = client.post(
            f"/api/work/contracts/{alice_contract_id}/attachments",
            files={
                "file": (
                    "alice-contract.pdf",
                    io.BytesIO(b"synthetic alice contract"),
                    "application/pdf",
                )
            },
        )
        assert alice_contract_attachment.status_code == 201
        alice_contract_attachment_id = alice_contract_attachment.json()["id"]

        alice_payslip = client.post(
            "/api/work/payslips",
            json={
                "contract_id": alice_contract_id,
                "period": "2026-09",
                "gross_salary": "4000.00",
                "net_after_tax": "2800.00",
            },
        )
        assert alice_payslip.status_code == 201
        alice_payslip_id = alice_payslip.json()["id"]
        alice_payslip_attachment = client.post(
            f"/api/work/payslips/{alice_payslip_id}/attachments",
            files={
                "file": (
                    "alice-payslip.pdf",
                    io.BytesIO(b"synthetic alice payslip"),
                    "application/pdf",
                )
            },
        )
        assert alice_payslip_attachment.status_code == 201
        alice_payslip_attachment_id = alice_payslip_attachment.json()["id"]

        alice_pension = client.put(
            "/api/work/pension",
            json={
                "birth_year": 1985,
                "birth_month": 7,
                "target_retirement_age": 65,
                "validated_quarters": 80,
                "required_quarters": 172,
                "estimated_monthly_pension": "2200.00",
                "target_monthly_income": "3000.00",
            },
        )
        assert alice_pension.status_code == 200
        assert alice_pension.json()["estimated_total_quarters"] == 82

        bob = client.post(
            "/api/profiles/manage",
            json={"name": "Bob", "color": "#0ea5e9"},
        )
        assert bob.status_code == 201
        bob_id = bob.json()["id"]
        _select_profile(client, bob_id)

        assert client.get("/api/work/contracts").json() == []
        assert client.get("/api/work/payslips").json() == []
        bob_summary = client.get("/api/work/summary")
        assert bob_summary.status_code == 200
        assert bob_summary.json()["active_contracts_count"] == 0
        assert bob_summary.json()["latest_net_after_tax"] == "0.00"
        bob_pension = client.get("/api/work/pension")
        assert bob_pension.status_code == 200
        assert bob_pension.json()["id"] != alice_pension.json()["id"]
        assert bob_pension.json()["validated_quarters"] == 40

        for response in (
            client.get(f"/api/work/contracts/{alice_contract_id}"),
            client.patch(
                f"/api/work/contracts/{alice_contract_id}",
                json={"position": "Mutated"},
            ),
            client.delete(f"/api/work/contracts/{alice_contract_id}"),
            client.get(f"/api/work/contracts/{alice_contract_id}/attachments"),
            client.post(
                f"/api/work/contracts/{alice_contract_id}/attachments",
                files={"file": ("other.pdf", io.BytesIO(b"other"), "application/pdf")},
            ),
            client.get(
                f"/api/work/contracts/{alice_contract_id}/attachments/"
                f"{alice_contract_attachment_id}/download"
            ),
            client.delete(
                f"/api/work/contracts/{alice_contract_id}/attachments/"
                f"{alice_contract_attachment_id}"
            ),
            client.get(f"/api/work/payslips/{alice_payslip_id}"),
            client.patch(
                f"/api/work/payslips/{alice_payslip_id}",
                json={"gross_salary": "1.00"},
            ),
            client.post(
                f"/api/work/payslips/{alice_payslip_id}/attachments",
                files={"file": ("other.pdf", io.BytesIO(b"other"), "application/pdf")},
            ),
            client.get(
                f"/api/work/payslips/{alice_payslip_id}/attachments/"
                f"{alice_payslip_attachment_id}/download"
            ),
            client.delete(
                f"/api/work/payslips/{alice_payslip_id}/attachments/"
                f"{alice_payslip_attachment_id}"
            ),
            client.get(f"/api/work/attachments/{alice_payslip_attachment_id}"),
            client.delete(f"/api/work/attachments/{alice_payslip_attachment_id}"),
            client.post(
                "/api/work/payslips",
                json={"contract_id": alice_contract_id, "period": "2026-10"},
            ),
        ):
            assert response.status_code == 404

        bob_payslip = client.post(
            "/api/work/payslips",
            json={"period": "2026-09", "gross_salary": "2500.00"},
        )
        assert bob_payslip.status_code == 201

        _select_profile(client, alice_id)
        assert [item["id"] for item in client.get("/api/work/contracts").json()] == [
            alice_contract_id
        ]
        assert [item["id"] for item in client.get("/api/work/payslips").json()] == [
            alice_payslip_id
        ]
        assert client.get("/api/work/summary").json()["latest_net_after_tax"] == "2800.00"
        assert client.get("/api/work/pension").json()["birth_year"] == 1985
