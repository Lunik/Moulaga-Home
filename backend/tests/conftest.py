"""Shared test helpers.

Every test runs against an isolated, file-backed SQLite database created inside
a temporary directory. Only synthetic, non-sensitive data is ever used.
"""

from __future__ import annotations

import importlib

import pytest


def load_app(tmp_path, monkeypatch):
    """Reload the application against a fresh temporary data directory."""
    monkeypatch.setenv("MOULAGA_DATA_DIR", str(tmp_path))

    import app.common
    import app.config
    import app.db
    import app.main
    import app.migrations
    import app.routers.accounts
    import app.routers.budget
    import app.routers.budgets
    import app.routers.categories
    import app.routers.documents
    import app.routers.household
    import app.routers.preferences
    import app.routers.recurring
    import app.routers.wealth

    importlib.reload(app.config)
    importlib.reload(app.migrations)
    importlib.reload(app.db)
    importlib.reload(app.common)
    for module in (
        app.routers.budget,
        app.routers.accounts,
        app.routers.categories,
        app.routers.documents,
        app.routers.preferences,
        app.routers.budgets,
        app.routers.recurring,
        app.routers.wealth,
        app.routers.household,
    ):
        importlib.reload(module)
    importlib.reload(app.main)
    return app.main, None


@pytest.fixture
def app_factory(tmp_path, monkeypatch):
    main, migration = load_app(tmp_path, monkeypatch)
    return main, migration, tmp_path
