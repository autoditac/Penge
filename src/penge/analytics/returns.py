"""Time-weighted and money-weighted return computations.

The mart layer (``mart_returns_daily``, ADR-0039) produces one row per
scope and day with begin value, end value, net external flow, and the
daily return factor, independently in EUR and DKK. This module
chain-links those daily sub-periods into window returns (TWR) and
solves the internal rate of return of the investor's cashflows (MWR /
XIRR). It is intentionally pure: no database access, no I/O.

Conventions (see ADR-0039):

- Start-of-day flows: ``factor = end / (begin + flow)``.
- Monetary inputs are ``Decimal``; rates are returned as ``float``
  because a rate is a measurement, not an amount of money.
- A day with no capital at risk (``begin + flow <= 0`` and ``end ==
  0``) is dormant and skipped. A day where value appears without a
  flow to explain it is a data gap and raises :class:`ReturnsError`
  instead of fabricating a return.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Final

import pydantic

__all__ = [
    "MIN_ANNUALIZE_DAYS",
    "ReturnPoint",
    "ReturnsError",
    "TwrSummary",
    "chain_linked_twr",
    "mwr_from_series",
    "twr_summary",
    "xirr",
]

MIN_ANNUALIZE_DAYS: Final = 30
"""Windows shorter than this many days report no annualized return."""

_DAYS_PER_YEAR: Final = 365.25

_XIRR_LOW: Final = -0.9999
_XIRR_HIGH: Final = 10.0
_XIRR_TOLERANCE: Final = 1e-12
_XIRR_MAX_ITERATIONS: Final = 200
_XIRR_MIN_FLOWS: Final = 2


class ReturnsError(Exception):
    """Raised when a return series cannot be computed faithfully."""


class ReturnPoint(pydantic.BaseModel):
    """One daily sub-period of a return series in one measurement currency.

    Mirrors a ``mart_returns_daily`` row restricted to a single scope
    and currency view.

    Args:
        as_of: Calendar date of the sub-period (its end).
        begin_value: Previous day's end-of-day value.
        end_value: End-of-day value.
        net_flow: Net external flow dated ``as_of`` (start-of-day
            convention), positive into the scope.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    as_of: date
    begin_value: Decimal
    end_value: Decimal
    net_flow: Decimal = Decimal("0")

    @property
    def denominator(self) -> Decimal:
        """Capital at risk during the day (begin value plus flow)."""
        return self.begin_value + self.net_flow

    @property
    def factor(self) -> Decimal | None:
        """Daily growth factor, or None when no capital was at risk."""
        if self.denominator <= 0:
            return None
        return self.end_value / self.denominator


