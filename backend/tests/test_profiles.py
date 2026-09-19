"""Focused API coverage for local profiles and opaque browser sessions."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient


def test_profile_onboarding_selection_management_and_lock(app_factory):
    main, _, data_dir = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        assert client.get("/api/profiles").json() == []

        created = client.post(
            "/api/profiles",
            json={"name": "Alice", "color": "#123456", "pin": "1234"},
        )
        assert created.status_code == 201
        alice = created.json()
        assert alice["role"] == "admin"
        assert alice["has_pin"] is True

        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 401
        selected = client.post(
            f"/api/profiles/{alice['id']}/select", json={"pin": "1234"}
        )
        assert selected.status_code == 200
        assert "HttpOnly" in selected.headers["set-cookie"]
        assert client.get("/api/profile-session").json()["profile"]["id"] == alice["id"]
        assert client.get("/api/profiles/session").json()["profile"]["id"] == alice["id"]
        assert client.get("/api/accounts").headers["cache-control"] == "no-store"
        assert client.get("/api/accounts").headers["vary"] == "Cookie"

        bob = client.post("/api/profiles", json={"name": "Bob"}).json()
        assert bob["role"] == "member"
        assert client.get("/api/profiles/manage").json() == [alice, bob]
        assert client.get("/api/profiles?include_archived=true").json() == [alice, bob]
        ownership = client.get(f"/api/profiles/{alice['id']}/ownership").json()
        assert ownership["account_ids"]
        assert ownership["real_estate_asset_ids"] == []

        assert client.patch(
            f"/api/profiles/{alice['id']}", json={"active": False}
        ).status_code == 409
        assert client.post("/api/profiles/lock").status_code == 204
        assert client.get("/api/profiles/session").status_code == 401

    with sqlite3.connect(data_dir / "moulaga.db") as connection:
        pin_hash = connection.execute(
            "SELECT pin_hash FROM household_members WHERE id = ?", (alice["id"],)
        ).fetchone()[0]
        owners = connection.execute("SELECT member_id FROM account_owners").fetchall()
    assert pin_hash != "1234"
    assert pin_hash.startswith("pbkdf2_sha256$")
    assert owners == [(alice["id"],)]


def test_default_http_profile_cookie_persists_selection(tmp_path, monkeypatch):
    monkeypatch.delenv("MOULAGA_SESSION_COOKIE_SECURE", raising=False)
    from conftest import load_app

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="http://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        selected = client.post(f"/api/profiles/{alice['id']}/select", json={})

        assert selected.status_code == 200
        assert "Secure" not in selected.headers["set-cookie"]
        assert client.get("/api/profiles/session").json()["profile"]["id"] == alice["id"]


def test_secure_profile_cookie_can_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MOULAGA_SESSION_COOKIE_SECURE", "true")
    from conftest import load_app

    main, _ = load_app(tmp_path, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        selected = client.post(f"/api/profiles/{alice['id']}/select", json={})

        assert selected.status_code == 200
        assert "Secure" in selected.headers["set-cookie"]
        assert client.get("/api/profiles/session").json()["profile"]["id"] == alice["id"]


def test_member_manages_own_pin_and_admin_can_only_remove_it(app_factory):
    main, _, _ = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        assert client.post(
            "/api/profiles",
            json={"name": "Interdit", "pin": "1234"},
        ).status_code == 403
        assert client.post(
            "/api/profiles/manage",
            json={"name": "Interdit aussi", "pin": "1234"},
        ).status_code == 403
        bob = client.post("/api/profiles", json={"name": "Bob"}).json()

        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        configured = client.patch(f"/api/profiles/{bob['id']}", json={"pin": "2468"})
        assert configured.status_code == 200
        assert configured.json()["has_pin"] is True
        assert client.patch(
            f"/api/profiles/{alice['id']}", json={"pin": "1111"}
        ).status_code == 403

        assert client.post("/api/profiles/lock").status_code == 204
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 401
        assert client.post(
            f"/api/profiles/{bob['id']}/select", json={"pin": "2468"}
        ).status_code == 200
        changed = client.patch(f"/api/profiles/{bob['id']}", json={"pin": "8642"})
        assert changed.status_code == 200
        assert client.post("/api/profiles/lock").status_code == 204
        assert client.post(
            f"/api/profiles/{bob['id']}/select", json={"pin": "2468"}
        ).status_code == 401
        assert client.post(
            f"/api/profiles/{bob['id']}/select", json={"pin": "8642"}
        ).status_code == 200

        assert client.post("/api/profiles/lock").status_code == 204
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        assert client.patch(
            f"/api/profiles/{bob['id']}", json={"pin": "1357"}
        ).status_code == 403
        reset = client.patch(f"/api/profiles/{bob['id']}", json={"pin": None})
        assert reset.status_code == 200
        assert reset.json()["has_pin"] is False
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200


def test_pin_changes_revoke_other_profile_sessions(app_factory):
    main, _, _ = app_factory
    app = main.create_app()
    with (
        TestClient(app, base_url="https://testserver") as current_client,
        TestClient(app, base_url="https://testserver") as other_client,
    ):
        alice = current_client.post("/api/profiles", json={"name": "Alice"}).json()
        assert current_client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200
        assert other_client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200

        changed = current_client.patch(
            f"/api/profiles/{alice['id']}", json={"pin": "2468"}
        )

        assert changed.status_code == 200
        assert current_client.get("/api/profiles/session").status_code == 200
        assert other_client.get("/api/profiles/session").status_code == 401
        assert other_client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 401

        bob = current_client.post("/api/profiles", json={"name": "Bob"}).json()
        assert other_client.post(
            f"/api/profiles/{bob['id']}/select", json={}
        ).status_code == 200
        assert other_client.patch(
            f"/api/profiles/{bob['id']}", json={"pin": "8642"}
        ).status_code == 200

        reset = current_client.patch(
            f"/api/profiles/{bob['id']}", json={"pin": None}
        )

        assert reset.status_code == 200
        assert other_client.get("/api/profiles/session").status_code == 401
        assert other_client.post(
            f"/api/profiles/{bob['id']}/select", json={}
        ).status_code == 200


def test_archived_resources_do_not_block_deactivation_and_sessions_are_revoked(
    app_factory,
):
    main, _, _ = app_factory
    app = main.create_app()
    with (
        TestClient(app, base_url="https://testserver") as admin_client,
        TestClient(app, base_url="https://testserver") as member_client,
    ):
        alice = admin_client.post("/api/profiles", json={"name": "Alice"}).json()
        assert admin_client.post(
            f"/api/profiles/{alice['id']}/select", json={}
        ).status_code == 200
        bob = admin_client.post("/api/profiles", json={"name": "Bob"}).json()
        assert member_client.post(
            f"/api/profiles/{bob['id']}/select", json={}
        ).status_code == 200
        account = member_client.post(
            "/api/accounts", json={"name": "Ancien compte"}
        ).json()
        assert member_client.post(
            f"/api/accounts/{account['id']}/archive"
        ).status_code == 200
        debt = member_client.post(
            "/api/debts",
            json={"name": "Ancienne dette", "principal": "100.00", "balance": "0.00"},
        ).json()
        assert member_client.patch(
            f"/api/debts/{debt['id']}", json={"archived": True}
        ).status_code == 200

        deactivated = admin_client.patch(
            f"/api/profiles/{bob['id']}", json={"active": False}
        )

        assert deactivated.status_code == 200
        assert member_client.get("/api/profiles/session").status_code == 401
        assert admin_client.patch(
            f"/api/profiles/{bob['id']}", json={"active": True}
        ).status_code == 200
        assert member_client.get("/api/profiles/session").status_code == 401


def test_profile_pin_failures_are_throttled_and_profile_fields_reject_null(
    app_factory,
):
    main, _, _ = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post(
            "/api/profiles",
            json={"name": "Alice", "pin": "1234"},
        ).json()

        for _ in range(5):
            assert client.post(
                f"/api/profiles/{alice['id']}/select",
                json={"pin": "0000"},
            ).status_code == 401
        throttled = client.post(
            f"/api/profiles/{alice['id']}/select",
            json={"pin": "1234"},
        )
        assert throttled.status_code == 429
        assert int(throttled.headers["retry-after"]) > 0

        with sqlite3.connect(app_factory[2] / "moulaga.db") as connection:
            connection.execute(
                "UPDATE household_members "
                "SET pin_failed_attempts = 0, pin_locked_until = NULL "
                "WHERE id = ?",
                (alice["id"],),
            )
        assert client.post(
            f"/api/profiles/{alice['id']}/select",
            json={"pin": "1234"},
        ).status_code == 200
        for field in ("name", "color", "active", "role"):
            assert client.patch(
                f"/api/profiles/{alice['id']}",
                json={field: None},
            ).status_code == 422


def test_first_profile_bootstrap_is_atomic(app_factory):
    main, _, _ = app_factory
    barrier = Barrier(2)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        def create(name: str):
            barrier.wait()
            return client.post("/api/profiles", json={"name": name})

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(create, ("Alice", "Bob")))

        assert sorted(response.status_code for response in responses) == [201, 401]
        profiles = client.get("/api/profiles").json()
        assert len(profiles) == 1
        assert profiles[0]["role"] == "admin"


def test_owner_link_column_migrates_from_profile_to_member_id(app_factory, monkeypatch):
    main, _, data_dir = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        profile = client.post("/api/profiles", json={"name": "Alice"}).json()

    with sqlite3.connect(data_dir / "moulaga.db") as connection:
        connection.execute("ALTER TABLE account_owners RENAME COLUMN member_id TO profile_id")
        connection.execute("PRAGMA user_version = 26")

    from conftest import load_app

    main, _ = load_app(data_dir, monkeypatch)
    with TestClient(main.create_app()):
        pass

    with sqlite3.connect(data_dir / "moulaga.db") as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(account_owners)")
        }
        owner_ids = connection.execute("SELECT member_id FROM account_owners").fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "member_id" in columns
    assert owner_ids == [(profile["id"],)]
    assert version == 29


def test_restart_does_not_restore_a_demoted_first_administrator(app_factory):
    main, _, _ = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        bob = client.post("/api/profiles", json={"name": "Bob"}).json()
        assert client.patch(
            f"/api/profiles/{bob['id']}", json={"role": "admin"}
        ).status_code == 200
        assert client.patch(
            f"/api/profiles/{alice['id']}", json={"role": "member"}
        ).status_code == 200

    with TestClient(main.create_app(), base_url="https://testserver") as client:
        profiles = client.get("/api/profiles").json()
        assert next(profile for profile in profiles if profile["id"] == alice["id"])[
            "role"
        ] == "member"
        assert next(profile for profile in profiles if profile["id"] == bob["id"])[
            "role"
        ] == "admin"


def test_startup_backfill_does_not_add_first_member_to_owned_resources(
    app_factory, monkeypatch
):
    main, _, data_dir = app_factory
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        alice = client.post("/api/profiles", json={"name": "Alice"}).json()
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        bob = client.post("/api/profiles/manage", json={"name": "Bob"}).json()

    with sqlite3.connect(data_dir / "moulaga.db") as connection:
        account_id = connection.execute("SELECT id FROM accounts").fetchone()[0]
        connection.execute("DELETE FROM account_owners WHERE account_id = ?", (account_id,))
        connection.execute(
            "INSERT INTO account_owners (account_id, member_id, weight) VALUES (?, ?, 1)",
            (account_id, bob["id"]),
        )

    from conftest import load_app

    main, _ = load_app(data_dir, monkeypatch)
    with TestClient(main.create_app(), base_url="https://testserver") as client:
        assert client.post(f"/api/profiles/{alice['id']}/select", json={}).status_code == 200
        assert client.get(f"/api/profiles/{alice['id']}/ownership").json()["account_ids"] == []
        assert client.post(f"/api/profiles/{bob['id']}/select", json={}).status_code == 200
        assert client.get(f"/api/profiles/{bob['id']}/ownership").json()["account_ids"] == [
            account_id
        ]
