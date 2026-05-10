"""CLI entry point for the Growney / Sutor Bank Depotauszug loader.

Usage::

    penge-growney --entity-name "Rouven Sacha" path/to/depotauszug.pdf

You can pass multiple PDFs in one invocation; they are loaded in
the order given inside a single DB transaction. The CLI reads
``DATABASE_URL`` (or the assembled ``POSTGRES_*`` set) the same
way as ``penge-nordnet``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from penge.ingest.growney.loader import load_files
from penge.ops.sentry import init_sentry

log = logging.getLogger("penge.ingest.growney")


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
        prog="penge-growney",
        description="Load Sutor Bank Depotauszug PDFs (Growney) into Postgres.",
    )
    p.add_argument(
        "pdf",
        nargs="+",
        metavar="PDF",
        help="Sutor Bank Depotauszug PDF (one or more).",
    )
    p.add_argument(
        "--entity-name",
        required=True,
        metavar="NAME",
        help="Local entity (person) name to attach the depot to.",
    )
    p.add_argument(
        "--account-name",
        default=None,
        metavar="NAME",
        help="Override account.name (default: 'Growney <strategy>').",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_sentry(component="ingest.growney")

    from sqlalchemy import create_engine

    engine = create_engine(_database_url())
    result = load_files(
        engine,
        pdf_paths=args.pdf,
        entity_name=args.entity_name,
        account_name=args.account_name,
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
