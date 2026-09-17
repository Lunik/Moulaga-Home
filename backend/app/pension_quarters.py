"""Estimate French pension quarters from pay-slip gross salaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class PaySlipAmount(Protocol):
    period: str
    gross_salary: Decimal


@dataclass(frozen=True)
class PensionQuarterYear:
    year: int
    gross_salary: Decimal
    quarter_threshold: Decimal
    validated_quarters: int
    next_quarter_remaining: Decimal | None


# One quarter is validated from the gross salary subject to pension
# contributions. Since 2014, the threshold is 150 times the hourly minimum
# wage in force on 1 January; before then it was 200 times that wage.
# Source: https://www.legislation.lassuranceretraite.fr/#/bareme
QUARTER_THRESHOLDS: dict[int, Decimal] = {
    2002: Decimal("1334.00"),
    2003: Decimal("1366.00"),
    2004: Decimal("1438.00"),
    2005: Decimal("1522.00"),
    2006: Decimal("1606.00"),
    2007: Decimal("1654.00"),
    2008: Decimal("1688.00"),
    2009: Decimal("1742.00"),
    2010: Decimal("1772.00"),
    2011: Decimal("1800.00"),
    2012: Decimal("1844.00"),
    2013: Decimal("1886.00"),
    2014: Decimal("1429.50"),
    2015: Decimal("1441.50"),
    2016: Decimal("1450.50"),
    2017: Decimal("1464.00"),
    2018: Decimal("1482.00"),
    2019: Decimal("1504.50"),
    2020: Decimal("1522.50"),
    2021: Decimal("1537.50"),
    2022: Decimal("1585.50"),
    2023: Decimal("1690.50"),
    2024: Decimal("1747.50"),
    2025: Decimal("1782.00"),
    2026: Decimal("1803.00"),
}

ZERO = Decimal("0.00")


def calculate_payslip_quarters(
    payslips: Iterable[PaySlipAmount],
) -> tuple[list[PensionQuarterYear], list[int]]:
    gross_by_year: dict[int, Decimal] = {}
    for payslip in payslips:
        year = int(payslip.period[:4])
        gross_by_year[year] = gross_by_year.get(year, ZERO) + max(
            payslip.gross_salary, ZERO
        )

    calculations: list[PensionQuarterYear] = []
    unsupported_years: list[int] = []
    for year, gross_salary in sorted(gross_by_year.items(), reverse=True):
        threshold = QUARTER_THRESHOLDS.get(year)
        if threshold is None:
            unsupported_years.append(year)
            continue

        validated_quarters = min(4, int(gross_salary // threshold))
        next_quarter_remaining = (
            None
            if validated_quarters == 4
            else max(
                threshold * Decimal(validated_quarters + 1) - gross_salary,
                ZERO,
            )
        )
        calculations.append(
            PensionQuarterYear(
                year=year,
                gross_salary=gross_salary,
                quarter_threshold=threshold,
                validated_quarters=validated_quarters,
                next_quarter_remaining=next_quarter_remaining,
            )
        )

    return calculations, unsupported_years
