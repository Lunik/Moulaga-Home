"""Test for the developer-only demo seeding command."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import load_app
from fastapi.testclient import TestClient


def test_seed_demo_populates_all_domains(tmp_path, monkeypatch):
    main, _ = load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)

    result = asyncio.run(seed.seed_demo())
    assert result.transactions > 0
    assert result.snapshots > 0
    assert result.debts == 3
    assert result.holdings == 2
    assert result.households == 1
    assert result.portfolio_snapshots > 0
    assert result.merchants > 0

    with TestClient(main.create_app()) as client:
        assert len(client.get("/api/accounts").json()) == 3
        assert client.get("/api/debts").json()
        assert client.get("/api/holdings").json()
        assert client.get("/api/rules").json()
        assert client.get("/api/recurring").json()
        assert client.get("/api/recurring/changes", params={"status": "pending"}).json()
        assert client.get("/api/portfolio/performance").json()
        assert client.get("/api/merchants").json()
        assert client.get("/api/contributions").json()
        households = client.get("/api/households").json()
        assert households
        goals = client.get(f"/api/households/{households[0]['id']}/goals").json()
        assert goals and goals[0]["current_amount"] == "750.00"


def test_seed_demo_refuses_to_overwrite_without_reset(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)

    asyncio.run(seed.seed_demo())
    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())

    # --reset wipes and reseeds without raising.
    result = asyncio.run(seed.seed_demo(reset=True))
    assert result.households == 1


def test_seed_demo_refuses_default_data_dir(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed
    import app.config

    importlib.reload(seed)
    # Simulate the production default path to ensure the guard trips.
    monkeypatch.setattr(app.config.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(app.config.settings, "database_url", None)
    monkeypatch.setattr(seed.settings, "data_dir", Path("/data"))
    monkeypatch.setattr(seed.settings, "database_url", None)

    with pytest.raises(seed.SeedError):
        asyncio.run(seed.seed_demo())


def test_seed_demo_cli_output_hides_database_path(tmp_path, monkeypatch, capsys):
    load_app(tmp_path, monkeypatch)
    import importlib

    import app.commands.seed_demo as seed

    importlib.reload(seed)

    exit_code = seed.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Donnees de demo generees" in captured.out
    # The concrete database path must never be printed.
    assert str(tmp_path) not in captured.out
    assert "moulaga.db" not in captured.out
