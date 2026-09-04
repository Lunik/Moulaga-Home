from __future__ import annotations

import asyncio
import importlib
from datetime import date

from fastapi.testclient import TestClient


def _load_application(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_DATA_DIR", str(tmp_path))

    import app.commands.import_banque_v3
    import app.config
    import app.db
    import app.main
    import app.routers.budget

    importlib.reload(app.config)
    importlib.reload(app.db)
    importlib.reload(app.routers.budget)
    importlib.reload(app.main)
    importlib.reload(app.commands.import_banque_v3)
    return app.main, app.commands.import_banque_v3


def test_transactions_persist_between_application_restarts(tmp_path, monkeypatch):
    main, _migration = _load_application(tmp_path, monkeypatch)

    with TestClient(main.create_app()) as client:
        account = client.get("/api/accounts").json()[0]
        category = next(
            item for item in client.get("/api/categories").json() if item["name"] == "Courses"
        )
        response = client.post(
            "/api/transactions",
            json={
                "booked_at": date.today().isoformat(),
                "description": "Achat test",
                "amount": "-42.50",
                "account_id": account["id"],
                "category_id": category["id"],
                "notes": "Donnee synthetique",
            },
        )
        assert response.status_code == 201
        budget_response = client.patch(
            f"/api/categories/{category['id']}/budget",
            json={"monthly_budget": "500.00"},
        )
        assert budget_response.status_code == 200
        assert budget_response.json()["monthly_budget"] == "500.00"

    assert (tmp_path / "moulaga.db").is_file()

    with TestClient(main.create_app()) as restarted_client:
        transactions = restarted_client.get("/api/transactions").json()
        assert len(transactions) == 1
        assert transactions[0]["description"] == "Achat test"
        restarted_overview = restarted_client.get("/api/overview").json()
        assert restarted_overview["balance"] == "-42.50"
        assert restarted_overview["budget_current_month"] == "500.00"


def test_deleted_default_category_stays_deleted_after_restart(tmp_path, monkeypatch):
    main, _migration = _load_application(tmp_path, monkeypatch)

    with TestClient(main.create_app()) as client:
        categories = client.get("/api/categories").json()
        source = next(category for category in categories if category["name"] == "Courses")
        destination = next(category for category in categories if category["name"] == "Loisirs")
        response = client.delete(
            f"/api/categories/{source['id']}",
            params={"replacement_category_id": destination["id"]},
        )
        assert response.status_code == 204

    with TestClient(main.create_app()) as restarted_client:
        names = {category["name"] for category in restarted_client.get("/api/categories").json()}
        assert "Courses" not in names


def test_banque_v3_is_a_one_shot_migration_not_an_api_feature(tmp_path, monkeypatch):
    main, migration = _load_application(tmp_path, monkeypatch)
    csv_path = tmp_path / "migration.csv"
    csv_path.write_text(
        "Date;Libelle;Montant;Categorie\n"
        f"{date.today().isoformat()};Revenu test;2500,00;Salaire\n"
        f"{date.today().isoformat()};Depense test;-42,50;Courses\n",
        encoding="utf-8",
    )

    first_result = asyncio.run(migration.migrate_csv(csv_path, "Compte courant"))
    duplicate_result = asyncio.run(migration.migrate_csv(csv_path, "Compte courant"))

    assert first_result.imported == 2
    assert first_result.errors == ()
    assert duplicate_result.imported == 0
    assert duplicate_result.skipped_duplicates == 2

    with TestClient(main.create_app()) as client:
        assert "/api/imports/csv" not in client.app.openapi()["paths"]
        overview = client.get("/api/overview").json()
        assert overview["balance"] == "2457.50"
        assert overview["uncategorized_count"] == 0


def test_migration_is_atomic_when_a_row_is_invalid(tmp_path, monkeypatch):
    main, migration = _load_application(tmp_path, monkeypatch)
    csv_path = tmp_path / "migration.csv"
    csv_path.write_text(
        "Date;Libelle;Montant\n"
        f"{date.today().isoformat()};Ligne valide;-10,00\n"
        "date-invalide;Ligne invalide;-20,00\n",
        encoding="utf-8",
    )

    result = asyncio.run(migration.migrate_csv(csv_path, "Compte courant"))

    assert result.imported == 0
    assert len(result.errors) == 1
    with TestClient(main.create_app()) as client:
        assert client.get("/api/transactions").json() == []
