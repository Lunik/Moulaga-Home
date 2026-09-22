"""Contracts for profile-scoped update prompts."""

from __future__ import annotations

import sqlite3
from datetime import date

from conftest import load_app
from fastapi.testclient import TestClient


def _previous_period() -> str:
    first = date.today().replace(day=1)
    previous = first.replace(day=1)
    if previous.month == 1:
        return f"{previous.year - 1:04d}-12"
    return f"{previous.year:04d}-{previous.month - 1:02d}"


def test_prompts_follow_missing_data_and_value_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "false")
    app_module, _ = load_app(tmp_path, monkeypatch)
    with TestClient(app_module.create_app()) as client:
        profile = client.post("/api/profiles", json={"name": "Profil rappels"}).json()
        assert client.post(
            f"/api/profiles/{profile['id']}/select", json={}
        ).status_code == 200
        accounts = client.get("/api/accounts").json()
        account = accounts[0]

        recurring = client.post(
            "/api/recurring",
            json={
                "label": "Assurance test",
                "account_id": account["id"],
                "frequency": "monthly",
                "next_due": date.today().isoformat(),
                "amount": "-20.00",
                "amount_type": "fixed",
                "status": "active",
                "recurring_type": "subscription",
            },
        ).json()
        contract = client.post(
            "/api/work/contracts",
            json={
                "employer": "Employeur synthétique",
                "position": "Poste test",
                "contract_type": "CDI",
                "start_date": "2020-01-01",
                "gross_annual_salary": "42000.00",
                "status": "active",
            },
        ).json()

        with sqlite3.connect(tmp_path / "moulaga.db") as connection:
            connection.execute(
                "UPDATE accounts SET created_at = '2020-01-01 00:00:00' WHERE id = ?",
                (account["id"],),
            )
            connection.execute(
                "UPDATE recurring_series "
                "SET created_at = '2020-01-01 00:00:00', "
                "amount_updated_at = '2020-01-01 00:00:00' WHERE id = ?",
                (recurring["id"],),
            )
            connection.execute(
                "UPDATE work_contracts "
                "SET created_at = '2020-01-01 00:00:00', "
                "updated_at = '2020-01-01 00:00:00' WHERE id = ?",
                (contract["id"],),
            )

        response = client.get("/api/update-prompts")
        assert response.status_code == 200
        prompts = response.json()["prompts"]
        by_kind = {item["kind"]: item for item in prompts}
        assert by_kind["missing_account_statement"]["resource_id"] == account["id"]
        assert by_kind["missing_account_statement"]["period"] == _previous_period()
        assert by_kind["missing_account_statement"]["recurrence_days"] == 30
        assert by_kind["stale_recurring_amount"]["resource_id"] == recurring["id"]
        assert by_kind["stale_recurring_amount"]["recurrence_days"] == 180
        assert by_kind["stale_work_contract"]["resource_id"] == contract["id"]
        assert by_kind["stale_work_contract"]["recurrence_days"] == 365
        assert by_kind["missing_payslip"]["period"] == _previous_period()
        assert "missing_documents" in by_kind
        assert "review_recurring_catalog" in by_kind

        ignored_recurring = client.post(
            f"/api/update-prompts/{by_kind['stale_recurring_amount']['id']}/ignore"
        )
        assert ignored_recurring.status_code == 200
        assert ignored_recurring.json()["mode"] == "snooze"
        assert ignored_recurring.json()["snoozed_until"] is not None
        assert "stale_recurring_amount" not in {
            item["kind"] for item in client.get("/api/update-prompts").json()["prompts"]
        }
        with sqlite3.connect(tmp_path / "moulaga.db") as connection:
            connection.execute(
                "UPDATE update_prompt_dismissals "
                "SET snoozed_until = '2020-01-01 00:00:00' "
                "WHERE prompt_id = ?",
                (by_kind["stale_recurring_amount"]["id"],),
            )
        assert "stale_recurring_amount" in {
            item["kind"] for item in client.get("/api/update-prompts").json()["prompts"]
        }

        document_prompt = next(
            item for item in prompts if item["kind"] == "missing_documents"
        )
        assert document_prompt["ignore_mode"] == "document"
        assert document_prompt["document_kind"] is not None
        assert document_prompt["recurrence_days"] is None
        ignored_document = client.post(
            f"/api/update-prompts/{document_prompt['id']}/ignore"
        )
        assert ignored_document.status_code == 200
        assert ignored_document.json() == {
            "mode": "document",
            "snoozed_until": None,
        }
        document_center = client.get("/api/documents").json()
        assert any(
            item["kind"] == document_prompt["document_kind"]
            and item["resource_id"] == document_prompt["resource_id"]
            for item in document_center["ignored_resources"]
        )
        assert document_prompt["id"] not in {
            item["id"] for item in client.get("/api/update-prompts").json()["prompts"]
        }

        assert client.put(
            f"/api/accounts/{account['id']}/snapshots",
            json={"period": _previous_period(), "balance": "125.00"},
        ).status_code == 200
        assert client.patch(
            f"/api/recurring/{recurring['id']}",
            json={"amount": "-21.00"},
        ).status_code == 200
        assert client.patch(
            f"/api/work/contracts/{contract['id']}",
            json={"gross_annual_salary": "43000.00"},
        ).status_code == 200
        assert client.post(
            "/api/work/payslips",
            json={
                "contract_id": contract["id"],
                "period": _previous_period(),
                "gross_salary": "3583.33",
                "taxable_net": "2900.00",
                "net_before_tax": "2800.00",
                "pas_rate": "5.00",
                "pas_amount": "140.00",
                "net_after_tax": "2660.00",
            },
        ).status_code == 201

        remaining_kinds = {
            item["kind"] for item in client.get("/api/update-prompts").json()["prompts"]
        }
        assert "missing_account_statement" not in remaining_kinds
        assert "stale_recurring_amount" not in remaining_kinds
        assert "stale_work_contract" not in remaining_kinds
        assert "missing_payslip" not in remaining_kinds
