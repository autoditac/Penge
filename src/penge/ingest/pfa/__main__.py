"""CLI entry point for the PFA pension loader.

Usage::

    penge-pfa --entity-name "Rouven Sacha" path/to/pensionsoversigt.pdf

Multiple PDFs can be passed; they are loaded in the order given
inside a single DB transaction. The CLI reads ``DATABASE_URL``
(or the assembled ``POSTGRES_*`` set) the same way as the other
``penge-*`` ingest commands.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from sqlalchemy import create_engine

from penge.ingest.pfa.loader import load_files
from penge.ops.sentry import init_sentry

log = logging.getLogger("penge.ingest.pfa")


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
        prog="penge-pfa",
        description="Load PFA Pensionsoversigt PDFs into Postgres.",
    )
    p.add_argument(
        "pdf",
        nargs="+",
        metavar="PDF",
        help="PFA Pensionsoversigt PDF (one or more).",
    )
    p.add_argument(
        "--entity-name",
        required=True,
        metavar="NAME",
        help="Local entity (person) name to attach the PFA accounts to.",
    )
    p.add_argument(
        "--no-ocr",
        action="store_true",
        help="Disable the OCR fallback (raise instead of falling back when a "
        "PDF has no embedded text).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_sentry(component="ingest.pfa")

    engine = create_engine(_database_url())
    result = load_files(
        engine,
        pdf_paths=args.pdf,
        entity_name=args.entity_name,
        allow_ocr=not args.no_ocr,
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
