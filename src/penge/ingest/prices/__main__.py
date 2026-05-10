"""CLI entry point for the instrument price loader.

Usage::

    penge-prices --since 2024-01-01            # full history from cutoff
    penge-prices --last-30d                    # trailing 30 days
    penge-prices --since 2024-01-01 \\
        --nordnet-holdings path/to/Depotoversigt*.csv \\
        # ↑ cross-check the latest yfinance close against Seneste kurs

Reads ``DATABASE_URL`` (or assembled ``POSTGRES_*``) just like Alembic.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from penge.ops.sentry import init_sentry

from .loader import (
    DISCREPANCY_THRESHOLD,
    Instrument,
    list_instruments,
    resolve_yahoo_symbol,
    run,
)

log = logging.getLogger("penge.ingest.prices")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER", "penge")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "penge")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="penge-prices",
        description=(
            "Load end-of-day instrument prices from Yahoo Finance into the price_history table."
        ),
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--since",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="fetch history from this date (inclusive)",
    )
    g.add_argument(
        "--last-30d",
        dest="last_30d",
        action="store_true",
        help="fetch the trailing 30 days only",
    )
    p.add_argument(
        "--nordnet-holdings",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "path to a Nordnet 'Depotoversigt' holdings CSV; supplies "
            "the latest Seneste kurs for cross-check. May be repeated."
        ),
    )
    p.add_argument(
        "--threshold",
        type=Decimal,
        default=DISCREPANCY_THRESHOLD,
        metavar="FRACTION",
        help=(
            "relative discrepancy threshold for cross-check warnings "
            f"(default {DISCREPANCY_THRESHOLD})"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "connect to the DB read-only, list instruments and resolve "
            "Yahoo symbols, then exit; skip yfinance fetch and DB writes"
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _build_nordnet_reference(
    holdings_paths: list[Path],
    instruments: list[Instrument],
) -> dict[UUID, Decimal]:
    """Build an instrument-id → Seneste kurs mapping from holdings CSVs.

    Matching strategy: when a holdings row exposes an ``isin`` it is
    matched against the instrument table by ISIN; otherwise we fall
    back to an exact ``name`` match (Nordnet's *Depotoversigt* CSV
    omits ISIN today, so name is the common path). Holdings rows that
    cannot be matched, or that lack ``last_price``, are skipped
    silently. Name matching is exact and case-sensitive, so genuine
    name collisions across different instruments will pick whichever
    row appears first in the instrument list.
    """
    if not holdings_paths:
        return {}

    # Lazy: only pull the Nordnet parser when actually requested.
    from penge.ingest.nordnet.parser import parse_holdings

    by_isin: dict[str, UUID] = {i.isin.upper(): i.instrument_id for i in instruments if i.isin}
    ref: dict[UUID, Decimal] = {}
    for path in holdings_paths:
        for h in parse_holdings(path):
            # ParsedHolding has no isin column today (Nordnet's holdings
            # CSV omits it); fall back to name match. Future Nordnet
            # exports may include ISIN — handle both.
            isin = getattr(h, "isin", None)
            instrument_id: UUID | None = None
            if isin and isin.upper() in by_isin:
                instrument_id = by_isin[isin.upper()]
            else:
                # Best-effort exact name match.
                for inst in instruments:
                    if inst.name == h.name:
                        instrument_id = inst.instrument_id
                        break
            if instrument_id is None or h.last_price is None:
                continue
            ref[instrument_id] = h.last_price
    return ref


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_sentry(component="ingest.prices")

    start = date.today() - timedelta(days=30) if args.last_30d else args.since

    # Lazy import so ``--help`` works without DB drivers installed.
    from sqlalchemy import create_engine

    engine = create_engine(_database_url())
    instruments = list_instruments(engine)

    if args.dry_run:
        resolved = 0
        for inst in instruments:
            symbol = resolve_yahoo_symbol(ticker=inst.ticker, mic=inst.mic, isin=inst.isin)
            if symbol is not None:
                resolved += 1
            log.info(
                "dry-run: instrument=%s ticker=%r mic=%r -> symbol=%r",
                inst.name,
                inst.ticker,
                inst.mic,
                symbol,
            )
        log.info(
            "dry-run: would fetch from %s; instruments_seen=%d resolved=%d",
            start,
            len(instruments),
            resolved,
        )
        return 0

    reference = _build_nordnet_reference(args.nordnet_holdings, instruments)
    log.info(
        "loading prices for %d instruments (%d cross-check refs)",
        len(instruments),
        len(reference),
    )

    stats = run(
        engine,
        start=start,
        nordnet_reference=reference if reference else None,
        threshold=args.threshold,
    )
    log.info(
        "instruments_seen=%d instruments_resolved=%d rows_written=%d warnings=%d",
        stats.instruments_seen,
        stats.instruments_resolved,
        stats.rows_written,
        stats.discrepancy_warnings,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
