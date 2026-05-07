"""CLI entry point for the ECB FX loader.

Usage:

    penge-ecb-fx --latest        # fetch eurofxref-daily.xml
    penge-ecb-fx --since 2014-01-01  # full history, slice >= cutoff
    penge-ecb-fx --90d           # trailing 90 days

Reads ``DATABASE_URL`` (or assembled ``POSTGRES_*``) just like Alembic.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from .loader import Feed, fetch, parse, upsert

log = logging.getLogger("penge.ingest.ecb_fx")


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
        prog="penge-ecb-fx",
        description="Load ECB daily FX reference rates into the fx_rate table.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--latest", action="store_true", help="latest business day only")
    g.add_argument("--90d", dest="last_90d", action="store_true", help="trailing 90 days")
    g.add_argument(
        "--since",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="full history, filtered to as_of >= this date",
    )
    p.add_argument("--dry-run", action="store_true", help="parse but do not write to DB")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.latest:
        feed = Feed.DAILY
        cutoff: date | None = None
    elif args.last_90d:
        feed = Feed.LAST_90D
        cutoff = None
    else:
        feed = Feed.HISTORICAL
        cutoff = args.since

    log.info("fetching %s", feed.value)
    xml_bytes = fetch(feed)
    rates = list(parse(xml_bytes))
    if cutoff is not None:
        rates = [r for r in rates if r.as_of >= cutoff]
    log.info("parsed %d rate rows", len(rates))

    if args.dry_run:
        log.info("dry-run: skipping DB write")
        return 0

    # Lazy import so --dry-run / --help work without DB drivers installed.
    from sqlalchemy import create_engine

    engine = create_engine(_database_url())
    written = upsert(engine, rates)
    log.info("upserted %d rows", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
