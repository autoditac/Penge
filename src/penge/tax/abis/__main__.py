"""CLI for the ABIS list ingestor.

Usage::

    penge-abis ingest path/to/abis.csv
    penge-abis override --isin DE0002635281 --treatment lagerbeskatning
    penge-abis override --isin DE0002635281 --clear

Reads ``DATABASE_URL`` (or the ``POSTGRES_*`` 5-tuple) from env.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine

from penge.tax.abis.constants import TREATMENT_VALUES
from penge.tax.abis.loader import (
    apply_manual_override,
    clear_manual_override,
    load_abis_csv,
)

log = logging.getLogger("penge.tax.abis")


def _build_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB")
    if not (user and password and db):
        raise SystemExit("DATABASE_URL is unset and POSTGRES_USER/PASSWORD/DB are not all set")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="penge-abis",
        description="Skat ABIS list ingestor and instrument tax-treatment manager.",
    )
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Parse a Skat ABIS CSV and write classifications.")
    ingest.add_argument("csv_path", help="Path to the Skat ABIS CSV.")

    override = sub.add_parser(
        "override",
        help="Apply or clear a sticky manual treatment for one ISIN.",
    )
    override.add_argument("--isin", required=True)
    treat_group = override.add_mutually_exclusive_group(required=True)
    treat_group.add_argument(
        "--treatment",
        choices=TREATMENT_VALUES,
        help="Force this treatment with source='manual'.",
    )
    treat_group.add_argument(
        "--clear",
        action="store_true",
        help="Drop a previous manual override; let the next ABIS import re-derive.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = create_engine(_build_database_url())

    if args.cmd == "ingest":
        result = load_abis_csv(engine, csv_path=args.csv_path)
        log.info(
            "ABIS ingest: rows=%d matched=%d unmatched=%d obs=%d " "classified=%d cleared=%d",
            result.csv_rows,
            result.matched_isins,
            result.unmatched_isins,
            result.listing_observations,
            result.instruments_classified,
            result.instruments_cleared,
        )
        # Keep the CLI quiet by default; emit a one-line summary on stdout
        # so shells / cron can grep it.
        sys.stdout.write(
            f"abis: rows={result.csv_rows} matched={result.matched_isins} "
            f"unmatched={result.unmatched_isins} obs={result.listing_observations} "
            f"classified={result.instruments_classified} cleared={result.instruments_cleared}\n"
        )
        return 0

    if args.cmd == "override":
        if args.clear:
            ok = clear_manual_override(engine, isin=args.isin)
            sys.stdout.write(
                f"abis: cleared override for {args.isin}: {'yes' if ok else 'no-op'}\n"
            )
            return 0 if ok else 1
        ok = apply_manual_override(engine, isin=args.isin, treatment=args.treatment)
        sys.stdout.write(
            f"abis: set {args.isin} -> {args.treatment} (manual): "
            f"{'ok' if ok else 'no instrument with that ISIN'}\n"
        )
        return 0 if ok else 1

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
