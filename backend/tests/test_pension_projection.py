"""Tests for pension estimates derived from pay-slip salaries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.pension_projection import calculate_pension_projection, legal_retirement_age


def test_legal_retirement_age_follows_birth_year_schedule():
    assert legal_retirement_age(1960) == (62, 0)
    assert legal_retirement_age(1963) == (62, 9)
    assert legal_retirement_age(1966) == (63, 6)
    assert legal_retirement_age(1990) == (64, 0)


def test_projection_annualizes_payslips_and_increases_after_legal_age():
    payslips = [
        SimpleNamespace(period="2026-08", gross_salary=Decimal("4000.00")),
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4000.00")),
    ]

    projection = calculate_pension_projection(
        payslips,
        birth_year=1992,
        birth_month=1,
        target_retirement_age=65,
        current_quarters=54,
        required_quarters=172,
        today=date(2026, 9, 17),
    )

    assert projection is not None
    assert projection.reference_annual_gross == Decimal("48000.00")
    assert projection.payslip_count == 2
    assert projection.covered_years == [2026]
    assert [scenario.kind for scenario in projection.scenarios] == [
        "legal_age",
        "target",
        "full_rate_automatic",
    ]
    assert projection.scenarios[0].total_monthly_pension == Decimal("2955.70")
    assert (
        projection.scenarios[0].total_monthly_pension
        < projection.scenarios[1].total_monthly_pension
        < projection.scenarios[2].total_monthly_pension
    )


def test_projection_requires_positive_gross_salary():
    payslips = [
        SimpleNamespace(period="2026-09", gross_salary=Decimal("0.00")),
    ]

    assert (
        calculate_pension_projection(
            payslips,
            birth_year=1990,
            birth_month=1,
            target_retirement_age=64,
            current_quarters=40,
            required_quarters=172,
            today=date(2026, 9, 17),
        )
        is None
    )


def test_long_career_before_21_requires_five_early_quarters():
    payslips = [
        SimpleNamespace(period="2010-12", gross_salary=Decimal("7088.00")),
        SimpleNamespace(period="2011-01", gross_salary=Decimal("1800.00")),
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4333.33")),
    ]

    projection = calculate_pension_projection(
        payslips,
        birth_year=1990,
        birth_month=8,
        target_retirement_age=64,
        current_quarters=68,
        required_quarters=172,
        today=date(2026, 9, 17),
    )

    assert projection is not None
    assert projection.long_career.status == "eligible"
    assert projection.long_career.cutoff_year == 2011
    assert projection.long_career.required_early_quarters == 5
    assert projection.long_career.entered_early_quarters == 5
    assert projection.long_career.projected_quarters_at_63 == 175
    assert projection.scenarios[0].kind == "long_career"
    assert projection.scenarios[0].age_years == 63


def test_long_career_last_quarter_birth_requires_four_early_quarters():
    payslips = [
        SimpleNamespace(period="2011-12", gross_salary=Decimal("7200.00")),
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4333.33")),
    ]

    projection = calculate_pension_projection(
        payslips,
        birth_year=1990,
        birth_month=10,
        target_retirement_age=64,
        current_quarters=68,
        required_quarters=172,
        today=date(2026, 9, 17),
    )

    assert projection is not None
    assert projection.long_career.status == "eligible"
    assert projection.long_career.required_early_quarters == 4
    assert projection.long_career.entered_early_quarters == 4


def test_long_career_reports_missing_historical_payslips():
    payslips = [
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4333.33")),
    ]

    projection = calculate_pension_projection(
        payslips,
        birth_year=1990,
        birth_month=8,
        target_retirement_age=64,
        current_quarters=68,
        required_quarters=172,
        today=date(2026, 9, 17),
    )

    assert projection is not None
    assert projection.long_career.status == "insufficient_early_records"
    assert projection.long_career.entered_early_quarters == 0
    assert all(scenario.kind != "long_career" for scenario in projection.scenarios)


def test_long_career_requires_enough_projected_quarters_at_63():
    payslips = [
        SimpleNamespace(period="2010-12", gross_salary=Decimal("7088.00")),
        SimpleNamespace(period="2011-01", gross_salary=Decimal("1800.00")),
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4333.33")),
    ]

    projection = calculate_pension_projection(
        payslips,
        birth_year=1990,
        birth_month=8,
        target_retirement_age=64,
        current_quarters=20,
        required_quarters=172,
        today=date(2026, 9, 17),
    )

    assert projection is not None
    assert projection.long_career.status == "insufficient_projected_quarters"
    assert projection.long_career.entered_early_quarters == 5
    assert projection.long_career.projected_quarters_at_63 == 127
    assert all(scenario.kind != "long_career" for scenario in projection.scenarios)


def test_simulation_options_change_income_curve_and_pension():
    payslips = [
        SimpleNamespace(period="2026-08", gross_salary=Decimal("4000.00")),
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4000.00")),
    ]
    baseline = calculate_pension_projection(
        payslips,
        birth_year=1992,
        birth_month=6,
        target_retirement_age=65,
        current_quarters=54,
        required_quarters=172,
        today=date(2026, 9, 17),
        income_growth_scenario="regular",
        future_annual_gross=Decimal("72000.00"),
    )
    reduced = calculate_pension_projection(
        payslips,
        birth_year=1992,
        birth_month=6,
        target_retirement_age=65,
        current_quarters=54,
        required_quarters=172,
        today=date(2026, 9, 17),
        income_growth_scenario="strong_late",
        future_annual_gross=Decimal("72000.00"),
        future_work_percentage=80,
        planned_unemployment_months=12,
    )

    assert baseline is not None
    assert reduced is not None
    assert baseline.simulated_end_annual_gross == Decimal("72000.00")
    assert reduced.simulated_end_annual_gross == Decimal("57600.00")
    assert baseline.income_evolution[-1].annual_gross == Decimal("72000.00")
    assert reduced.income_evolution[-1].annual_gross == Decimal("57600.00")
    baseline_target = next(
        scenario for scenario in baseline.scenarios if scenario.kind == "target"
    )
    reduced_target = next(
        scenario for scenario in reduced.scenarios if scenario.kind == "target"
    )
    assert reduced_target.projected_quarters < baseline_target.projected_quarters
    assert reduced_target.total_monthly_pension < baseline_target.total_monthly_pension


def test_income_growth_presets_change_curve_shape():
    payslips = [
        SimpleNamespace(period="2026-09", gross_salary=Decimal("4000.00")),
    ]
    projections = {
        scenario: calculate_pension_projection(
            payslips,
            birth_year=1992,
            birth_month=1,
            target_retirement_age=65,
            current_quarters=54,
            required_quarters=172,
            today=date(2026, 9, 17),
            income_growth_scenario=scenario,
            future_annual_gross=Decimal("72000.00"),
        )
        for scenario in ("regular", "strong_early", "strong_late")
    }

    regular = projections["regular"]
    strong_early = projections["strong_early"]
    strong_late = projections["strong_late"]
    assert regular is not None
    assert strong_early is not None
    assert strong_late is not None
    midpoint = len(regular.income_evolution) // 2
    assert (
        strong_early.income_evolution[midpoint].annual_gross
        > regular.income_evolution[midpoint].annual_gross
        > strong_late.income_evolution[midpoint].annual_gross
    )