class TwrSummary(pydantic.BaseModel):
    """Chain-linked time-weighted return over a window of daily points.

    Args:
        start_date: First sub-period date in the window.
        end_date: Last sub-period date in the window.
        days: Calendar length of the window in days (inclusive count
            of sub-periods).
        cumulative_factor: Product of all defined daily factors.
        cumulative_return: ``cumulative_factor - 1``.
        annualized_return: Actual/365.25 annualization, or None for
            windows shorter than :data:`MIN_ANNUALIZE_DAYS`.
        dormant_days: Sub-periods skipped because no capital was at
            risk.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start_date: date
    end_date: date
    days: int
    cumulative_factor: Decimal
    cumulative_return: Decimal
    annualized_return: float | None
    dormant_days: int


def chain_linked_twr(factors: list[Decimal]) -> Decimal:
    """Multiply daily growth factors into a cumulative factor.

    Args:
        factors: Daily growth factors (e.g. 1.01 for a +1% day).

    Returns:
        The cumulative growth factor; ``Decimal("1")`` for an empty
        list.
    """
    cumulative = Decimal("1")
    for factor in factors:
        cumulative *= factor
    return cumulative


def twr_summary(points: list[ReturnPoint]) -> TwrSummary:
    """Chain-link contiguous daily points into a window TWR.

    Args:
        points: Daily sub-periods, strictly ascending by date and
            value-continuous (each ``begin_value`` equals the previous
            ``end_value``), exactly as emitted by ``mart_returns_daily``
            for one scope and currency view.

    Returns:
        The chain-linked summary over the window.

    Raises:
        ReturnsError: If ``points`` is empty, out of order, not
            value-continuous, or contains a day where value exists
            without capital at risk (a data gap).
    """
    if not points:
        msg = "cannot compute TWR over an empty series"
        raise ReturnsError(msg)

    factors: list[Decimal] = []
    dormant = 0
    previous: ReturnPoint | None = None
    for point in points:
        if previous is not None:
            if point.as_of <= previous.as_of:
                msg = f"return points out of order at {point.as_of.isoformat()}"
                raise ReturnsError(msg)
            if point.begin_value != previous.end_value:
                msg = (
                    f"value series is discontinuous at {point.as_of.isoformat()}: "
                    f"begin {point.begin_value} != previous end {previous.end_value}"
                )
                raise ReturnsError(msg)
        factor = point.factor
        if factor is None:
            if point.end_value != 0:
                msg = (
                    f"value {point.end_value} on {point.as_of.isoformat()} "
                    "has no capital at risk to explain it (data gap)"
                )
                raise ReturnsError(msg)
            dormant += 1
        else:
            factors.append(factor)
        previous = point

    cumulative = chain_linked_twr(factors)
    days = (points[-1].as_of - points[0].as_of).days + 1
    annualized: float | None = None
    if days >= MIN_ANNUALIZE_DAYS:
        annualized = float(cumulative) ** (_DAYS_PER_YEAR / days) - 1
    return TwrSummary(
        start_date=points[0].as_of,
        end_date=points[-1].as_of,
        days=days,
        cumulative_factor=cumulative,
        cumulative_return=cumulative - 1,
        annualized_return=annualized,
        dormant_days=dormant,
    )


def _npv(rate: float, flows: list[tuple[date, float]], t0: date) -> float:
    """Net present value of dated flows at an annual ``rate``."""
    total = 0.0
    for flow_date, amount in flows:
        years = (flow_date - t0).days / _DAYS_PER_YEAR
        total += amount / (1.0 + rate) ** years
    return total


def xirr(cashflows: list[tuple[date, Decimal]]) -> float | None:
    """Solve the annualized internal rate of return of dated cashflows.

    Investor sign convention: contributions are negative, withdrawals
    and the final liquidation value positive.

    The solver bisects the NPV function over annual rates in
    ``(-99.99%, +1000%)`` — deterministic and divergence-free. Solver
    internals use ``float``; the result is a rate, not money.

    Args:
        cashflows: Dated, signed flows. Order does not matter.

    Returns:
        The annualized rate, or None when no root exists in the
        bracket (e.g. all flows have the same sign) or fewer than two
        nonzero flows are given.
    """
    flows = [(d, float(a)) for d, a in cashflows if a != 0]
    if len(flows) < _XIRR_MIN_FLOWS:
        return None
    has_negative = any(a < 0 for _, a in flows)
    has_positive = any(a > 0 for _, a in flows)
    if not (has_negative and has_positive):
        return None

    t0 = min(d for d, _ in flows)
    low, high = _XIRR_LOW, _XIRR_HIGH
    npv_low = _npv(low, flows, t0)
    npv_high = _npv(high, flows, t0)
    if (npv_low > 0) == (npv_high > 0):
        # No sign change over the open bracket: no solvable rate.
        return None

    for _ in range(_XIRR_MAX_ITERATIONS):
        mid = (low + high) / 2
        npv_mid = _npv(mid, flows, t0)
        if abs(npv_mid) < _XIRR_TOLERANCE or (high - low) / 2 < _XIRR_TOLERANCE:
            return mid
        if (npv_mid > 0) == (npv_low > 0):
            low, npv_low = mid, npv_mid
        else:
            high = mid
    return (low + high) / 2


def mwr_from_series(points: list[ReturnPoint]) -> float | None:
    """Money-weighted return (XIRR) of a daily value/flow series.

    Builds the investor cashflow view of the window: buying the
    opening value at the previous day's close (when ``begin_value``
    was struck), contributing/withdrawing each ``net_flow`` on its
    date, and liquidating the closing value at the end — then solves
    XIRR.

    Args:
        points: Daily sub-periods as for :func:`twr_summary`.

    Returns:
        The annualized money-weighted rate, or None when the window is
        empty or XIRR has no solution.
    """
    if not points:
        return None
    first = points[0]
    flows: list[tuple[date, Decimal]] = [(first.as_of - timedelta(days=1), -first.begin_value)]
    flows.extend((point.as_of, -point.net_flow) for point in points)
    flows.append((points[-1].as_of, points[-1].end_value))
    return xirr(flows)
