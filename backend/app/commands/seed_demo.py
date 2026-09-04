"""Developer-only command that seeds a temporary database with demo data.

This is a *visual QA* helper. It fills a configured, throwaway database with
rich but entirely synthetic, non-PII data across every domain of the app.

Safety rules:

* it refuses to run against the default production data directory (``/data``)
  unless an explicit ``MOULAGA_DATABASE_URL`` is configured, so it can never
  accidentally target real banking data;
* it refuses to overwrite a database that already holds user data unless the
  ``--reset`` flag is supplied;
* it never prints or logs the concrete database path.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common import add_month, get_preferences, money
from ..config import settings
from ..db import SessionLocal, engine, init_db
from ..models import (
    Account,
    BalanceSnapshot,
    Base,
    CategorizationRule,
    Category,
    Contribution,
    Debt,
    Goal,
    GoalContribution,
    Holding,
    Household,
    HouseholdMember,
    MerchantIdentity,
    PortfolioSnapshot,
    RecurringChange,
    RecurringSeries,
    SharedAccountLink,
    Transaction,
)

DEFAULT_DATA_DIR = Path("/data")


class SeedError(RuntimeError):
    """Raised when seeding is refused for a safety reason."""


@dataclass(frozen=True)
class SeedResult:
    accounts: int
    transactions: int
    snapshots: int
    categories: int
    rules: int
    recurring: int
    changes: int
    debts: int
    holdings: int
    contributions: int
    households: int
    goals: int
    portfolio_snapshots: int
    merchants: int


def _guard_data_dir() -> None:
    if settings.database_url is None and settings.data_dir == DEFAULT_DATA_DIR:
        raise SeedError(
            "Refuse d'ecrire dans le repertoire de donnees par defaut. "
            "Definis MOULAGA_DATA_DIR vers un dossier de QA dedie."
        )


async def _has_user_data(session: AsyncSession) -> bool:
    """True if the database holds more than the freshly-seeded baseline."""
    accounts = await session.scalar(select(func.count()).select_from(Account))
    transactions = await session.scalar(select(func.count()).select_from(Transaction))
    households = await session.scalar(select(func.count()).select_from(Household))
    holdings = await session.scalar(select(func.count()).select_from(Holding))
    return bool((accounts or 0) > 1 or transactions or households or holdings)


async def seed_demo(reset: bool = False) -> SeedResult:
    """Seed the configured temporary database with synthetic demo data."""
    _guard_data_dir()
    settings.ensure_dirs()
    await init_db()

    async with SessionLocal() as session:
        if await _has_user_data(session) and not reset:
            raise SeedError(
                "La base contient deja des donnees. Relance avec --reset pour la reinitialiser."
            )

    if reset:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await init_db()

    async with SessionLocal() as session:
        result = await _seed(session)
        await session.commit()
    return result


async def _seed(session: AsyncSession) -> SeedResult:
    # Enable the privacy-gated local features so QA can view them.
    prefs = await get_preferences(session)
    prefs.local_merchant_identities = True
    prefs.private_categorization_enabled = True
    prefs.private_categorization_mode = "suggest"

    categories = {
        (category.name, category.kind): category
        for category in (await session.execute(select(Category))).scalars().all()
    }

    # --- Category hierarchy + budgets ------------------------------------- #
    logement = categories[("Logement", "expense")]
    logement.monthly_budget = money("900.00")
    courses = categories[("Courses", "expense")]
    courses.monthly_budget = money("450.00")
    electricite = Category(
        name="Electricite", kind="expense", color="#f59e0b", parent_id=logement.id,
        monthly_budget=money("120.00"),
    )
    internet = Category(
        name="Internet", kind="expense", color="#38bdf8", parent_id=logement.id,
        monthly_budget=money("40.00"),
    )
    session.add_all([electricite, internet])
    await session.flush()

    salaire = categories[("Salaire", "income")]
    loisirs = categories[("Loisirs", "expense")]
    transport = categories[("Transport", "expense")]

    # --- Accounts --------------------------------------------------------- #
    checking = await session.scalar(select(Account).where(Account.name == "Compte courant"))
    if checking is None:
        raise SeedError("Le compte local initial est introuvable.")
    checking.name = "Compte courant demo"
    checking.type = "checking"
    checking.currency = "EUR"
    checking.initial_balance = money("1200.00")
    checking.institution = "BNP Paribas"
    checking.color = "#4f46e5"
    savings = Account(
        name="Livret epargne demo", type="savings", currency="EUR",
        initial_balance=money("5000.00"), institution="BNP Paribas", color="#16a34a",
        savings_product="Livret A", annual_interest_rate=Decimal("1.700"),
        legal_cap=money("22950.00"),
    )
    invest = Account(
        name="PEA demo", type="investment", currency="EUR",
        initial_balance=money("0.00"), institution="Trade Republic", color="#7c3aed",
    )
    session.add_all([savings, invest])
    await session.flush()

    # --- Transactions across the last four cycles ------------------------- #
    anchor = date.today().replace(day=1)
    months = [add_month(anchor, -offset) for offset in range(3, -1, -1)]
    transaction_count = 0
    for month in months:
        rows = [
            (month.replace(day=1), "Salaire mensuel", money("2500.00"), salaire.id),
            (month.replace(day=3), "Loyer", money("-750.00"), logement.id),
            (month.replace(day=6), "Fournisseur ELECTRICITE", money("-95.00"), electricite.id),
            (month.replace(day=6), "Abonnement INTERNET", money("-39.99"), internet.id),
            (month.replace(day=8), "Achat SUPERMARCHE", money("-84.30"), courses.id),
            (month.replace(day=15), "Achat SUPERMARCHE", money("-61.20"), courses.id),
            (month.replace(day=18), "Cinema", money("-24.00"), loisirs.id),
            (month.replace(day=20), "Carburant STATION", money("-58.40"), transport.id),
            (month.replace(day=22), "Paiement sans categorie", money("-12.50"), None),
        ]
        for booked_at, description, amount, category_id in rows:
            session.add(
                Transaction(
                    booked_at=booked_at, description=description, amount=amount,
                    account_id=checking.id, category_id=category_id,
                )
            )
            transaction_count += 1

    # --- Monthly balance snapshots for the checking account --------------- #
    running = Decimal(checking.initial_balance)
    snapshot_count = 0
    for month in months:
        running += money("2500.00") - money("1125.39")
        session.add(
            BalanceSnapshot(
                account_id=checking.id, period=month.strftime("%Y-%m"), balance=money(running)
            )
        )
        snapshot_count += 1

    # --- Categorization rules --------------------------------------------- #
    session.add_all(
        [
            CategorizationRule(name="Supermarche", match_type="keyword", pattern="SUPERMARCHE",
                               category_id=courses.id, priority=200, enabled=True),
            CategorizationRule(name="Station", match_type="keyword", pattern="STATION",
                               category_id=transport.id, priority=150, enabled=True),
        ]
    )

    # --- Recurring series + a pending drift change ------------------------ #
    rent_series = RecurringSeries(
        label="Loyer", account_id=checking.id, category_id=logement.id, frequency="monthly",
        next_due=add_month(months[-1], 1).replace(day=3), amount=money("-750.00"),
        amount_type="fixed", status="active", confidence=money("0.95"), match_key="demo-loyer",
    )
    session.add(rent_series)
    await session.flush()
    session.add(
        RecurringSeries(
            label="Abonnement demo",
            account_id=checking.id,
            category_id=loisirs.id,
            frequency="monthly",
            next_due=anchor.replace(day=25),
            amount=money("-14.90"),
            amount_type="fixed",
            status="active",
            confidence=money("1.00"),
            match_key="demo-abonnement",
        )
    )
    session.add(
        RecurringChange(
            series_id=rent_series.id, change_type="amount", detected_amount=money("-780.00"),
            detected_next_due=add_month(months[-1], 1).replace(day=3), status="pending",
            note="Montant detecte different du montant enregistre",
        )
    )

    # --- Debts ------------------------------------------------------------- #
    session.add_all(
        [
            Debt(name="Pret auto", principal=money("15000.00"), balance=money("8200.00"),
                 interest_rate=Decimal("2.90"), minimum_payment=money("250.00"),
                 account_id=checking.id, due_date=add_month(anchor, 1).replace(day=5),
                 color="#ef4444", archived=False),
            Debt(name="Pret etudiant", principal=money("6000.00"), balance=money("1500.00"),
                 interest_rate=Decimal("1.20"), minimum_payment=money("80.00"),
                 due_date=add_month(anchor, 2).replace(day=15), color="#f97316", archived=False),
            Debt(name="Ancien pret solde", principal=money("2000.00"), balance=money("0.00"),
                 interest_rate=Decimal("0.00"), minimum_payment=money("0.00"),
                 color="#94a3b8", archived=True),
        ]
    )

    # --- Holdings + contributions ----------------------------------------- #
    etf = Holding(
        account_id=invest.id, name="ETF Monde", symbol="EWLD", asset_class="equity",
        quantity=Decimal("12"), average_price=Decimal("85"), current_price=Decimal("102"),
    )
    bond = Holding(
        account_id=invest.id, name="Fonds Obligations", symbol="BND", asset_class="bond",
        quantity=Decimal("30"), average_price=Decimal("48"), current_price=Decimal("47"),
    )
    session.add_all([etf, bond])
    await session.flush()
    contribution_count = 0
    for month in months:
        session.add(
            Contribution(holding_id=etf.id, amount=money("200.00"),
                         occurred_on=month.replace(day=5), note="Versement programme")
        )
        contribution_count += 1

    # --- Monthly portfolio valuation snapshots ---------------------------- #
    # Rising cost basis and market value so /portfolio/performance can render a
    # real gain/value history rather than a contributions-only series.
    portfolio_snapshot_count = 0
    base_cost = Decimal("1800.00")
    base_value = Decimal("1850.00")
    for index, month in enumerate(months):
        cost_basis = money(base_cost + Decimal(index) * Decimal("200.00"))
        market_value = money(base_value + Decimal(index) * Decimal("260.00"))
        session.add(
            PortfolioSnapshot(
                period=month.strftime("%Y-%m"),
                market_value=market_value,
                cost_basis=cost_basis,
            )
        )
        portfolio_snapshot_count += 1

    # --- Local merchant identities (no logos or network fetch) ------------ #
    session.add_all(
        [
            MerchantIdentity(label="Supermarche QA", pattern="SUPERMARCHE",
                             monogram="SM", color="#0ea5e9"),
            MerchantIdentity(label="Station QA", pattern="STATION",
                             monogram="ST", color="#f59e0b"),
            MerchantIdentity(label="Fournisseur Energie", pattern="ELECTRICITE",
                             monogram="EN", color="#22c55e"),
        ]
    )
    merchant_count = 3

    # --- Household + members + goals + sharing ---------------------------- #
    household = Household(name="Foyer QA")
    session.add(household)
    await session.flush()
    owner = HouseholdMember(household_id=household.id, name="Profil principal", role="owner")
    partner = HouseholdMember(household_id=household.id, name="Profil membre", role="member")
    session.add_all([owner, partner])
    await session.flush()

    goal = Goal(
        household_id=household.id, name="Fonds d'urgence", target_amount=money("3000.00"),
        current_amount=money("0.00"), due_date=add_month(anchor, 12), account_id=savings.id,
    )
    session.add(goal)
    await session.flush()
    session.add(
        GoalContribution(goal_id=goal.id, amount=money("750.00"),
                         occurred_on=anchor.replace(day=10), member_id=owner.id,
                         note="Mise de depart")
    )
    goal.current_amount = money("750.00")

    session.add(
        SharedAccountLink(household_id=household.id, account_id=checking.id, permission="edit")
    )

    await session.flush()
    total_categories = await session.scalar(select(func.count()).select_from(Category))
    return SeedResult(
        accounts=3,
        transactions=transaction_count,
        snapshots=snapshot_count,
        categories=int(total_categories or 0),
        rules=2,
        recurring=2,
        changes=1,
        debts=3,
        holdings=2,
        contributions=contribution_count,
        households=1,
        goals=1,
        portfolio_snapshots=portfolio_snapshot_count,
        merchants=merchant_count,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Remplit une base de QA temporaire avec des donnees synthetiques. "
            "Reserve au developpement: definir MOULAGA_DATA_DIR vers un dossier dedie."
        )
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reinitialise la base avant de semer (efface les donnees existantes).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(seed_demo(reset=args.reset))
    except SeedError as exc:
        print(f"Seed annule: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Seed annule: impossible d'ouvrir la base de QA locale.", file=sys.stderr)
        return 1

    # Only counts are printed; the database path is intentionally never shown.
    print(
        "Donnees de demo generees: "
        f"{result.accounts} comptes, {result.transactions} transactions, "
        f"{result.snapshots} instantanes, {result.categories} categories, "
        f"{result.rules} regles, {result.recurring} recurrence(s), "
        f"{result.changes} changement(s), {result.debts} dette(s), "
        f"{result.holdings} actif(s), {result.contributions} versement(s), "
        f"{result.portfolio_snapshots} valorisation(s), {result.merchants} identite(s), "
        f"{result.households} foyer, {result.goals} objectif."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
