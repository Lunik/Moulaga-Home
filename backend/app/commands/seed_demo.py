"""Developer-only command that seeds a temporary database with demo data.

This is a *visual QA* helper. It fills a configured, throwaway database with
rich but entirely synthetic, non-PII data across every domain of the app. The
same read models feed the PWA cache so every graph and summary can be checked
offline without retaining the transaction ledger.

Safety rules:

* it refuses to run against the default production data directory (``/data``)
  unless an explicit ``MOULAGA_DATABASE_URL`` is configured or
  ``MOULAGA_DEMO_MODE`` explicitly enables destructive demo startup;
* it refuses to overwrite a database that already holds user data unless the
  ``--reset`` flag is supplied;
* it never prints or logs the concrete database path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..attachments import remove_attachment, store_attachment
from ..common import add_month, get_preferences, money
from ..config import settings
from ..db import SessionLocal, engine, init_db
from ..debt_recurring import build_debt_recurring_series
from ..models import (
    Account,
    BalanceSnapshot,
    BalanceSnapshotAttachment,
    Base,
    CategorizationRule,
    Category,
    Contribution,
    Debt,
    DebtAttachment,
    Goal,
    GoalContribution,
    Holding,
    Household,
    HouseholdMember,
    MerchantIdentity,
    PortfolioSnapshot,
    RealEstateAsset,
    RealEstateAttachment,
    RealEstateDebtLink,
    RecurringChange,
    RecurringSeries,
    RecurringSeriesAttachment,
    SharedAccountLink,
    Transaction,
    TransactionAttachment,
)
from ..snapshot_import import parse_snapshot_tsv

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
    real_estate_assets: int
    holdings: int
    contributions: int
    households: int
    goals: int
    portfolio_snapshots: int
    merchants: int
    transaction_attachments: int
    snapshot_attachments: int
    recurring_attachments: int
    debt_attachments: int
    real_estate_attachments: int


def _guard_data_dir() -> None:
    if (
        settings.database_url is None
        and settings.data_dir == DEFAULT_DATA_DIR
        and not settings.demo_mode
    ):
        raise SeedError(
            "Refuse d'ecrire dans le repertoire de donnees par defaut. "
            "Definis MOULAGA_DATA_DIR vers un dossier de QA dedie ou active "
            "explicitement MOULAGA_DEMO_MODE."
        )


async def _has_user_data(session: AsyncSession) -> bool:
    """True if the database holds more than the freshly-seeded baseline."""
    accounts = await session.scalar(select(func.count()).select_from(Account))
    transactions = await session.scalar(select(func.count()).select_from(Transaction))
    households = await session.scalar(select(func.count()).select_from(Household))
    holdings = await session.scalar(select(func.count()).select_from(Holding))
    real_estate_assets = await session.scalar(
        select(func.count()).select_from(RealEstateAsset)
    )
    return bool(
        (accounts or 0) > 1
        or transactions
        or households
        or holdings
        or real_estate_assets
    )


async def _remove_attachment_files(session: AsyncSession) -> None:
    for model in (
        TransactionAttachment,
        BalanceSnapshotAttachment,
        RecurringSeriesAttachment,
        DebtAttachment,
        RealEstateAttachment,
    ):
        stored_paths = (await session.scalars(select(model.stored_path))).all()
        for stored_path in stored_paths:
            remove_attachment(stored_path)


async def _store_demo_file(filename: str, payload: bytes) -> tuple[str, str, int]:
    return await store_attachment(UploadFile(BytesIO(payload), filename=filename))


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
            await _remove_attachment_files(session)

    if reset:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await init_db()

    created_attachment_paths: list[str] = []
    async with SessionLocal() as session:
        try:
            result = await _seed(session, created_attachment_paths)
            await session.commit()
        except (OSError, SQLAlchemyError):
            for stored_path in created_attachment_paths:
                remove_attachment(stored_path)
            raise
    return result


async def _seed(
    session: AsyncSession,
    created_attachment_paths: list[str],
) -> SeedResult:
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
    logement_remainder = money("740.00")
    logement.monthly_budget = money(
        electricite.monthly_budget + internet.monthly_budget + logement_remainder
    )
    archived_category = Category(
        name="Ancienne categorie demo",
        kind="expense",
        color="#94a3b8",
        archived=True,
    )
    session.add_all([electricite, internet, archived_category])
    await session.flush()

    salaire = categories[("Salaire", "income")]
    loisirs = categories[("Loisirs", "expense")]
    transport = categories[("Transport", "expense")]
    transport.monthly_budget = None

    # Keep enough active accounts with varied balances to exercise dashboard
    # scrolling and descending balance sorting.
    # --- Accounts --------------------------------------------------------- #
    checking = await session.scalar(select(Account).where(Account.name == "Compte courant"))
    if checking is None:
        raise SeedError("Le compte local initial est introuvable.")
    checking.name = "Compte courant demo"
    checking.type = "checking"
    checking.currency = "EUR"
    checking.initial_balance = money("1200.00")
    checking.institution = "Caisse d’Épargne"
    checking.regional_entity = "Loire Drôme Ardèche"
    checking.account_number = "DEMO-COURANT-001"
    checking.color = "#4f46e5"
    savings = Account(
        name="Livret epargne demo", type="savings", currency="EUR",
        initial_balance=money("5000.00"), institution="Caisse d’Épargne",
        regional_entity="Rhône Alpes", color="#16a34a",
        account_number="DEMO-LIVRET-001",
        savings_product="Livret A", annual_interest_rate=Decimal("1.700"),
        legal_cap=money("22950.00"),
    )
    invest = Account(
        name="PEA demo", type="pea", currency="EUR",
        initial_balance=money("2634.00"), institution="Boursobank", color="#7c3aed",
        account_number="DEMO-PEA-001",
    )
    peg = Account(
        name="PEG Amundi demo", type="peg", currency="EUR",
        initial_balance=money("0.00"), institution="Amundi", color="#d71920",
        account_number="DEMO-PEG-001",
    )
    percol = Account(
        name="PER/PERCOL Amundi demo", type="percol", currency="EUR",
        initial_balance=money("11200.00"), institution="Amundi", color="#9f1239",
        account_number="DEMO-PERCOL-001",
    )
    boursobank_checking = Account(
        name="Compte courant Boursobank demo", type="checking", currency="EUR",
        initial_balance=money("2150.00"), institution="Boursobank", color="#d9f99d",
        account_number="DEMO-BOURSO-COURANT-001",
    )
    life_insurance = Account(
        name="Assurance vie Boursobank demo", type="life_insurance", currency="EUR",
        initial_balance=money("18500.00"), institution="Boursobank", color="#a855f7",
        account_number="DEMO-BOURSO-AV-001",
    )
    crypto_wallet = Account(
        name="Wallet crypto demo", type="wallet", currency="EUR",
        initial_balance=money("4200.00"), institution="Revolut", color="#06b6d4",
        account_number="DEMO-CRYPTO-001",
    )
    archived = Account(
        name="Compte cloture demo", type="checking", currency="EUR",
        initial_balance=money("0.00"), institution="Credit Agricole", color="#94a3b8",
        account_number="DEMO-ARCHIVE-001", archived=True,
    )
    sandbox = Account(
        name="Compte bac a sable demo", type="cash", currency="EUR",
        initial_balance=money("125.00"), color="#0ea5e9",
        account_number="DEMO-SANDBOX-001",
    )
    session.add_all(
        [
            savings,
            invest,
            peg,
            percol,
            boursobank_checking,
            life_insurance,
            crypto_wallet,
            archived,
            sandbox,
        ]
    )
    await session.flush()

    # --- Transactions across the last four cycles ------------------------- #
    anchor = date.today().replace(day=1)
    months = [add_month(anchor, -offset) for offset in range(3, -1, -1)]
    transaction_count = 0
    checking_monthly_deltas = {month: Decimal("0.00") for month in months}
    savings_monthly_deltas = {month: Decimal("0.00") for month in months}
    boursobank_monthly_deltas = {month: Decimal("0.00") for month in months}
    boursobank_monthly_expenses = (
        money("-350.00"),
        money("-350.00"),
        money("-370.00"),
        money("-330.00"),
    )
    receipt_transaction: Transaction | None = None
    session.add(
        Transaction(
            booked_at=add_month(anchor, -18).replace(day=12),
            description="Historique categorie archivee",
            amount=money("-7.00"),
            account_id=checking.id,
            category_id=archived_category.id,
        )
    )
    transaction_count += 1
    for month_index, month in enumerate(months):
        rows = [
            (month.replace(day=1), "Salaire mensuel", money("2500.00"), salaire.id, None),
            (month.replace(day=3), "Loyer", money("-750.00"), logement.id, None),
            (
                month.replace(day=6),
                "Fournisseur ELECTRICITE",
                money("-95.00"),
                electricite.id,
                None,
            ),
            (
                month.replace(day=6),
                "Abonnement INTERNET",
                money("-39.99"),
                internet.id,
                None,
            ),
            (
                month.replace(day=8),
                "Achat SUPERMARCHE",
                money("-84.30"),
                courses.id,
                "Ticket de caisse synthetique joint."
                if month == months[-1]
                else None,
            ),
            (month.replace(day=15), "Achat SUPERMARCHE", money("-61.20"), courses.id, None),
            (month.replace(day=18), "Cinema", money("-24.00"), loisirs.id, None),
            (month.replace(day=20), "Carburant STATION", money("-58.40"), transport.id, None),
            (month.replace(day=22), "Paiement sans categorie", money("-12.50"), None, None),
        ]
        for booked_at, description, amount, category_id, notes in rows:
            transaction = Transaction(
                booked_at=booked_at,
                description=description,
                amount=amount,
                account_id=checking.id,
                category_id=category_id,
                notes=notes,
            )
            session.add(transaction)
            checking_monthly_deltas[month] += amount
            if notes is not None:
                receipt_transaction = transaction
            transaction_count += 1

        boursobank_rows = [
            (
                month.replace(day=5),
                "Revenu complementaire demo",
                money("500.00"),
                salaire.id,
            ),
            (
                month.replace(day=17),
                "Courses compte Boursobank demo",
                boursobank_monthly_expenses[month_index],
                courses.id,
            ),
        ]
        for booked_at, description, amount, category_id in boursobank_rows:
            session.add(
                Transaction(
                    booked_at=booked_at,
                    description=description,
                    amount=amount,
                    account_id=boursobank_checking.id,
                    category_id=category_id,
                )
            )
            boursobank_monthly_deltas[month] += amount
            transaction_count += 1

        # Enough ordinary ledger entries to exercise account-level pagination.
        for index in range(17):
            amount = money("-2.00")
            session.add(
                Transaction(
                    booked_at=month.replace(day=9 + index),
                    description=f"Achat quotidien demo {month:%m}-{index + 1:02d}",
                    amount=amount,
                    account_id=checking.id,
                    category_id=loisirs.id,
                )
            )
            checking_monthly_deltas[month] += amount
            transaction_count += 1

        transfer_amount = money("250.00")
        transfer_group = f"demo-transfer-{month:%Y-%m}"
        session.add_all(
            [
                Transaction(
                    booked_at=month.replace(day=12),
                    description="Transfert vers Livret epargne demo",
                    amount=-transfer_amount,
                    account_id=checking.id,
                    transfer_group=transfer_group,
                ),
                Transaction(
                    booked_at=month.replace(day=12),
                    description="Transfert depuis Compte courant demo",
                    amount=transfer_amount,
                    account_id=savings.id,
                    transfer_group=transfer_group,
                ),
            ]
        )
        checking_monthly_deltas[month] -= transfer_amount
        savings_monthly_deltas[month] += transfer_amount
        transaction_count += 2

    archived_income = Transaction(
        booked_at=months[0].replace(day=2),
        description="Solde initial avant cloture",
        amount=money("400.00"),
        account_id=archived.id,
        category_id=salaire.id,
    )
    archived_expense = Transaction(
        booked_at=months[0].replace(day=24),
        description="Cloture du compte demo",
        amount=money("-400.00"),
        account_id=archived.id,
        notes="Compte conserve en lecture seule pour la QA.",
    )
    session.add_all([archived_income, archived_expense])
    transaction_count += 2

    # --- Monthly balance snapshots ----------------------------------------- #
    checking_running = Decimal(checking.initial_balance)
    savings_running = Decimal(savings.initial_balance)
    boursobank_running = Decimal(boursobank_checking.initial_balance)
    life_insurance_snapshot_values = ("16700.00", "17450.00", "18100.00", "18500.00")
    additional_snapshot_series = [
        (life_insurance, life_insurance_snapshot_values),
        (invest, ("2100.00", "2300.00", "2450.00", "2634.00")),
        (crypto_wallet, ("3600.00", "4100.00", "3850.00", "4200.00")),
    ]
    quick_import_snapshot_series = [
        (peg, ("6 500,00 €", "6 900,00 €", "7 350,00 €", "7 800,00 €")),
        (percol, ("9 200,00 €", "9 800,00 €", "10 400,00 €", "11 200,00 €")),
    ]
    snapshot_count = 0
    historical_months = [
        add_month(anchor, -offset) for offset in range(72, 3, -1)
    ]
    historical_snapshot_series = [
        (checking, Decimal("1400.00"), Decimal("12.00")),
        (boursobank_checking, Decimal("1100.00"), Decimal("17.00")),
        (peg, Decimal("2500.00"), Decimal("58.00")),
        (crypto_wallet, Decimal("900.00"), Decimal("38.00")),
    ]
    for account, opening_balance, monthly_growth in historical_snapshot_series:
        session.add_all(
            BalanceSnapshot(
                account_id=account.id,
                period=month.strftime("%Y-%m"),
                balance=money(opening_balance + monthly_growth * index),
            )
            for index, month in enumerate(historical_months)
        )
        snapshot_count += len(historical_months)

    latest_savings_snapshot: BalanceSnapshot | None = None
    for index, month in enumerate(months):
        checking_running += checking_monthly_deltas[month]
        savings_running += savings_monthly_deltas[month]
        boursobank_running += boursobank_monthly_deltas[month]
        checking_snapshot = BalanceSnapshot(
            account_id=checking.id,
            period=month.strftime("%Y-%m"),
            balance=money(checking_running),
        )
        savings_snapshot = BalanceSnapshot(
            account_id=savings.id,
            period=month.strftime("%Y-%m"),
            balance=money(savings_running),
        )
        boursobank_snapshot = BalanceSnapshot(
            account_id=boursobank_checking.id,
            period=month.strftime("%Y-%m"),
            balance=money(boursobank_running),
        )
        additional_snapshots = [
            BalanceSnapshot(
                account_id=account.id,
                period=month.strftime("%Y-%m"),
                balance=money(balances[index]),
            )
            for account, balances in additional_snapshot_series
        ]
        session.add_all(
            [
                checking_snapshot,
                savings_snapshot,
                boursobank_snapshot,
                *additional_snapshots,
            ]
        )
        latest_savings_snapshot = savings_snapshot
        snapshot_count += 3 + len(additional_snapshots)

    for account, balances in quick_import_snapshot_series:
        content = "Date\tMontant\n" + "\n".join(
            f"{month.replace(day=28).strftime('%d/%m/%Y')}\t{balances[index]}"
            for index, month in enumerate(months)
        )
        imported_rows = parse_snapshot_tsv(content)
        session.add_all(
            BalanceSnapshot(
                account_id=account.id,
                period=row.period,
                balance=row.balance,
            )
            for row in imported_rows
        )
        snapshot_count += len(imported_rows)

    archived_snapshot = BalanceSnapshot(
        account_id=archived.id,
        period=months[0].strftime("%Y-%m"),
        balance=money("0.00"),
    )
    session.add(archived_snapshot)
    snapshot_count += 1

    # --- Categorization rules --------------------------------------------- #
    session.add_all(
        [
            CategorizationRule(name="Supermarche", match_type="keyword", pattern="SUPERMARCHE",
                               patterns_json=json.dumps(
                                   ["SUPERMARCHE", "HYPERMARCHE", "EPICERIE"]
                               ),
                               category_id=courses.id, priority=200, enabled=True),
            CategorizationRule(name="Station", match_type="keyword", pattern="STATION",
                               category_id=transport.id, priority=150, enabled=True),
        ]
    )

    # --- Recurring series + a pending drift change ------------------------ #
    rent_series = RecurringSeries(
        label="Loyer", account_id=checking.id, category_id=logement.id, frequency="monthly",
        next_due=add_month(months[-1], 1).replace(day=3), amount=money("-750.00"),
        amount_type="fixed", status="active", recurring_type="rent", confidence=money("0.95"),
    )
    session.add(rent_series)
    await session.flush()
    session.add(
        RecurringSeries(
            label="Abonnement internet",
            account_id=checking.id,
            category_id=loisirs.id,
            frequency="monthly",
            next_due=anchor.replace(day=25),
            amount=money("-14.90"),
            amount_type="fixed",
            status="active",
            recurring_type="subscription",
            confidence=money("1.00"),
        )
    )
    session.add(
        RecurringSeries(
            label="Fournisseur electricite",
            account_id=checking.id,
            category_id=electricite.id,
            frequency="monthly",
            next_due=anchor.replace(day=20),
            amount=money("-95.00"),
            amount_type="variable",
            status="active",
            recurring_type="energy",
            confidence=money("0.85"),
        )
    )
    loan_series = RecurringSeries(
        label="Mensualite pret immobilier",
        account_id=checking.id,
        category_id=logement.id,
        frequency="monthly",
        next_due=add_month(anchor, 1).replace(day=15),
        amount=money("-920.00"),
        amount_type="fixed",
        status="active",
        recurring_type="loan_payment",
        confidence=money("1.00"),
    )
    credit_insurance_series = RecurringSeries(
        label="Assurance emprunteur",
        account_id=checking.id,
        category_id=logement.id,
        frequency="monthly",
        next_due=add_month(anchor, 1).replace(day=5),
        amount=money("-34.80"),
        amount_type="variable",
        status="active",
        recurring_type="credit_insurance",
        credit_insurance_rate=Decimal("0.320"),
        confidence=money("1.00"),
    )
    custom_series = RecurringSeries(
        label="Cotisation associative",
        account_id=checking.id,
        category_id=loisirs.id,
        frequency="yearly",
        next_due=add_month(anchor, 2).replace(day=12),
        amount=money("-45.00"),
        amount_type="fixed",
        status="active",
        recurring_type="other",
        custom_type="Cotisation associative",
        confidence=money("1.00"),
    )
    session.add_all([loan_series, credit_insurance_series, custom_series])
    await session.flush()
    session.add(
        RecurringChange(
            series_id=rent_series.id, change_type="amount", detected_amount=money("-780.00"),
            detected_next_due=add_month(months[-1], 1).replace(day=3), status="pending",
            note="Montant detecte different du montant enregistre",
        )
    )

    # --- Debts ------------------------------------------------------------- #
    mortgage = Debt(
        name="Pret immobilier demo",
        debt_type="mortgage",
        principal=money("210000.00"),
        balance=money("178000.00"),
        interest_rate=Decimal("2.10"),
        minimum_payment=money("920.00"),
        recurring_series_id=loan_series.id,
        due_date=date(2042, 5, 15),
        color="#7c3aed",
        archived=False,
    )
    auto_loan = Debt(
        name="Pret travaux demo",
        debt_type="consumer_credit",
        principal=money("15000.00"),
        balance=money("8200.00"),
        interest_rate=Decimal("2.90"),
        minimum_payment=money("250.00"),
        account_id=checking.id,
        due_date=add_month(anchor, 1).replace(day=5),
        color="#ef4444",
        archived=False,
    )
    student_loan = Debt(
        name="Pret etudiant",
        debt_type="other",
        principal=money("6000.00"),
        balance=money("1500.00"),
        interest_rate=Decimal("1.20"),
        minimum_payment=money("80.00"),
        account_id=checking.id,
        due_date=add_month(anchor, 2).replace(day=15),
        color="#f97316",
        archived=False,
    )
    session.add_all(
        [
            mortgage,
            auto_loan,
            student_loan,
            Debt(name="Ancien pret solde", debt_type="other",
                 principal=money("2000.00"), balance=money("0.00"),
                 interest_rate=Decimal("0.00"), minimum_payment=money("0.00"),
                 color="#94a3b8", archived=True),
        ]
    )
    await session.flush()
    automatic_debt_series = [
        build_debt_recurring_series(auto_loan),
        build_debt_recurring_series(student_loan),
    ]
    session.add_all(automatic_debt_series)
    await session.flush()
    for debt, series in zip(
        (auto_loan, student_loan),
        automatic_debt_series,
        strict=True,
    ):
        debt.recurring_series_id = series.id

    # --- Real estate ------------------------------------------------------- #
    apartment = RealEstateAsset(
        name="Appartement demo",
        property_type="primary_residence",
        address="12 rue des Exemples, 75000 Paris",
        acquired_on=date(2021, 5, 15),
        purchase_price=money("280000.00"),
        current_value=money("310000.00"),
        ownership_share=Decimal("100.00"),
    )
    land = RealEstateAsset(
        name="Terrain demo",
        property_type="land",
        acquired_on=date(2024, 3, 10),
        purchase_price=money("45000.00"),
        current_value=None,
        ownership_share=Decimal("50.00"),
    )
    session.add_all([apartment, land])
    await session.flush()
    session.add_all(
        [
            RealEstateDebtLink(asset_id=apartment.id, debt_id=mortgage.id),
            RealEstateDebtLink(asset_id=apartment.id, debt_id=auto_loan.id),
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
    life_fund = Holding(
        account_id=life_insurance.id,
        name="Fonds euros",
        symbol="FONDS-EUR",
        asset_class="fund",
        quantity=Decimal("100"),
        average_price=Decimal("175"),
        current_price=Decimal("185"),
    )
    session.add_all([etf, bond, life_fund])
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
    base_cost = Decimal("304300.00")
    base_value = Decimal("334350.00")
    life_insurance_cost_values = ("16000.00", "16500.00", "17000.00", "17500.00")
    for index, month in enumerate(months):
        cost_basis = money(
            base_cost
            + Decimal(index) * Decimal("200.00")
            + Decimal(life_insurance_cost_values[index])
        )
        market_value = money(
            base_value
            + Decimal(index) * Decimal("260.00")
            + Decimal(life_insurance_snapshot_values[index])
        )
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
    if receipt_transaction is None or latest_savings_snapshot is None:
        raise SeedError("Les donnees de demonstration des comptes sont incompletes.")

    transaction_attachments = [
        (
            receipt_transaction,
            "justificatif-courses-demo.txt",
            b"Moulaga QA - justificatif de transaction entierement synthetique.\n",
        ),
        (
            archived_expense,
            "justificatif-compte-archive-demo.txt",
            b"Moulaga QA - justificatif synthetique conserve en lecture seule.\n",
        ),
    ]
    for transaction, filename, payload in transaction_attachments:
        original_name, stored_path, size = await _store_demo_file(filename, payload)
        created_attachment_paths.append(stored_path)
        session.add(
            TransactionAttachment(
                transaction_id=transaction.id,
                original_name=original_name,
                stored_path=stored_path,
                content_type="text/plain",
                size=size,
            )
        )

    snapshot_attachments = [
        (
            latest_savings_snapshot,
            "releve-livret-demo.txt",
            b"Moulaga QA - releve mensuel d'epargne entierement synthetique.\n",
        ),
        (
            archived_snapshot,
            "releve-compte-archive-demo.txt",
            b"Moulaga QA - releve synthetique d'un compte archive.\n",
        ),
    ]
    for snapshot, filename, payload in snapshot_attachments:
        original_name, stored_path, size = await _store_demo_file(filename, payload)
        created_attachment_paths.append(stored_path)
        session.add(
            BalanceSnapshotAttachment(
                snapshot_id=snapshot.id,
                original_name=original_name,
                stored_path=stored_path,
                content_type="text/plain",
                size=size,
            )
        )

    recurring_attachments = [
        (
            credit_insurance_series,
            "contrat-assurance-emprunteur-demo.txt",
            b"Moulaga QA - contrat recurrent entierement synthetique.\n",
        ),
    ]
    for series, filename, payload in recurring_attachments:
        original_name, stored_path, size = await _store_demo_file(filename, payload)
        created_attachment_paths.append(stored_path)
        session.add(
            RecurringSeriesAttachment(
                series_id=series.id,
                original_name=original_name,
                stored_path=stored_path,
                content_type="text/plain",
                size=size,
            )
        )

    debt_attachments = [
        (
            mortgage,
            "offre-pret-immobilier-demo.txt",
            b"Moulaga QA - offre de pret entierement synthetique.\n",
        ),
    ]
    for debt, filename, payload in debt_attachments:
        original_name, stored_path, size = await _store_demo_file(filename, payload)
        created_attachment_paths.append(stored_path)
        session.add(
            DebtAttachment(
                debt_id=debt.id,
                original_name=original_name,
                stored_path=stored_path,
                content_type="text/plain",
                size=size,
            )
        )

    real_estate_attachments = [
        (
            apartment,
            "acte-propriete-demo.txt",
            b"Moulaga QA - acte de propriete entierement synthetique.\n",
        ),
    ]
    for asset, filename, payload in real_estate_attachments:
        original_name, stored_path, size = await _store_demo_file(filename, payload)
        created_attachment_paths.append(stored_path)
        session.add(
            RealEstateAttachment(
                asset_id=asset.id,
                original_name=original_name,
                stored_path=stored_path,
                content_type="text/plain",
                size=size,
            )
        )

    total_categories = await session.scalar(select(func.count()).select_from(Category))
    return SeedResult(
        accounts=10,
        transactions=transaction_count,
        snapshots=snapshot_count,
        categories=int(total_categories or 0),
        rules=2,
        recurring=8,
        changes=1,
        debts=4,
        real_estate_assets=2,
        holdings=3,
        contributions=contribution_count,
        households=1,
        goals=1,
        portfolio_snapshots=portfolio_snapshot_count,
        merchants=merchant_count,
        transaction_attachments=len(transaction_attachments),
        snapshot_attachments=len(snapshot_attachments),
        recurring_attachments=len(recurring_attachments),
        debt_attachments=len(debt_attachments),
        real_estate_attachments=len(real_estate_attachments),
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
        f"{result.real_estate_assets} bien(s) immobilier(s), "
        f"{result.holdings} actif(s), {result.contributions} versement(s), "
        f"{result.portfolio_snapshots} valorisation(s), {result.merchants} identite(s), "
        f"{result.households} foyer, {result.goals} objectif, "
        f"{result.transaction_attachments} justificatif(s) de transaction, "
        f"{result.snapshot_attachments} releve(s) joint(s), "
        f"{result.recurring_attachments} piece(s) jointe(s) recurrente(s), "
        f"{result.debt_attachments} piece(s) jointe(s) de dette, "
        f"{result.real_estate_attachments} piece(s) jointe(s) immobiliere(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
