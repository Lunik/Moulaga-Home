#!/usr/bin/env python3
"""Enforce QA rules for DB migration : rollback script exists, test passes, no wrong column name."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    rollback_script = BACKEND_DIR / "scripts" / "rollback_migration.py"
    test_script = BACKEND_DIR / "tests" / "test_migration_rollback.py"

    errors = []

    if not rollback_script.exists():
        errors.append("Le script rollback_migration.py est manquant.")

    if not test_script.exists():
        errors.append("Le test test_migration_rollback.py est manquant.")

    # Vérifier qu'il n'y a pas d'ancienne colonne erronée dans migrations.py
    migrations_py = BACKEND_DIR / "app" / "migrations.py"
    content = migrations_py.read_text()
    if "recurring_series_id" in content:
        errors.append("Ancienne colonne erronée 'recurring_series_id' trouvée dans migrations.py.")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_script), "-v"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append(f"Le test rollback a échoué : {result.stdout}\n{result.stderr}")

    if errors:
        print("QA RULES — ÉCHEC", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("Migration + rollback OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
