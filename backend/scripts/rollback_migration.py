#!/usr/bin/env python3
"""Rollback script for SQLite migrations in Moulaga.

Applies DROP COLUMN for every column listed in EXPECTED_COLUMNS
so that a test can revert the schema to the previous version.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import EXPECTED_COLUMNS, sqlite_file_path
from app.config import settings


async def rollback(db_path: Path | None = None) -> None:
    target_path = db_path or settings.db_path
    url = f"sqlite+aiosqlite:///{target_path}"
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        for table, columns in EXPECTED_COLUMNS.items():
            for name in columns:
                try:
                    await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {name}"))
                except Exception:
                    pass  # Colonne peut déjà être absente
        await conn.commit()
    await engine.dispose()
    print("Rollback applied.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=str, default=None)
    args = parser.parse_args()
    path = Path(args.db) if args.db else None
    asyncio.run(rollback(path))
