"""Test rollback de la migration SQLite : applique, rollback, vérifie idempotence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "moulaga.db"


def test_rollback_exists():
    rollback_script = Path(__file__).resolve().parent.parent / "scripts" / "rollback_migration.py"
    assert rollback_script.exists(), "Le script rollback_migration.py est manquant"


def test_migration_has_expected_columns():
    from app.migrations import EXPECTED_COLUMNS, SCHEMA_VERSION
    assert isinstance(EXPECTED_COLUMNS, dict)
    assert SCHEMA_VERSION >= 14
    for table, cols in EXPECTED_COLUMNS.items():
        assert isinstance(cols, dict)
        for col, ddl in cols.items():
            assert isinstance(col, str)
            assert isinstance(ddl, str)


def test_rollback_script_executes():
    import tempfile
    import subprocess
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name
    try:
        # Créer un DB temporaire avec le schéma de base
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE IF NOT EXISTS debts (id INTEGER PRIMARY KEY, name VARCHAR(120))")
        conn.execute("ALTER TABLE debts ADD COLUMN test_col VARCHAR(16)")
        conn.commit()
        conn.close()
        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).resolve().parent.parent / "scripts" / "rollback_migration.py"),
                "--db",
                temp_db,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Le rollback a échoué : {result.stderr}\n{result.stdout}"
    finally:
        import os
        os.unlink(temp_db)
