"""Instrument price loader — fetch (yfinance), parse, upsert, cross-check.

The module is structured so the only piece that touches the network or
yfinance / pandas is :func:`fetch_history`. Everything else is pure
Python and unit-testable in isolation.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Default tolerance used by :func:`cross_check`. Discrepancies strictly
#: above this fraction are surfaced as warnings.
DISCREPANCY_THRESHOLD: Decimal = Decimal("0.01")  # 1 %

#: Mapping of ISO-10383 MIC to the Yahoo Finance ticker suffix used for
#: that listing venue. Empty string means "no suffix" (US listings).
MIC_TO_YAHOO_SUFFIX: dict[str, str] = {
    # United States
    "XNYS": "",
    "XNAS": "",
    "ARCX": "",
    "BATS": "",
    # Denmark
    "XCSE": ".CO",
    # Sweden
    "XSTO": ".ST",
    # Norway
    "XOSL": ".OL",
    # Germany
    "XETR": ".DE",
    "XFRA": ".F",
    "XBER": ".BE",
    "XMUN": ".MU",
    "XSTU": ".SG",
    # United Kingdom
    "XLON": ".L",
    # France
    "XPAR": ".PA",
    # Netherlands
    "XAMS": ".AS",
    # Italy
    "XMIL": ".MI",
    # Switzerland
    "XSWX": ".SW",
    "XVTX": ".VX",
    # Spain
    "XMAD": ".MC",
}


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Instrument:
    """Subset of ``raw.instrument`` columns needed by the loader."""

    instrument_id: UUID
    name: str
    kind: str
    currency: str
    isin: str | None
    ticker: str | None
    mic: str | None


@dataclass(frozen=True, slots=True)
class ParsedPrice:
    """One (instrument, day, close) tuple ready for upsert."""

    instrument_id: UUID
    as_of: date
    close: Decimal
    currency: str
    source: str


# --------------------------------------------------------------------------- #
# Yahoo symbol resolution (pure)
# --------------------------------------------------------------------------- #


def resolve_yahoo_symbol(
    *,
    ticker: str | None,
    mic: str | None,
    isin: str | None = None,
) -> str | None:
    """Best-effort map an instrument to a Yahoo Finance symbol.

    Resolution order:

    1. If ``ticker`` already contains a venue suffix (``"."`` in it),
       return it unchanged.
    2. If both ``ticker`` and a known ``mic`` are given, return
       ``f"{ticker}{MIC_TO_YAHOO_SUFFIX[mic]}"``.
    3. If only ``ticker`` is given, return it (assume US listing).
    4. Otherwise return ``None`` — ISIN-only resolution requires Yahoo
       Search (network) and is left to the caller to decide.
    """
    if ticker:
        clean = ticker.strip()
        if not clean:
            return None
        if "." in clean:
            return clean
        if mic and mic in MIC_TO_YAHOO_SUFFIX:
            suffix = MIC_TO_YAHOO_SUFFIX[mic]
            return f"{clean}{suffix}" if suffix else clean
        return clean
    return None


# --------------------------------------------------------------------------- #
# Cross-check (pure)
# --------------------------------------------------------------------------- #


def cross_check(yfinance_close: Decimal, reference_close: Decimal) -> Decimal:
    """Return the absolute relative discrepancy between two close prices.

    ``abs(yfinance_close - reference_close) / reference_close``. The
    caller compares the result against :data:`DISCREPANCY_THRESHOLD`
    (or its own threshold) and decides whether to log.

    Raises ``ValueError`` if ``reference_close`` is zero.
    """
    if reference_close == 0:
        raise ValueError("reference_close must be non-zero")
    return abs(yfinance_close - reference_close) / abs(reference_close)


# --------------------------------------------------------------------------- #
# Network — yfinance
# --------------------------------------------------------------------------- #


def fetch_history(
    symbol: str,
    *,
    start: date,
    end: date | None = None,
    instrument_id: UUID,
    currency: str,
    source: str = "yfinance",
) -> Iterator[ParsedPrice]:
    """Fetch EOD closes for ``symbol`` from Yahoo Finance.

    yfinance returns a pandas DataFrame indexed by timestamp with a
    ``Close`` column. We coerce each row into a :class:`ParsedPrice`
    using ``Decimal(repr(float(close)))`` to avoid binary-float drift.

    The ``end`` parameter, if given, follows yfinance semantics
    (exclusive). When omitted, defaults to ``start + 1 day``-style
    "today" via the yfinance default.
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    kwargs: dict[str, object] = {
        "start": start.isoformat(),
        "auto_adjust": False,
        "actions": False,
    }
    if end is not None:
        kwargs["end"] = end.isoformat()

    df = ticker.history(**kwargs)
    if df is None or df.empty:
        log.warning("yfinance returned no rows for %s", symbol)
        return

    if "Close" not in df.columns:
        log.warning("yfinance frame for %s has no Close column", symbol)
        return

    for ts, close in df["Close"].items():
        if close is None:
            continue
        # ``ts`` is a pandas Timestamp; ``.date()`` strips tz/time.
        as_of = ts.date()
        try:
            close_float = float(close)
        except (TypeError, ValueError):
            log.warning("could not coerce close=%r for %s on %s", close, symbol, as_of)
            continue
        if not math.isfinite(close_float):
            log.warning("skipping non-finite close=%r for %s on %s", close, symbol, as_of)
            continue
        close_dec = Decimal(repr(close_float))
        yield ParsedPrice(
            instrument_id=instrument_id,
            as_of=as_of,
            close=close_dec,
            currency=currency,
            source=source,
        )


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


