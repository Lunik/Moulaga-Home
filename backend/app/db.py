"""Async SQLAlchemy engine + session plumbing over SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import settings
from .migrations import run_migrations, sqlite_file_path
from .models import Account, Category, Preferences

engine = create_async_engine(
    settings.sqlalchemy_url,
    echo=False,
    future=True,
    # SQLite + asyncio: a pooled connection held across tasks is the classic source of
    # "cannot operate on a closed database" under concurrency. NullPool opens per session,
    # which SQLite handles fine at this app's request volume.
    poolclass=NullPool,
    connect_args={"check_same_thread": False, "timeout": 30},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


async def init_db() -> None:
    await run_migrations(engine, sqlite_file_path(settings.sqlalchemy_url))
    async with SessionLocal() as session:
        if await session.scalar(select(Account.id).limit(1)) is None:
            session.add(Account(name="Compte courant", type="checking", currency="EUR"))

        default_categories = [
            ("Salaire", "income", "#16a34a"),
            ("Remboursements", "income", "#22c55e"),
            ("Logement", "expense", "#7c3aed"),
            ("Courses", "expense", "#f97316"),
            ("Transport", "expense", "#0ea5e9"),
            ("Loisirs", "expense", "#ec4899"),
            ("Sante", "expense", "#ef4444"),
            ("Epargne", "expense", "#64748b"),
        ]
        if await session.scalar(select(Category.id).limit(1)) is None:
            session.add_all(
                Category(name=name, kind=kind, color=color, is_default=True)
                for name, kind, color in default_categories
            )

        if await session.scalar(select(Preferences.id).limit(1)) is None:
            session.add(Preferences(id=1))
        await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
