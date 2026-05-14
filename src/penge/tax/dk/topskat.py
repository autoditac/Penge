"""Topskat exposure check for projected Danish pension income (#129).

Topskat is a 15 % surtax on personal income above the annual threshold
(~588 900 DKK in 2026, after personfradrag).  Pension drawdown from
Livrente and Ratepension counts as personal income; Aldersforsikring
lump-sum payouts are tax-free and do *not* count.

The combined marginal rate once in Topskat is approximately 52 %
(kommuneskat ~25 % + bundskat ~12 % + topskat 15 %).

Usage::

    from decimal import Decimal
    from penge.tax.dk.topskat import check_topskat_exposure

    warning = check_topskat_exposure(
        annual_pension_income_dkk=Decimal("900000"),
    )
    if warning.in_topskat:
        print(warning.estimated_topskat_dkk, warning.suggestion)

Integration with :class:`~penge.sim.payout.PayoutProjection`::

    from penge.tax.dk.topskat import topskat_from_payout

    warning = topskat_from_payout(projection, eur_per_dkk=Decimal("0.1341"))

References:
    - SKAT — https://skat.dk/data/satser/skattesatser-2026
    - ADR-0029 — DK Topskat + Folkepension modules
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from penge.tax.dk.rates import DK_TOPSKAT_RATE, DK_TOPSKAT_THRESHOLD_DKK

if TYPE_CHECKING:
    from penge.sim.payout import PayoutProjection

__all__ = [
    "TopskatError",
    "TopskatWarning",
    "check_topskat_exposure",
    "topskat_from_payout",
]

_TWO_DP = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)


class TopskatError(Exception):
    """Raised when inputs to Topskat computation are inconsistent."""


@dataclass(frozen=True)
class TopskatWarning:
    """Result of a Topskat exposure check.

    Attributes:
        annual_pension_income_dkk: Gross annual pension income (Livrente +
            Ratepension) fed into the check, in DKK.
        topskat_threshold_dkk: The annual threshold above which Topskat is
            levied (configurable; default is the 2026 value from
            :data:`~penge.tax.dk.rates.DK_TOPSKAT_THRESHOLD_DKK`).
        income_above_threshold_dkk: ``max(annual_pension_income - threshold, 0)``
            — the portion of income subject to Topskat.
        estimated_topskat_dkk: ``income_above_threshold * DK_TOPSKAT_RATE``
            — estimated annual Topskat liability in DKK.
        in_topskat: ``True`` if ``annual_pension_income_dkk`` exceeds the
            threshold.
        suggestion: Plain-language primary mitigation suggestion, or an empty
            string when income is below the threshold.
    """

    annual_pension_income_dkk: Decimal
    topskat_threshold_dkk: Decimal
    income_above_threshold_dkk: Decimal
    estimated_topskat_dkk: Decimal
    in_topskat: bool
    suggestion: str


def check_topskat_exposure(
    annual_pension_income_dkk: Decimal,
    *,
    topskat_threshold_dkk: Decimal = DK_TOPSKAT_THRESHOLD_DKK,
) -> TopskatWarning:
    """Check whether projected pension income falls into the Topskat bracket.

    The function is a **pure projection aid** — it does not account for
    personfradrag (personal allowance) or other deductions; the caller should
    subtract those before calling if a more precise estimate is needed.

    Args:
        annual_pension_income_dkk: Gross annual income from Livrente and
            Ratepension combined (DKK).  Aldersforsikring lump sums are
            tax-free and should *not* be included.
        topskat_threshold_dkk: Annual threshold above which the 15 % surtax
            applies.  Defaults to the 2026 value; pass an updated constant for
            future years.

    Returns:
        :class:`TopskatWarning` with the computed exposure and a primary
        mitigation suggestion.

    Raises:
        TopskatError: If ``annual_pension_income_dkk`` or
            ``topskat_threshold_dkk`` are negative.
    """
    if annual_pension_income_dkk < Decimal("0"):
        raise TopskatError("annual_pension_income_dkk must be >= 0")
    if topskat_threshold_dkk <= Decimal("0"):
        raise TopskatError("topskat_threshold_dkk must be > 0")

    above = max(annual_pension_income_dkk - topskat_threshold_dkk, Decimal("0"))
    topskat = _q(above * DK_TOPSKAT_RATE)
    in_topskat = above > Decimal("0")

    suggestion = _primary_suggestion(annual_pension_income_dkk, topskat_threshold_dkk)

    return TopskatWarning(
        annual_pension_income_dkk=_q(annual_pension_income_dkk),
        topskat_threshold_dkk=_q(topskat_threshold_dkk),
        income_above_threshold_dkk=_q(above),
        estimated_topskat_dkk=topskat,
        in_topskat=in_topskat,
        suggestion=suggestion,
    )


def _primary_suggestion(annual_income: Decimal, threshold: Decimal) -> str:
    """Return the most relevant plain-language mitigation suggestion."""
    if annual_income <= threshold:
        return ""
    excess_fraction = (annual_income - threshold) / threshold
    # Severity-ordered suggestions:
    #   > 100 % over threshold  → extend drawdown period aggressively
    #   > 30 % over threshold   → combination: drawdown extension + Aldersforsikring
    #   otherwise               → extend Ratepension drawdown period
    if excess_fraction > Decimal("1"):
        return (
            "Income is more than double the Topskat threshold. "
            "Consider extending Ratepension drawdown to the maximum 30-year period "
            "and redirecting future contributions to Aldersforsikring (tax-free lump sum) "
            "to reduce the annual taxable pension income."
        )
    if excess_fraction > Decimal("0.3"):
        return (
            "Consider extending the Ratepension drawdown period and increasing "
            "the Aldersforsikring allocation to shift taxable income below the Topskat threshold."
        )
    return (
        "Consider extending the Ratepension drawdown period to spread income "
        "over more years and reduce exposure to the Topskat bracket."
    )


def topskat_from_payout(
    projection: PayoutProjection,
    eur_per_dkk: Decimal,
    *,
    topskat_threshold_dkk: Decimal = DK_TOPSKAT_THRESHOLD_DKK,
) -> TopskatWarning:
    """Convenience wrapper: derive annual DK pension income from a
    :class:`~penge.sim.payout.PayoutProjection` and run the Topskat check.

    Converts the EUR-denominated ``total_monthly_gross_eur`` from the
    projection to DKK (annual) using ``eur_per_dkk``.
    Aldersforsikring is excluded because it is a one-off tax-free lump sum.

    Args:
        projection: Output of :func:`~penge.sim.payout.compute_payout`.
        eur_per_dkk: ECB/SKAT FX rate: how many EUR equals 1 DKK
            (e.g. ``Decimal("0.1341")`` for 1 DKK = 0.1341 EUR).
        topskat_threshold_dkk: Override the threshold (defaults to 2026 value).

    Returns:
        :class:`TopskatWarning` for the projected income.

    Raises:
        TopskatError: If ``eur_per_dkk`` is not positive.
    """
    if eur_per_dkk <= Decimal("0"):
        raise TopskatError("eur_per_dkk must be > 0")

    annual_eur = projection.total_monthly_gross_eur * Decimal("12")
    annual_dkk = annual_eur / eur_per_dkk
    return check_topskat_exposure(annual_dkk, topskat_threshold_dkk=topskat_threshold_dkk)
