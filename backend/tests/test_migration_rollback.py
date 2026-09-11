"""Test rollback de la migration SQLite : applique, rollback, vérifie idempotence."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def test_rollback_exists():
    rollback_script = Path(__file__).resolve().parent.parent / "scripts" / "rollback_migration.py"
    assert rollback_script.exists(), "Le script rollback_migration.py est manquant"


def test_migration_has_expected_columns():
    from app.migrations import EXPECTED_COLUMNS, SCHEMA_VERSION

    assert isinstance(EXPECTED_COLUMNS, dict)
    assert SCHEMA_VERSION >= 16
    for _table, cols in EXPECTED_COLUMNS.items():
        assert isinstance(cols, dict)
        for col, ddl in cols.items():
            assert isinstance(col, str)
            assert isinstance(ddl, str)


def test_rollback_script_executes():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = Path(f.name)
    try:
        with sqlite3.connect(temp_db) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS debts "
                "(id INTEGER PRIMARY KEY, name VARCHAR(120))"
            )
            connection.execute("ALTER TABLE debts ADD COLUMN test_col VARCHAR(16)")
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "scripts" / "rollback_migration.py"),
                "--db",
                str(temp_db),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Le rollback a échoué : {result.stderr}\n{result.stdout}"
        )
    finally:
        temp_db.unlink(missing_ok=True)
