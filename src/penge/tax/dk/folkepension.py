"""Folkepension modregning model — Danish state pension with means-testing (#131).

Folkepension consists of two components:

**Grundbeløb** (~7 191 DKK/month in 2026)
    Universal, paid to all who reach folkepensionsalderen.  Not means-tested.

**Pensionstillæg** (up to ~18 389 DKK/month single / ~8 993 DKK/month married)
    Means-tested supplement.  Reduced (modregnet) by **30.9 %** of private
    pension income above the annual threshold (~94 800 DKK in 2026).

For a user with ~75 000 DKK/month (900 000 DKK/year) in pension income the
tillæg will be entirely zeroed.

Folkepensionsalder schedule (as of 2026):
    - 67 until 2029
    - 68 from 2030
    - 69 from 2035 (subject to life-expectancy revision)

Usage::

    from decimal import Decimal
    from penge.tax.dk.folkepension import FolkepensionConfig, compute_folkepension

    result = compute_folkepension(FolkepensionConfig(
        civil_status="single",
        folkepension_age=67,
        annual_private_pension_income_dkk=Decimal("900000"),
    ))
    print(result.total_monthly_dkk)  # ≈ 7191 (only grundbeløb remains)

Integration with :class:`~penge.sim.payout.PayoutProjection`::

    from penge.tax.dk.folkepension import folkepension_from_payout

    result = folkepension_from_payout(
        projection,
        civil_status="single",
        folkepension_age=67,
        eur_per_dkk=Decimal("0.1341"),
    )

References:
    - Ankestyrelsen — https://www.ankestyrelsen.dk/satser/satser-for-folkepension
    - Borger.dk — https://www.borger.dk/pension-og-efterloen/folkepension
    - ADR-0029 — DK Topskat + Folkepension modules
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Literal

from penge.tax.dk.rates import (
    FOLKEPENSION_AGE_SCHEDULE,
    FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK,
    FOLKEPENSION_INCOME_THRESHOLD_DKK,
    FOLKEPENSION_MODREGNING_RATE,
    FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK,
    FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK,
)

if TYPE_CHECKING:
    from penge.sim.payout import PayoutProjection

__all__ = [
    "CivilStatus",
    "FolkepensionConfig",
    "FolkepensionError",
    "FolkepensionResult",
    "compute_folkepension",
    "folkepension_age_for_year",
    "folkepension_from_payout",
]

_TWO_DP = Decimal("0.01")
_MIN_FOLKEPENSION_AGE = 60

CivilStatus = Literal["single", "married"]


def _q(v: Decimal) -> Decimal:
    return v.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class FolkepensionError(Exception):
    """Raised when Folkepension inputs are inconsistent."""


@dataclass(frozen=True)
class FolkepensionConfig:
    """Parameters for a Folkepension computation.

    Attributes:
        civil_status: ``"single"`` or ``"married"``/cohabiting.  Determines
            the maximum pensionstillæg.
        folkepension_age: Age at which the person starts receiving Folkepension.
            Typically derived from :func:`folkepension_age_for_year`.
        annual_private_pension_income_dkk: Gross annual income from private
            pension instruments (Livrente + Ratepension).  Aldersforsikring
            lump sums are excluded as they are tax-free and not means-tested.
            Used to compute the modregning reduction of the tillæg.
        grundbeloeb_monthly_dkk: Monthly grundbeløb (override from
            :data:`~penge.tax.dk.rates.FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK`).
        tillaeg_max_monthly_dkk: Maximum monthly pensionstillæg (override;
            defaults to the 2026 value for the chosen ``civil_status``).
        modregning_rate: Fraction of excess private income that reduces the
            tillæg (default: ``FOLKEPENSION_MODREGNING_RATE``).
        income_threshold_dkk: Annual private-income threshold below which no
            modregning applies (default: ``FOLKEPENSION_INCOME_THRESHOLD_DKK``).
    """

    civil_status: CivilStatus
    folkepension_age: int
    annual_private_pension_income_dkk: Decimal
    grundbeloeb_monthly_dkk: Decimal = FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK
    tillaeg_max_monthly_dkk: Decimal | None = None  # resolved from civil_status if None
    modregning_rate: Decimal = FOLKEPENSION_MODREGNING_RATE
    income_threshold_dkk: Decimal = FOLKEPENSION_INCOME_THRESHOLD_DKK


@dataclass(frozen=True)
class FolkepensionResult:
    """Computed Folkepension entitlement after means-testing.

    Attributes:
        grundbeloeb_monthly_dkk: Universal grundbeløb (unchanged, not means-tested).
        tillaeg_before_modregning_dkk: Maximum tillæg for the civil status,
            before any income-based reduction.
        modregning_dkk: Monthly reduction applied to the tillæg due to private
            pension income exceeding the threshold.
        tillaeg_after_modregning_dkk: ``max(tillaeg_before - modregning, 0)``.
        total_monthly_dkk: ``grundbeloeb + tillaeg_after_modregning``.
    """

    grundbeloeb_monthly_dkk: Decimal
    tillaeg_before_modregning_dkk: Decimal
    modregning_dkk: Decimal
    tillaeg_after_modregning_dkk: Decimal
    total_monthly_dkk: Decimal


def folkepension_age_for_year(retirement_year: int) -> int:
    """Return the statutory folkepensionsalder for a given calendar year.

    Uses the schedule in :data:`~penge.tax.dk.rates.FOLKEPENSION_AGE_SCHEDULE`.
    Returns the highest age whose effective year is ``<= retirement_year``.

    Args:
        retirement_year: The calendar year the person retires.

    Returns:
        Statutory folkepensionsalder (integer).

    Raises:
        FolkepensionError: If ``retirement_year`` is before the earliest
            schedule entry.
    """
    effective_years = sorted(FOLKEPENSION_AGE_SCHEDULE.keys())
    if retirement_year < effective_years[0]:
        raise FolkepensionError(
            f"retirement_year {retirement_year} is before the earliest schedule entry "
            f"({effective_years[0]})"
        )
    age = FOLKEPENSION_AGE_SCHEDULE[effective_years[0]]
    for year in effective_years:
        if retirement_year >= year:
            age = FOLKEPENSION_AGE_SCHEDULE[year]
    return age


def compute_folkepension(config: FolkepensionConfig) -> FolkepensionResult:
    """Compute monthly Folkepension entitlement after means-testing.

    The modregning (monthly reduction) is computed as::

        annual_excess = max(annual_private_income - income_threshold, 0)
        annual_modregning = annual_excess * modregning_rate
        monthly_modregning = annual_modregning / 12

    The tillæg is then capped at zero from below::

        tillaeg_after = max(tillaeg_max - monthly_modregning, 0)

    Args:
        config: :class:`FolkepensionConfig` with all parameters.

    Returns:
        :class:`FolkepensionResult` with the computed entitlement.

    Raises:
        FolkepensionError: If any input amount is negative, or if
            ``folkepension_age`` is below 60.
    """
    if config.annual_private_pension_income_dkk < Decimal("0"):
        raise FolkepensionError("annual_private_pension_income_dkk must be >= 0")
    if config.grundbeloeb_monthly_dkk < Decimal("0"):
        raise FolkepensionError("grundbeloeb_monthly_dkk must be >= 0")
    if config.modregning_rate < Decimal("0") or config.modregning_rate > Decimal("1"):
        raise FolkepensionError("modregning_rate must be in [0, 1]")
    if config.income_threshold_dkk < Decimal("0"):
        raise FolkepensionError("income_threshold_dkk must be >= 0")
    if config.folkepension_age < _MIN_FOLKEPENSION_AGE:
        raise FolkepensionError("folkepension_age must be >= 60")

    tillaeg_max = _resolve_tillaeg_max(config)
    if tillaeg_max < Decimal("0"):
        raise FolkepensionError("tillaeg_max_monthly_dkk must be >= 0")

    annual_excess = max(
        config.annual_private_pension_income_dkk - config.income_threshold_dkk,
        Decimal("0"),
    )
    annual_modregning = annual_excess * config.modregning_rate
    monthly_modregning = _q(annual_modregning / Decimal("12"))

    tillaeg_after = _q(max(tillaeg_max - monthly_modregning, Decimal("0")))
    total = _q(config.grundbeloeb_monthly_dkk + tillaeg_after)

    return FolkepensionResult(
        grundbeloeb_monthly_dkk=_q(config.grundbeloeb_monthly_dkk),
        tillaeg_before_modregning_dkk=_q(tillaeg_max),
        modregning_dkk=monthly_modregning,
        tillaeg_after_modregning_dkk=tillaeg_after,
        total_monthly_dkk=total,
    )


def folkepension_from_payout(
    projection: PayoutProjection,
    *,
    civil_status: CivilStatus,
    folkepension_age: int,
    eur_per_dkk: Decimal,
    grundbeloeb_monthly_dkk: Decimal = FOLKEPENSION_GRUNDBELOEB_MONTHLY_DKK,
    tillaeg_max_monthly_dkk: Decimal | None = None,
    modregning_rate: Decimal = FOLKEPENSION_MODREGNING_RATE,
    income_threshold_dkk: Decimal = FOLKEPENSION_INCOME_THRESHOLD_DKK,
) -> FolkepensionResult:
    """Convenience wrapper: derive annual DK private-pension income from a
    :class:`~penge.sim.payout.PayoutProjection` and compute Folkepension.

    Converts ``total_monthly_gross_eur`` to annual DKK using ``eur_per_dkk``.
    Aldersforsikring is not included in the modregning base as it is tax-free.

    Args:
        projection: Output of :func:`~penge.sim.payout.compute_payout`.
        civil_status: ``"single"`` or ``"married"``.
        folkepension_age: Age at which Folkepension begins (use
            :func:`folkepension_age_for_year` to derive from a calendar year).
        eur_per_dkk: ECB/SKAT FX rate (e.g. ``Decimal("0.1341")``).
        grundbeloeb_monthly_dkk: Override grundbeløb (defaults to 2026 value).
        tillaeg_max_monthly_dkk: Override maximum tillæg (defaults to
            civil-status-specific 2026 value).
        modregning_rate: Override modregning rate (defaults to 2026 value).
        income_threshold_dkk: Override income threshold (defaults to 2026 value).

    Returns:
        :class:`FolkepensionResult` for the projected income.

    Raises:
        FolkepensionError: If ``eur_per_dkk`` is not positive.
    """
    if eur_per_dkk <= Decimal("0"):
        raise FolkepensionError("eur_per_dkk must be > 0")

    annual_eur = projection.total_monthly_gross_eur * Decimal("12")
    annual_dkk = annual_eur / eur_per_dkk

    config = FolkepensionConfig(
        civil_status=civil_status,
        folkepension_age=folkepension_age,
        annual_private_pension_income_dkk=annual_dkk,
        grundbeloeb_monthly_dkk=grundbeloeb_monthly_dkk,
        tillaeg_max_monthly_dkk=tillaeg_max_monthly_dkk,
        modregning_rate=modregning_rate,
        income_threshold_dkk=income_threshold_dkk,
    )
    return compute_folkepension(config)


def _resolve_tillaeg_max(config: FolkepensionConfig) -> Decimal:
    if config.tillaeg_max_monthly_dkk is not None:
        return config.tillaeg_max_monthly_dkk
    if config.civil_status == "single":
        return FOLKEPENSION_TILLAEG_SINGLE_MONTHLY_DKK
    return FOLKEPENSION_TILLAEG_MARRIED_MONTHLY_DKK
