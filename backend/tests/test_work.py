"""Tests for the Work router: contracts, pay slips, attachments, pension, and summary."""

from __future__ import annotations

import io

from conftest import load_app
from fastapi.testclient import TestClient


def test_work_crud_and_summary(tmp_path, monkeypatch):
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        # Check empty summary
        summary = client.get("/api/work/summary").json()
        assert summary["active_contracts_count"] == 0
        assert summary["latest_net_after_tax"] == "0.00"

        # Create contract
        contract_data = {
            "employer": "Acme Inc",
            "position": "Software Engineer",
            "contract_type": "CDI",
            "start_date": "2024-01-15",
            "gross_annual_salary": "48000.00",
            "work_percentage": 100,
            "status": "active",
            "notes": "Test contract",
        }
        res = client.post("/api/work/contracts", json=contract_data)
        assert res.status_code == 201
        contract = res.json()
        contract_id = contract["id"]
        assert contract["employer"] == "Acme Inc"
        assert contract["attachment_count"] == 0

        contract_payload = b"Fake employment contract"
        contract_attachment_response = client.post(
            f"/api/work/contracts/{contract_id}/attachments",
            files={
                "file": (
                    "contrat-acme.pdf",
                    io.BytesIO(contract_payload),
                    "application/pdf",
                )
            },
        )
        assert contract_attachment_response.status_code == 201
        contract_attachment = contract_attachment_response.json()
        contract_attachment_id = contract_attachment["id"]
        contract_file = tmp_path / contract_attachment["stored_path"]
        assert contract_file.read_bytes() == contract_payload
        assert client.get(f"/api/work/contracts/{contract_id}").json()[
            "attachment_count"
        ] == 1
        assert [
            item["id"]
            for item in client.get(
                f"/api/work/contracts/{contract_id}/attachments"
            ).json()
        ] == [contract_attachment_id]
        contract_download = client.get(
            f"/api/work/contracts/{contract_id}/attachments/"
            f"{contract_attachment_id}/download"
        )
        assert contract_download.status_code == 200
        assert contract_download.content == contract_payload

        update_contract = client.patch(
            f"/api/work/contracts/{contract_id}",
            json={"payment_period_months": 13},
        )
        assert update_contract.status_code == 200
        assert update_contract.json()["payment_period_months"] == 13

        # List contracts
        contracts = client.get("/api/work/contracts").json()
        assert len(contracts) == 1

        # Create payslip
        payslip_data = {
            "contract_id": contract_id,
            "period": "2026-09",
            "gross_salary": "4000.00",
            "taxable_net": "3200.00",
            "net_before_tax": "3100.00",
            "pas_rate": "8.00",
            "pas_amount": "248.00",
            "net_after_tax": "2852.00",
            "bonuses": "500.00",
            "employer_contributions": "1100.00",
            "employer_profit_sharing": "0.00",
            "hours_worked": "151.67",
        }
        res_slip = client.post("/api/work/payslips", json=payslip_data)
        assert res_slip.status_code == 201
        payslip = res_slip.json()
        payslip_id = payslip["id"]
        assert payslip["net_after_tax"] == "2852.00"

        # Check summary with contract + payslip
        summary = client.get("/api/work/summary").json()
        assert summary["active_contracts_count"] == 1
        assert summary["latest_net_after_tax"] == "2852.00"
        assert summary["ytd_taxable_net"] == "3200.00"

        # Attachment for payslip
        file_payload = b"Fake PDF Payslip"
        res_att = client.post(
            f"/api/work/payslips/{payslip_id}/attachments",
            files={"file": ("bulletin-2026-09.pdf", io.BytesIO(file_payload), "application/pdf")},
        )
        assert res_att.status_code == 201
        att = res_att.json()
        att_id = att["id"]

        attachments = client.get(
            f"/api/work/payslips/{payslip_id}/attachments"
        ).json()
        assert [item["id"] for item in attachments] == [att_id]

        # Download attachment from both the Work view and the document center route
        res_dl = client.get(f"/api/work/attachments/{att_id}")
        assert res_dl.status_code == 200
        assert res_dl.content == file_payload
        nested_download = client.get(
            f"/api/work/payslips/{payslip_id}/attachments/{att_id}/download"
        )
        assert nested_download.status_code == 200
        assert nested_download.content == file_payload

        documents = client.get("/api/documents").json()
        assert documents["stats"] == {
            "total_documents": 2,
            "total_size": len(contract_payload) + len(file_payload),
            "total_resources": 2,
            "covered_resources": 2,
            "missing_resources": 0,
        }
        payslip_document = next(
            item for item in documents["documents"] if item["kind"] == "payslip"
        )
        assert payslip_document["resource_id"] == payslip_id
        assert payslip_document["reference"] == "2026-09"
        assert payslip_document["download_url"].endswith(
            f"/work/payslips/{payslip_id}/attachments/{att_id}/download"
        )
        contract_document = next(
            item
            for item in documents["documents"]
            if item["kind"] == "work_contract"
        )
        assert contract_document["resource_id"] == contract_id
        assert contract_document["reference"] == "2024-01-15"
        assert contract_document["download_url"].endswith(
            f"/work/contracts/{contract_id}/attachments/"
            f"{contract_attachment_id}/download"
        )

        # Get pension profile (default created)
        pension = client.get("/api/work/pension").json()
        assert pension["target_retirement_age"] == 64

        # Update pension profile
        pension_update = {
            "birth_year": 1992,
            "target_retirement_age": 65,
            "validated_quarters": 52,
            "required_quarters": 172,
            "estimated_monthly_pension": "2600.00",
            "target_monthly_income": "3200.00",
            "notes": "Updated pension test",
        }
        res_p_up = client.put("/api/work/pension", json=pension_update)
        assert res_p_up.status_code == 200
        assert res_p_up.json()["estimated_monthly_pension"] == "2600.00"

        # Delete attachments
        del_contract_att = client.delete(
            f"/api/work/contracts/{contract_id}/attachments/"
            f"{contract_attachment_id}"
        )
        assert del_contract_att.status_code == 204
        assert not contract_file.exists()
        assert client.get("/api/documents").json()["stats"]["missing_resources"] == 1

        del_att = client.delete(
            f"/api/work/payslips/{payslip_id}/attachments/{att_id}"
        )
        assert del_att.status_code == 204
        assert client.get("/api/documents").json()["stats"]["missing_resources"] == 2

        # Delete contract and its stored files without deleting the linked payslip files
        replacement_attachment = client.post(
            f"/api/work/contracts/{contract_id}/attachments",
            files={
                "file": (
                    "avenant-acme.pdf",
                    io.BytesIO(b"Fake amendment"),
                    "application/pdf",
                )
            },
        ).json()
        replacement_file = tmp_path / replacement_attachment["stored_path"]
        assert replacement_file.exists()
        retained_payslip_attachment = client.post(
            f"/api/work/payslips/{payslip_id}/attachments",
            files={
                "file": (
                    "bulletin-conserve.pdf",
                    io.BytesIO(file_payload),
                    "application/pdf",
                )
            },
        ).json()
        retained_payslip_file = tmp_path / retained_payslip_attachment["stored_path"]
        assert retained_payslip_file.exists()

        del_contract = client.delete(f"/api/work/contracts/{contract_id}")
        assert del_contract.status_code == 204
        assert not replacement_file.exists()
        assert retained_payslip_file.exists()
        retained_payslip = client.get(f"/api/work/payslips/{payslip_id}").json()
        assert retained_payslip["contract_id"] is None
        assert client.get(
            f"/api/work/payslips/{payslip_id}/attachments/"
            f"{retained_payslip_attachment['id']}/download"
        ).content == file_payload

        # Deleting the payslip still removes its own stored files
        del_slip = client.delete(f"/api/work/payslips/{payslip_id}")
        assert del_slip.status_code == 204
        assert not retained_payslip_file.exists()


def test_payslip_period_rejects_invalid_month(tmp_path, monkeypatch):
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        response = client.post(
            "/api/work/payslips",
            json={"period": "2026-99"},
        )

    assert response.status_code == 422
