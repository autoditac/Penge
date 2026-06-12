"""Deterministic investment-returns analytics (TWR and MWR/XIRR).

Pure, database-free helpers that consume the daily value/flow series
materialized by ``mart_returns_daily`` (one scope and one measurement
currency at a time) and compute chain-linked time-weighted returns and
money-weighted returns. Methodology and conventions are recorded in
ADR-0039 and documented in ``docs/analytics/returns.md``.
"""

from penge.analytics.returns import (
    MIN_ANNUALIZE_DAYS,
    ReturnPoint,
    ReturnsError,
    TwrSummary,
    chain_linked_twr,
    mwr_from_series,
    twr_summary,
    xirr,
)

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
