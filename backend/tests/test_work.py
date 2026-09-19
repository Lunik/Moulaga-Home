"""Tests for the Work router: contracts, pay slips, attachments, pension, and summary."""

from __future__ import annotations

import io

from conftest import load_app
from fastapi.testclient import TestClient


def _activate_default_profile(client: TestClient) -> None:
    profiles = client.get("/api/profiles")
    assert profiles.status_code == 200
    if profiles.json():
        profile_id = profiles.json()[0]["id"]
    else:
        created = client.post(
            "/api/profiles",
            json={"name": "Profil de test", "color": "#4f46e5"},
        )
        assert created.status_code == 201
        profile_id = created.json()["id"]
    response = client.post(f"/api/profiles/{profile_id}/select", json={})
    assert response.status_code == 200


def test_work_crud_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "false")
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        _activate_default_profile(client)
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
        assert pension["birth_month"] == 1
        assert pension["validated_quarters"] == 40
        assert pension["payslip_quarters"] == 2
        assert pension["estimated_total_quarters"] == 42
        assert pension["quarter_calculation"] == [
            {
                "year": 2026,
                "gross_salary": "4000.00",
                "quarter_threshold": "1803.00",
                "validated_quarters": 2,
                "next_quarter_remaining": "1409.00",
            }
        ]

        # Update pension profile
        pension_update = {
            "birth_year": 1992,
            "birth_month": 6,
            "target_retirement_age": 65,
            "validated_quarters": 52,
            "required_quarters": 172,
            "estimated_monthly_pension": "2600.00",
            "target_monthly_income": "3200.00",
            "income_growth_scenario": "strong_late",
            "future_work_percentage": 80,
            "planned_unemployment_months": 12,
            "notes": "Updated pension test",
        }
        res_p_up = client.put("/api/work/pension", json=pension_update)
        assert res_p_up.status_code == 200
        assert res_p_up.json()["birth_month"] == 6
        assert res_p_up.json()["income_growth_scenario"] == "strong_late"
        assert "future_annual_gross" not in res_p_up.json()
        assert res_p_up.json()["future_work_percentage"] == 80
        assert res_p_up.json()["planned_unemployment_months"] == 12
        assert res_p_up.json()["estimated_monthly_pension"] == "2600.00"
        assert res_p_up.json()["estimated_total_quarters"] == 54
        projection = res_p_up.json()["projection"]
        assert projection["reference_annual_gross"] == "48000.00"
        assert projection["payslip_count"] == 1
        assert projection["covered_years"] == [2026]
        assert projection["annual_social_security_ceiling"] == "48060.00"
        assert projection["simulated_end_annual_gross"] == "30720.00"
        assert projection["income_evolution"][0] == {
            "age_years": 34,
            "annual_gross": "48000.00",
        }
        assert [scenario["kind"] for scenario in projection["scenarios"]] == [
            "legal_age",
            "target",
            "full_rate_automatic",
        ]
        assert projection["scenarios"][0]["total_monthly_pension"] == "2293.72"

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
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "false")
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        _activate_default_profile(client)
        response = client.post(
            "/api/work/payslips",
            json={"period": "2026-99"},
        )

    assert response.status_code == 422


def test_payslip_quarters_are_aggregated_by_year_and_capped(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "false")
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        _activate_default_profile(client)
        pension_update = {
            "birth_year": 1990,
            "birth_month": 11,
            "target_retirement_age": 64,
            "validated_quarters": 12,
            "required_quarters": 172,
            "estimated_monthly_pension": "0.00",
            "target_monthly_income": "0.00",
            "notes": None,
        }
        assert client.put("/api/work/pension", json=pension_update).status_code == 200

        for period, gross_salary in (
            ("2025-01", "1781.99"),
            ("2025-02", "1782.01"),
            ("2025-03", "10000.00"),
            ("2014-12", "1429.50"),
            ("2001-12", "5000.00"),
        ):
            response = client.post(
                "/api/work/payslips",
                json={"period": period, "gross_salary": gross_salary},
            )
            assert response.status_code == 201

        pension = client.get("/api/work/pension").json()
        assert pension["payslip_quarters"] == 5
        assert pension["estimated_total_quarters"] == 17
        assert pension["unsupported_payslip_years"] == [2001]
        assert pension["quarter_calculation"] == [
            {
                "year": 2025,
                "gross_salary": "13564.00",
                "quarter_threshold": "1782.00",
                "validated_quarters": 4,
                "next_quarter_remaining": None,
            },
            {
                "year": 2014,
                "gross_salary": "1429.50",
                "quarter_threshold": "1429.50",
                "validated_quarters": 1,
                "next_quarter_remaining": "1429.50",
            },
        ]

        summary = client.get("/api/work/summary").json()
        assert summary["declared_validated_quarters"] == 12
        assert summary["payslip_quarters"] == 5
        assert summary["validated_quarters"] == 17
