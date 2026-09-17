"""Indicative pension projection derived from entered pay slips."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

from .pension_quarters import calculate_payslip_quarters


class PaySlipAmount(Protocol):
    period: str
    gross_salary: Decimal


ProjectionKind = Literal[
    "long_career", "target", "legal_age", "full_rate_automatic"
]
LongCareerStatus = Literal[
    "eligible",
    "insufficient_early_records",
    "insufficient_projected_quarters",
]
IncomeGrowthScenario = Literal["none", "regular", "strong_early", "strong_late"]


@dataclass(frozen=True)
class PensionProjectionScenario:
    kind: ProjectionKind
    age_years: int
    age_months: int
    projected_quarters: int
    base_monthly_pension: Decimal
    complementary_monthly_pension: Decimal
    total_monthly_pension: Decimal


@dataclass(frozen=True)
class PensionProjection:
    reference_annual_gross: Decimal
    payslip_count: int
    covered_years: list[int]
    annual_social_security_ceiling: Decimal
    simulated_end_annual_gross: Decimal
    income_evolution: list[PensionIncomePoint]
    scenarios: list[PensionProjectionScenario]
    long_career: LongCareerAssessment


@dataclass(frozen=True)
class PensionIncomePoint:
    age_years: int
    annual_gross: Decimal


@dataclass(frozen=True)
class LongCareerAssessment:
    status: LongCareerStatus
    cutoff_year: int
    required_early_quarters: int
    entered_early_quarters: int
    projected_quarters_at_63: int
    required_total_quarters: int


ANNUAL_SOCIAL_SECURITY_CEILING_2026 = Decimal("48060.00")
AGIRC_ARRCO_POINT_PURCHASE_PRICE_2026 = Decimal("20.1877")
AGIRC_ARRCO_POINT_VALUE_2026 = Decimal("1.4386")
AGIRC_ARRCO_T1_POINT_RATE = Decimal("0.062")
AGIRC_ARRCO_T2_POINT_RATE = Decimal("0.17")
FULL_BASE_RATE = Decimal("0.50")
DISCOUNT_PER_MISSING_QUARTER = Decimal("0.0125")
MAX_DISCOUNT_QUARTERS = 20
MONTHS_PER_YEAR = Decimal(12)
QUARTERS_PER_YEAR = Decimal(4)
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ONE = Decimal(1)
HUNDRED = Decimal(100)
QUARTER_SALARY_THRESHOLD_2026 = Decimal("1803.00")
DEFAULT_ANNUAL_GROWTH_RATE = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def legal_retirement_age(birth_year: int) -> tuple[int, int]:
    if birth_year <= 1960:
        return 62, 0
    if birth_year == 1961:
        return 62, 3
    if birth_year == 1962:
        return 62, 6
    if birth_year == 1963:
        return 62, 9
    if birth_year == 1964:
        return 63, 0
    if birth_year == 1965:
        return 63, 3
    if birth_year == 1966:
        return 63, 6
    if birth_year == 1967:
        return 63, 9
    return 64, 0


def _reference_annual_gross(
    payslips: Iterable[PaySlipAmount],
) -> tuple[Decimal, int, list[int]]:
    gross_and_months_by_year: dict[int, tuple[Decimal, set[str]]] = {}
    payslip_count = 0
    for payslip in payslips:
        payslip_count += 1
        year = int(payslip.period[:4])
        gross, periods = gross_and_months_by_year.get(year, (ZERO, set()))
        gross_and_months_by_year[year] = (
            gross + max(payslip.gross_salary, ZERO),
            periods | {payslip.period},
        )

    if not gross_and_months_by_year:
        return ZERO, payslip_count, []
    latest_year = max(gross_and_months_by_year)
    latest_gross, latest_periods = gross_and_months_by_year[latest_year]
    reference = latest_gross * MONTHS_PER_YEAR / Decimal(len(latest_periods))
    return _money(reference), payslip_count, sorted(gross_and_months_by_year, reverse=True)


def _projected_quarters(
    current_quarters: int,
    birth_year: int,
    birth_month: int,
    retirement_age_years: int,
    retirement_age_months: int,
    today: date,
    annual_gross: Decimal,
    future_work_percentage: int,
    planned_unemployment_months: int,
) -> int:
    current_age_months = (today.year - birth_year) * 12 + today.month - birth_month
    retirement_age_total_months = retirement_age_years * 12 + retirement_age_months
    remaining_months = max(retirement_age_total_months - current_age_months, 0)
    full_year_quarter_capacity = min(
        4,
        int(
            (
                annual_gross
                * Decimal(future_work_percentage)
                / HUNDRED
            )
            // QUARTER_SALARY_THRESHOLD_2026
        ),
    )
    full_years, partial_months = divmod(remaining_months, 12)
    additional_quarters = (
        full_years * full_year_quarter_capacity
        + min(full_year_quarter_capacity, partial_months // 3)
    )
    unemployment_quarters = int(
        (
            Decimal(min(planned_unemployment_months, remaining_months))
            / Decimal(3)
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    additional_quarters = max(additional_quarters - unemployment_quarters, 0)
    return current_quarters + additional_quarters


def _annual_agirc_arrco_points(annual_gross: Decimal) -> Decimal:
    tranche_one = min(annual_gross, ANNUAL_SOCIAL_SECURITY_CEILING_2026)
    tranche_two = min(
        max(annual_gross - ANNUAL_SOCIAL_SECURITY_CEILING_2026, ZERO),
        ANNUAL_SOCIAL_SECURITY_CEILING_2026 * Decimal(7),
    )
    return (
        tranche_one * AGIRC_ARRCO_T1_POINT_RATE
        + tranche_two * AGIRC_ARRCO_T2_POINT_RATE
    ) / AGIRC_ARRCO_POINT_PURCHASE_PRICE_2026


def _growth_progress(scenario: IncomeGrowthScenario, ratio: float) -> float:
    if scenario == "strong_early":
        return ratio**0.5
    if scenario == "strong_late":
        return ratio**2
    return ratio


def _simulated_end_gross(
    annual_gross: Decimal,
    scenario: IncomeGrowthScenario,
    future_annual_gross: Decimal | None,
    years_to_target: Decimal,
) -> Decimal:
    if scenario == "none":
        return annual_gross
    if future_annual_gross is not None:
        return future_annual_gross
    factor = (1 + float(DEFAULT_ANNUAL_GROWTH_RATE)) ** float(years_to_target)
    return _money(annual_gross * Decimal(str(factor)))


def _full_time_income_at(
    annual_gross: Decimal,
    end_annual_gross: Decimal,
    scenario: IncomeGrowthScenario,
    elapsed_months: int,
    target_months: int,
) -> Decimal:
    if scenario == "none" or target_months <= 0 or annual_gross <= ZERO:
        return annual_gross
    ratio = min(elapsed_months / target_months, 1)
    progress = _growth_progress(scenario, ratio)
    factor = (float(end_annual_gross) / float(annual_gross)) ** progress
    return _money(annual_gross * Decimal(str(factor)))


def _future_incomes(
    annual_gross: Decimal,
    end_annual_gross: Decimal,
    scenario: IncomeGrowthScenario,
    remaining_months: int,
    target_months: int,
    future_work_percentage: int,
    planned_unemployment_months: int,
) -> list[Decimal]:
    if remaining_months <= 0:
        return []
    employment_ratio = (
        Decimal(max(remaining_months - planned_unemployment_months, 0))
        / Decimal(remaining_months)
    )
    work_ratio = Decimal(future_work_percentage) / HUNDRED
    incomes: list[Decimal] = []
    elapsed_months = 0
    while elapsed_months < remaining_months:
        period_months = min(12, remaining_months - elapsed_months)
        elapsed_months += period_months
        full_time_income = _full_time_income_at(
            annual_gross,
            end_annual_gross,
            scenario,
            elapsed_months,
            target_months,
        )
        incomes.append(
            _money(
                full_time_income
                * work_ratio
                * employment_ratio
                * Decimal(period_months)
                / MONTHS_PER_YEAR
            )
        )
    return incomes


def _average_base_salary(
    annual_gross: Decimal,
    current_quarters: int,
    future_incomes: list[Decimal],
) -> Decimal:
    historical_years = max(1, current_quarters // 4)
    career_incomes = [annual_gross] * historical_years + future_incomes
    best_years = sorted(career_incomes, reverse=True)[:25]
    capped = [
        min(income, ANNUAL_SOCIAL_SECURITY_CEILING_2026)
        for income in best_years
    ]
    return sum(capped, ZERO) / Decimal(len(capped))


def calculate_pension_projection(
    payslips: Iterable[PaySlipAmount],
    *,
    birth_year: int,
    birth_month: int,
    target_retirement_age: int,
    current_quarters: int,
    required_quarters: int,
    today: date,
    income_growth_scenario: IncomeGrowthScenario = "regular",
    future_annual_gross: Decimal | None = None,
    future_work_percentage: int = 100,
    planned_unemployment_months: int = 0,
) -> PensionProjection | None:
    payslip_list = list(payslips)
    annual_gross, payslip_count, covered_years = _reference_annual_gross(payslip_list)
    if annual_gross <= ZERO:
        return None

    current_age_months = (today.year - birth_year) * 12 + today.month - birth_month
    target_age_months = target_retirement_age * 12
    months_to_target = max(target_age_months - current_age_months, 0)
    end_annual_gross = _simulated_end_gross(
        annual_gross,
        income_growth_scenario,
        future_annual_gross,
        Decimal(months_to_target) / MONTHS_PER_YEAR,
    )
    work_ratio = Decimal(future_work_percentage) / HUNDRED
    income_evolution = [
        PensionIncomePoint(
            age_years=current_age_months // 12,
            annual_gross=annual_gross,
        )
    ]
    elapsed_months = 12
    while elapsed_months < months_to_target:
        income_evolution.append(
            PensionIncomePoint(
                age_years=(current_age_months + elapsed_months) // 12,
                annual_gross=_money(
                    _full_time_income_at(
                        annual_gross,
                        end_annual_gross,
                        income_growth_scenario,
                        elapsed_months,
                        months_to_target,
                    )
                    * work_ratio
                ),
            )
        )
        elapsed_months += 12
    if months_to_target > 0:
        income_evolution.append(
            PensionIncomePoint(
                age_years=target_retirement_age,
                annual_gross=_money(end_annual_gross * work_ratio),
            )
        )

    legal_age = legal_retirement_age(birth_year)
    cutoff_year = birth_year + 21
    required_early_quarters = 4 if birth_month >= 10 else 5
    quarter_calculation, _ = calculate_payslip_quarters(payslip_list)
    entered_early_quarters = sum(
        year.validated_quarters
        for year in quarter_calculation
        if year.year <= cutoff_year
    )
    projected_quarters_at_63 = _projected_quarters(
        current_quarters,
        birth_year,
        birth_month,
        63,
        0,
        today,
        annual_gross,
        future_work_percentage,
        planned_unemployment_months,
    )
    if entered_early_quarters < required_early_quarters:
        long_career_status: LongCareerStatus = "insufficient_early_records"
    elif projected_quarters_at_63 < required_quarters:
        long_career_status = "insufficient_projected_quarters"
    else:
        long_career_status = "eligible"
    long_career = LongCareerAssessment(
        status=long_career_status,
        cutoff_year=cutoff_year,
        required_early_quarters=required_early_quarters,
        entered_early_quarters=entered_early_quarters,
        projected_quarters_at_63=projected_quarters_at_63,
        required_total_quarters=required_quarters,
    )

    scenario_ages: list[tuple[ProjectionKind, int, int]] = []
    if long_career.status == "eligible":
        scenario_ages.append(("long_career", 63, 0))
    if (
        (target_retirement_age, 0) != legal_age
        and target_retirement_age != 67
        and not (
            target_retirement_age == 63
            and long_career.status == "eligible"
        )
    ):
        scenario_ages.append(("target", target_retirement_age, 0))
    scenario_ages.extend(
        [
            ("legal_age", legal_age[0], legal_age[1]),
            ("full_rate_automatic", 67, 0),
        ]
    )

    scenarios: list[PensionProjectionScenario] = []
    for kind, age_years, age_months in sorted(
        scenario_ages, key=lambda item: (item[1], item[2])
    ):
        projected_quarters = _projected_quarters(
            current_quarters,
            birth_year,
            birth_month,
            age_years,
            age_months,
            today,
            annual_gross,
            future_work_percentage,
            planned_unemployment_months,
        )
        missing_quarters = max(required_quarters - projected_quarters, 0)
        discount_quarters = (
            0 if kind == "full_rate_automatic" else min(missing_quarters, MAX_DISCOUNT_QUARTERS)
        )
        months_after_legal_age = max(
            (age_years - legal_age[0]) * 12 + age_months - legal_age[1],
            0,
        )
        premium_quarters = min(
            max(projected_quarters - required_quarters, 0),
            months_after_legal_age // 3,
        )
        base_rate = FULL_BASE_RATE * (
            Decimal(1)
            - DISCOUNT_PER_MISSING_QUARTER * Decimal(discount_quarters)
            + DISCOUNT_PER_MISSING_QUARTER * Decimal(premium_quarters)
        )
        duration_ratio = min(
            Decimal(projected_quarters) / Decimal(required_quarters),
            Decimal(1),
        )
        retirement_age_months = age_years * 12 + age_months
        remaining_months = max(retirement_age_months - current_age_months, 0)
        future_incomes = _future_incomes(
            annual_gross,
            end_annual_gross,
            income_growth_scenario,
            remaining_months,
            months_to_target,
            future_work_percentage,
            planned_unemployment_months,
        )
        average_base_salary = _average_base_salary(
            annual_gross,
            current_quarters,
            future_incomes,
        )
        base_annual = (
            average_base_salary
            * base_rate
            * duration_ratio
        )
        historical_points = (
            _annual_agirc_arrco_points(annual_gross)
            * Decimal(current_quarters)
            / QUARTERS_PER_YEAR
        )
        future_points = sum(
            (_annual_agirc_arrco_points(income) for income in future_incomes),
            ZERO,
        )
        complementary_annual = (
            historical_points + future_points
        ) * AGIRC_ARRCO_POINT_VALUE_2026
        base_monthly = _money(base_annual / MONTHS_PER_YEAR)
        complementary_monthly = _money(complementary_annual / MONTHS_PER_YEAR)
        scenarios.append(
            PensionProjectionScenario(
                kind=kind,
                age_years=age_years,
                age_months=age_months,
                projected_quarters=projected_quarters,
                base_monthly_pension=base_monthly,
                complementary_monthly_pension=complementary_monthly,
                total_monthly_pension=base_monthly + complementary_monthly,
            )
        )

    return PensionProjection(
        reference_annual_gross=annual_gross,
        payslip_count=payslip_count,
        covered_years=covered_years,
        annual_social_security_ceiling=ANNUAL_SOCIAL_SECURITY_CEILING_2026,
        simulated_end_annual_gross=_money(end_annual_gross * work_ratio),
        income_evolution=income_evolution,
        scenarios=scenarios,
        long_career=long_career,
    )
