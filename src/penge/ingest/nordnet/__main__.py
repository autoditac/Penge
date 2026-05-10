"""CLI entry point for the Nordnet loader.

Usage::

    penge-nordnet \\
        --transactions /path/to/20260507-...csv \\
        --holdings "/path/to/Depotoversigt for kontonummer 60109543, 7.5.2026.csv" \\
        --holdings "/path/to/Depotoversigt for kontonummer 60183456, 7.5.2026.csv" \\
        --accounts-config config/nordnet-accounts.yaml

Reads ``DATABASE_URL`` (or assembled ``POSTGRES_*``) just like the
ECB FX loader.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from sqlalchemy import create_engine

from penge.ingest.nordnet.config import load_accounts_config
from penge.ingest.nordnet.loader import load_files
from penge.ops.sentry import init_sentry

log = logging.getLogger("penge.ingest.nordnet")


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
        prog="penge-nordnet",
        description="Load Nordnet (DK) CSV exports into Postgres.",
    )
    p.add_argument(
        "--transactions",
        required=True,
        metavar="PATH",
        help="Nordnet transaction CSV (UTF-16LE, tab-separated).",
    )
    p.add_argument(
        "--holdings",
        action="append",
        default=[],
        metavar="PATH",
        help="Holdings CSV (Depotoversigt). May be repeated.",
    )
    p.add_argument(
        "--accounts-config",
        required=True,
        metavar="PATH",
        help="YAML config mapping kontonummer -> entity + account kind.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_sentry(component="ingest.nordnet")

    cfg = load_accounts_config(args.accounts_config)
    engine = create_engine(_database_url())

    result = load_files(
        engine,
        transactions_csv=args.transactions,
        holdings_csvs=args.holdings,
        accounts_config=cfg,
    )
    log.info(
        "loaded entities=%d accounts=%d instruments=%d transactions=%d holdings=%d",
        result.entities,
        result.accounts,
        result.instruments,
        result.transactions,
        result.holding_snapshots,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