def list_instruments(engine: Engine) -> list[Instrument]:
    """Return every row of ``raw.instrument`` as an :class:`Instrument`.

    Synthetic cash instruments (``kind = 'cash'``) are excluded — they
    have no quoted price.
    """
    from sqlalchemy import MetaData, Table, select

    meta = MetaData()
    inst = Table("instrument", meta, autoload_with=engine)
    stmt = select(
        inst.c.id,
        inst.c.name,
        inst.c.kind,
        inst.c.currency,
        inst.c.isin,
        inst.c.ticker,
        inst.c.mic,
    ).where(inst.c.kind != "cash")

    out: list[Instrument] = []
    with engine.begin() as conn:
        for row in conn.execute(stmt):
            out.append(
                Instrument(
                    instrument_id=row.id,
                    name=row.name,
                    kind=row.kind,
                    currency=row.currency,
                    isin=row.isin,
                    ticker=row.ticker,
                    mic=row.mic,
                )
            )
    return out


def upsert(engine: Engine, prices: Iterable[ParsedPrice]) -> int:
    """Write ``prices`` to ``price_history`` idempotently.

    Conflict target: ``(instrument_id, as_of)``. On conflict we refresh
    ``close``, ``currency``, and ``source`` so a re-run after a
    yfinance restatement updates the row in place.
    """
    from sqlalchemy import MetaData, Table
    from sqlalchemy.dialects.postgresql import insert

    payload = [
        {
            "instrument_id": p.instrument_id,
            "as_of": p.as_of,
            "close": p.close,
            "currency": p.currency,
            "source": p.source,
        }
        for p in prices
    ]
    if not payload:
        return 0

    meta = MetaData()
    price_history = Table("price_history", meta, autoload_with=engine)
    stmt = insert(price_history).values(payload)
    stmt = stmt.on_conflict_do_update(
        constraint="ux_price_history__instrument_id_as_of",
        set_={
            "close": stmt.excluded.close,
            "currency": stmt.excluded.currency,
            "source": stmt.excluded.source,
        },
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    return len(payload)


# --------------------------------------------------------------------------- #
# Convenience runner
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RunStats:
    """Aggregate counters returned by :func:`run`."""

    instruments_seen: int
    instruments_resolved: int
    rows_written: int
    discrepancy_warnings: int


def run(
    engine: Engine,
    *,
    start: date,
    end: date | None = None,
    nordnet_reference: dict[UUID, Decimal] | None = None,
    threshold: Decimal = DISCREPANCY_THRESHOLD,
) -> RunStats:
    """Resolve every non-cash instrument, fetch its history, upsert.

    :param nordnet_reference: optional mapping of ``instrument_id`` →
        the latest Nordnet *Seneste kurs* for that instrument. When
        provided, the loader compares it against the most recent
        yfinance close and emits a warning per instrument whose
        relative discrepancy exceeds ``threshold``.
    """
    instruments = list_instruments(engine)
    resolved = 0
    rows_written = 0
    warnings = 0

    for inst in instruments:
        symbol = resolve_yahoo_symbol(ticker=inst.ticker, mic=inst.mic, isin=inst.isin)
        if symbol is None:
            log.info("skip %s: no ticker (isin=%s)", inst.name, inst.isin)
            continue
        resolved += 1
        prices = list(
            fetch_history(
                symbol,
                start=start,
                end=end,
                instrument_id=inst.instrument_id,
                currency=inst.currency,
            )
        )
        if not prices:
            continue

        rows_written += upsert(engine, prices)

        if nordnet_reference is not None and inst.instrument_id in nordnet_reference:
            latest = max(prices, key=lambda p: p.as_of)
            try:
                rel = cross_check(latest.close, nordnet_reference[inst.instrument_id])
            except ValueError:
                continue
            if rel > threshold:
                warnings += 1
                log.warning(
                    "price discrepancy for %s (%s) on %s: yfinance=%s, " "nordnet=%s, rel=%.4f",
                    inst.name,
                    symbol,
                    latest.as_of,
                    latest.close,
                    nordnet_reference[inst.instrument_id],
                    float(rel),
                )

    return RunStats(
        instruments_seen=len(instruments),
        instruments_resolved=resolved,
        rows_written=rows_written,
        discrepancy_warnings=warnings,
    )
