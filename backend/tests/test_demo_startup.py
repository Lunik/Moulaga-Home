"""Container demo-mode startup contract."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.config import Settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPOSITORY_ROOT / "docker" / "entrypoint.sh"


def _start_container_entrypoint(data_dir: Path, demo_mode: str | None) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["MOULAGA_DATA_DIR"] = str(data_dir)
    environment["PATH"] = (
        f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
    )
    if demo_mode is None:
        environment.pop("MOULAGA_DEMO_MODE", None)
    else:
        environment["MOULAGA_DEMO_MODE"] = demo_mode

    return subprocess.run(
        ["/bin/sh", str(ENTRYPOINT), sys.executable, "-c", "pass"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _account_names(database: Path) -> list[str]:
    with sqlite3.connect(database) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT name FROM accounts ORDER BY id").fetchall()
        ]


def test_demo_mode_defaults_to_disabled_and_parses_environment(monkeypatch):
    monkeypatch.delenv("MOULAGA_DEMO_MODE", raising=False)
    assert Settings().demo_mode is False

    monkeypatch.setenv("MOULAGA_DEMO_MODE", "true")
    assert Settings().demo_mode is True


def test_entrypoint_resets_while_demo_variable_is_enabled_then_preserves(tmp_path):
    first_start = _start_container_entrypoint(tmp_path, "true")
    database = tmp_path / "moulaga.db"
    assert "Mode demo actif" in first_start.stdout
    assert len(_account_names(database)) == 10

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE accounts SET name = ? WHERE name = ?",
            ("Modification temporaire", "Compte courant demo"),
        )
        connection.commit()
    assert "Modification temporaire" in _account_names(database)

    _start_container_entrypoint(tmp_path, "true")
    assert "Modification temporaire" not in _account_names(database)
    assert len([path for path in (tmp_path / "attached").rglob("*") if path.is_file()]) == 9

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE accounts SET name = ? WHERE name = ?",
            ("Donnees persistantes", "Compte courant demo"),
        )
        connection.commit()

    persistent_start = _start_container_entrypoint(tmp_path, None)
    assert "Mode demo actif" not in persistent_start.stdout
    assert "Donnees persistantes" in _account_names(database)
