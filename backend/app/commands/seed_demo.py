"""Developer-only command that seeds a temporary database with demo data.

This is a *visual QA* helper. It fills a configured, throwaway database with
rich but entirely synthetic, non-PII data across every domain of the app. The
same read models feed the PWA cache so every graph and summary can be checked
offline without relying on an operation ledger.

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
from ..common import add_month, money
from ..config import settings
from ..db import SessionLocal, engine, init_db
from ..debt_recurring import (
    build_debt_recurring_series_insurance,
    build_debt_recurring_series_repayment,
)
from ..models import (
    Account,
    BalanceSnapshot,
    BalanceSnapshotAttachment,
    Base,
    Category,
    Contribution,
    Debt,
    DebtAttachment,
    Goal,
    GoalContribution,
    Holding,
    Household,
    HouseholdMember,
    PaySlip,
    PaySlipAttachment,
    PensionProfile,
    PortfolioSnapshot,
    RealEstateAsset,
    RealEstateAttachment,
    RealEstateDebtLink,
    RecurringSeries,
    RecurringSeriesAttachment,
    SharedAccountLink,
    WorkContract,
    WorkContractAttachment,
)
from ..snapshot_import import parse_snapshot_tsv

DEFAULT_DATA_DIR = Path("/data")


class SeedError(RuntimeError):
    """Raised when seeding is refused for a safety reason."""


@dataclass(frozen=True)
class SeedResult:
    accounts: int
    snapshots: int
    categories: int
    recurring: int
    debts: int
    real_estate_assets: int
    holdings: int
    contributions: int
    households: int
    goals: int
    portfolio_snapshots: int
    snapshot_attachments: int
    recurring_attachments: int
    debt_attachments: int
    real_estate_attachments: int
    contracts: int
    contract_attachments: int
    payslips: int
    payslip_attachments: int


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
    snapshots = await session.scalar(select(func.count()).select_from(BalanceSnapshot))
    recurring = await session.scalar(select(func.count()).select_from(RecurringSeries))
    debts = await session.scalar(select(func.count()).select_from(Debt))
    households = await session.scalar(select(func.count()).select_from(Household))
    holdings = await session.scalar(select(func.count()).select_from(Holding))
    real_estate_assets = await session.scalar(
        select(func.count()).select_from(RealEstateAsset)
    )
    return bool(
        (accounts or 0) > 1
        or snapshots
        or recurring
        or debts
        or households
        or holdings
        or real_estate_assets
    )


async def _remove_attachment_files(session: AsyncSession) -> None:
    for model in (
        BalanceSnapshotAttachment,
        RecurringSeriesAttachment,
        DebtAttachment,
        RealEstateAttachment,
        WorkContractAttachment,
        PaySlipAttachment,
    ):
        stored_paths = (await session.scalars(select(model.stored_path))).all()
        for stored_path in stored_paths:
            remove_attachment(stored_path)
    icon_paths = (
        await session.scalars(
            select(RealEstateAsset.icon_path).where(
                RealEstateAsset.icon_path.is_not(None)
            )
        )
    ).all()
    for icon_path in icon_paths:
        remove_attachment(icon_path)


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

    # --- Monthly balance statements --------------------------------------- #
    anchor = date.today().replace(day=1)
    months = [add_month(anchor, -offset) for offset in range(3, -1, -1)]
    checking_snapshot_values = ("4700.00", "5000.00", "5300.00", "5562.44")
    savings_snapshot_values = ("5250.00", "5500.00", "5750.00", "6000.00")
    boursobank_snapshot_values = ("2240.00", "2390.00", "2580.00", "2750.00")
    life_insurance_snapshot_values = ("16700.00", "17450.00", "18100.00", "18500.00")
    additional_snapshot_series = [
        (life_insurance, life_insurance_snapshot_values),
        (invest, ("2100.00", "2300.00", "2450.00", "2634.00")),
        (crypto_wallet, ("3600.00", "4100.00", "3850.00", "4200.00")),
    ]
    archived_snapshot_values = ("900.00", "600.00", "250.00", "0.00")
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
    latest_archived_snapshot: BalanceSnapshot | None = None
    for index, month in enumerate(months):
        checking_snapshot = BalanceSnapshot(
            account_id=checking.id,
            period=month.strftime("%Y-%m"),
            balance=money(checking_snapshot_values[index]),
        )
        boursobank_snapshot = BalanceSnapshot(
            account_id=boursobank_checking.id,
            period=month.strftime("%Y-%m"),
            balance=money(boursobank_snapshot_values[index]),
        )
        archived_snapshot = BalanceSnapshot(
            account_id=archived.id,
            period=month.strftime("%Y-%m"),
            balance=money(archived_snapshot_values[index]),
        )
        additional_snapshots = [
            BalanceSnapshot(
                account_id=account.id,
                period=month.strftime("%Y-%m"),
                balance=money(balances[index]),
            )
            for account, balances in additional_snapshot_series
            if account is not crypto_wallet or index < 2
        ]
        month_snapshots = [
            checking_snapshot,
            boursobank_snapshot,
            archived_snapshot,
            *additional_snapshots,
        ]
        if index != 1:
            savings_snapshot = BalanceSnapshot(
                account_id=savings.id,
                period=month.strftime("%Y-%m"),
                balance=money(savings_snapshot_values[index]),
            )
            month_snapshots.append(savings_snapshot)
            latest_savings_snapshot = savings_snapshot
        session.add_all(month_snapshots)
        latest_archived_snapshot = archived_snapshot
        snapshot_count += len(month_snapshots)

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

    # --- Recurring budget series ------------------------------------------ #
    salary_series = RecurringSeries(
        label="Salaire mensuel",
        account_id=checking.id,
        category_id=salaire.id,
        frequency="monthly",
        next_due=add_month(anchor, 1).replace(day=1),
        amount=money("3126.50"),
        amount_type="fixed",
        status="active",
        recurring_type="salary",
    )
    rent_series = RecurringSeries(
        label="Loyer", account_id=checking.id, category_id=logement.id, frequency="monthly",
        next_due=add_month(months[-1], 1).replace(day=3), amount=money("-750.00"),
        amount_type="fixed", status="active", recurring_type="rent",
    )
    session.add_all([salary_series, rent_series])
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
        )
    )
    loan_series = RecurringSeries(
        label="Remboursement · Pret immobilier demo",
        account_id=checking.id,
        category_id=logement.id,
        frequency="monthly",
        next_due=add_month(anchor, 1).replace(day=15),
        amount=money("-920.00"),
        amount_type="fixed",
        status="active",
        recurring_type="loan_payment",
    )
    credit_insurance_series = RecurringSeries(
        label="Assurance · Pret immobilier demo",
        account_id=checking.id,
        category_id=logement.id,
        frequency="monthly",
        next_due=add_month(anchor, 1).replace(day=5),
        amount=money("-34.80"),
        amount_type="variable",
        status="active",
        recurring_type="credit_insurance",
        credit_insurance_rate=Decimal("0.320"),
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
    )
    fuel_series = RecurringSeries(
        label="Budget carburant",
        account_id=checking.id,
        category_id=transport.id,
        frequency="monthly",
        next_due=anchor.replace(day=20),
        amount=money("-58.40"),
        amount_type="variable",
        status="active",
        recurring_type="other",
        custom_type="Carburant",
    )
    extra_income_series = RecurringSeries(
        label="Revenu complémentaire démo",
        account_id=boursobank_checking.id,
        category_id=salaire.id,
        frequency="monthly",
        next_due=anchor.replace(day=5),
        amount=money("500.00"),
        amount_type="fixed",
        status="active",
        recurring_type="other",
        custom_type="Revenu complémentaire",
    )
    boursobank_expense_series = RecurringSeries(
        label="Courses compte Boursobank demo",
        account_id=boursobank_checking.id,
        category_id=courses.id,
        frequency="monthly",
        next_due=anchor.replace(day=17),
        amount=money("-330.00"),
        amount_type="variable",
        status="active",
        recurring_type="other",
        custom_type="Courses",
    )
    session.add_all(
        [
            loan_series,
            credit_insurance_series,
            custom_series,
            fuel_series,
            extra_income_series,
            boursobank_expense_series,
        ]
    )
    await session.flush()

    # --- Debts ------------------------------------------------------------- #
    mortgage = Debt(
        name="Pret immobilier demo",
        debt_type="mortgage",
        principal=money("210000.00"),
        balance=money("178000.00"),
        interest_rate=Decimal("2.10"),
        minimum_payment=money("920.00"),
        recurring_series_repayment_id=loan_series.id,
        recurring_series_insurance_id=credit_insurance_series.id,
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
    automatic_debt_series = []
    for debt in (auto_loan, student_loan):
        repayment_series = build_debt_recurring_series_repayment(debt)
        insurance_series = build_debt_recurring_series_insurance(debt)
        automatic_debt_series.extend([repayment_series, insurance_series])
    session.add_all(automatic_debt_series)
    await session.flush()
    for debt, repayment_series, insurance_series in zip(
        (auto_loan, student_loan),
        automatic_debt_series[::2],
        automatic_debt_series[1::2],
        strict=True,
    ):
        debt.recurring_series_repayment_id = repayment_series.id
        debt.recurring_series_insurance_id = insurance_series.id

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
    if latest_savings_snapshot is None or latest_archived_snapshot is None:
        raise SeedError("Les donnees de demonstration des comptes sont incompletes.")

    snapshot_attachments = [
        (
            latest_savings_snapshot,
            "releve-livret-demo.txt",
            b"Moulaga QA - releve mensuel d'epargne entierement synthetique.\n",
        ),
        (
            latest_archived_snapshot,
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
            salary_series,
            "bulletin-salaire-demo.txt",
            b"Moulaga QA - bulletin de salaire entierement synthetique.\n",
        ),
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
    fuel_series.document_ignored = True

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

    # Synthetic icon for the apartment (minimal PNG header)
    icon_filename = "appartement-icone-demo.png"
    icon_payload = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\xfc\xcf\xc0\x00\x00\x00"
        b"\x00\x04\x00\x01\xaa\x8a\x82\x8b\x00\x00\x00\x00"
        b"IEND\xaeB`\x82"
    )
    original_name, stored_path, size = await _store_demo_file(icon_filename, icon_payload)
    created_attachment_paths.append(stored_path)
    apartment.icon_path = stored_path

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
    total_recurring = await session.scalar(select(func.count()).select_from(RecurringSeries))

    # --- Work module seeding ------------------------------------------------ #
    current_contract = WorkContract(
        employer="Tech Corp Solutions",
        position="Lead Développeur Fullstack",
        contract_type="CDI",
        start_date=date(2021, 9, 1),
        gross_annual_salary=money("52000.00"),
        work_percentage=100,
        payment_period_months=12,
        recurring_series_id=salary_series.id,
        status="active",
        notes="CDI cadre avec forfait jours, participation & PEE",
    )
    previous_contract = WorkContract(
        employer="Studio Numérique Démo",
        position="Développeur fullstack",
        contract_type="CDD",
        start_date=date(2019, 9, 1),
        end_date=date(2021, 8, 31),
        gross_annual_salary=money("42000.00"),
        work_percentage=100,
        payment_period_months=12,
        status="ended",
        notes="Expérience professionnelle entièrement synthétique",
    )
    session.add_all([current_contract, previous_contract])
    await session.flush()

    contract_attachment_payload = (
        b"Moulaga QA - contrat de travail entierement synthetique.\n"
        b"Aucune donnee bancaire ou personnelle reelle.\n"
    )
    original_name, stored_path, size = await _store_demo_file(
        "contrat-travail-demo.txt",
        contract_attachment_payload,
    )
    created_attachment_paths.append(stored_path)
    session.add(
        WorkContractAttachment(
            contract_id=current_contract.id,
            original_name=original_name,
            stored_path=stored_path,
            content_type="text/plain",
            size=size,
        )
    )

    payslip_periods = [
        (
            "2026-09", money("4333.33"), money("3550.00"), money("3380.00"),
            Decimal("7.50"), money("253.50"), money("3126.50"), money("0.00"),
            money("1200.00"), money("0.00")
        ),
        (
            "2026-08", money("4333.33"), money("3550.00"), money("3380.00"),
            Decimal("7.50"), money("253.50"), money("3126.50"), money("0.00"),
            money("1200.00"), money("0.00")
        ),
        (
            "2026-07", money("4333.33"), money("3550.00"), money("3380.00"),
            Decimal("7.50"), money("253.50"), money("3126.50"), money("0.00"),
            money("1200.00"), money("0.00")
        ),
        (
            "2026-06", money("4333.33"), money("5550.00"), money("5380.00"),
            Decimal("7.50"), money("403.50"), money("4976.50"), money("2000.00"),
            money("1200.00"), money("1500.00")
        ),
        (
            "2026-05", money("4333.33"), money("3550.00"), money("3380.00"),
            Decimal("7.50"), money("253.50"), money("3126.50"), money("0.00"),
            money("1200.00"), money("0.00")
        ),
        (
            "2026-04", money("4333.33"), money("3550.00"), money("3380.00"),
            Decimal("7.50"), money("253.50"), money("3126.50"), money("0.00"),
            money("1200.00"), money("0.00")
        ),
    ]
    payslips = []
    for item in payslip_periods:
        (
            period, gross, taxable_net, net_before, pas_rate,
            pas_amt, net_after, bonus, emp_contrib, profit_sharing
        ) = item
        sl = PaySlip(
            contract_id=current_contract.id,
            period=period,
            gross_salary=gross,
            taxable_net=taxable_net,
            net_before_tax=net_before,
            pas_rate=pas_rate,
            pas_amount=pas_amt,
            net_after_tax=net_after,
            bonuses=bonus,
            employer_contributions=emp_contrib,
            employer_profit_sharing=profit_sharing,
            hours_worked=Decimal("151.67"),
            notes=None,
        )
        payslips.append(sl)
    session.add_all(payslips)
    await session.flush()

    payslip_attachment_payload = (
        b"Moulaga QA - bulletin de paie entierement synthetique.\n"
        b"Aucune donnee bancaire ou personnelle reelle.\n"
    )
    original_name, stored_path, size = await _store_demo_file(
        "bulletin-paie-2026-09-demo.txt",
        payslip_attachment_payload,
    )
    created_attachment_paths.append(stored_path)
    session.add(
        PaySlipAttachment(
            payslip_id=payslips[0].id,
            original_name=original_name,
            stored_path=stored_path,
            content_type="text/plain",
            size=size,
        )
    )

    pension = PensionProfile(
        birth_year=1990,
        target_retirement_age=64,
        validated_quarters=48,
        required_quarters=172,
        estimated_monthly_pension=money("2450.00"),
        target_monthly_income=money("3000.00"),
        notes="Estimation basée sur Relevé Individuel de Situation (RIS) Agirc-Arrco 2026",
    )
    session.add(pension)
    await session.flush()

    return SeedResult(
        accounts=10,
        snapshots=snapshot_count,
        categories=int(total_categories or 0),
        recurring=int(total_recurring or 0),
        debts=4,
        real_estate_assets=2,
        holdings=3,
        contributions=contribution_count,
        households=1,
        goals=1,
        portfolio_snapshots=portfolio_snapshot_count,
        snapshot_attachments=len(snapshot_attachments),
        recurring_attachments=len(recurring_attachments),
        debt_attachments=len(debt_attachments),
        real_estate_attachments=len(real_estate_attachments),
        contracts=2,
        contract_attachments=1,
        payslips=len(payslips),
        payslip_attachments=1,
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
        f"{result.accounts} comptes, {result.snapshots} releves, "
        f"{result.categories} categories, {result.recurring} recurrence(s), "
        f"{result.debts} dette(s), "
        f"{result.real_estate_assets} bien(s) immobilier(s), "
        f"{result.holdings} actif(s), {result.contributions} versement(s), "
        f"{result.portfolio_snapshots} valorisation(s), "
        f"{result.households} foyer, {result.goals} objectif, "
        f"{result.snapshot_attachments} releve(s) joint(s), "
        f"{result.recurring_attachments} piece(s) jointe(s) recurrente(s), "
        f"{result.debt_attachments} piece(s) jointe(s) de dette, "
        f"{result.real_estate_attachments} piece(s) jointe(s) immobiliere(s)."
        f" {result.contracts} contrat(s), "
        f"{result.contract_attachments} contrat(s) joint(s), "
        f"{result.payslips} fiche(s) de paie, "
        f"{result.payslip_attachments} bulletin(s) joint(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
