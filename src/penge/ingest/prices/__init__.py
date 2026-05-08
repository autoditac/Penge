"""Instrument price loader (yfinance + Nordnet cross-check).

Source: Yahoo Finance via ``yfinance``. Daily close prices are written to
the ``price_history`` table, keyed by ``(instrument_id, as_of)``.

Public API:

- :data:`MIC_TO_YAHOO_SUFFIX` — mapping from ISO-10383 MIC to the Yahoo
  ticker suffix used for that exchange (e.g. ``XCSE → .CO``).
- :func:`resolve_yahoo_symbol` — best-effort mapping of an instrument
  (ticker, MIC, ISIN) to a Yahoo Finance symbol. Pure function.
- :func:`fetch_history` — call yfinance and return EOD closes as
  ``ParsedPrice`` records (network IO).
- :func:`cross_check` — compute the relative discrepancy between two
  close prices for sanity-checking against Nordnet holdings exports.
- :func:`upsert` — idempotent ``INSERT ... ON CONFLICT`` against
  ``price_history``.
- :class:`Instrument` / :class:`ParsedPrice` — record types.
"""

from .loader import (
    DISCREPANCY_THRESHOLD,
    MIC_TO_YAHOO_SUFFIX,
    Instrument,
    ParsedPrice,
    cross_check,
    fetch_history,
    list_instruments,
    resolve_yahoo_symbol,
    run,
    upsert,
)

__all__ = [
    "DISCREPANCY_THRESHOLD",
    "MIC_TO_YAHOO_SUFFIX",
    "Instrument",
    "ParsedPrice",
    "cross_check",
    "fetch_history",
    "list_instruments",
    "resolve_yahoo_symbol",
    "run",
    "upsert",
]
