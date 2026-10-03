"""CLI entry point for the scheduled public merchant-reference refresh."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from penge.api.connections.config import ConnectionsConfig
from penge.api.imports.engine import get_import_engine
from penge.api.merchant_reference.service import (
    ReferenceStoreError,
    RefreshResult,
    preview_release,
    refresh_index,
)
from penge.ingest.merchant_reference.nsi import NsiClient
from penge.ops.net_worth_refresh import LockUnavailableError, exclusive_lock


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _configure_logging(*, verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def _parser() -> argparse.ArgumentParser:
    state_dir = ConnectionsConfig.from_env().refresh_state_dir
    parser = argparse.ArgumentParser(
        description="Refresh the local public merchant-reference index from the NSI catalog."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the latest public release without downloading or changing state.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=state_dir / "refresh.lock",
        help="Shared advisory lock path.",
    )
    return parser


def _error_result(code: str) -> RefreshResult:
    return RefreshResult(
        status="failed",
        source_version=None,
        records_promoted=0,
        skipped_unchanged=False,
        error_code=code,
    )


def main(argv: list[str] | None = None) -> int:
    """Run one refresh attempt and print its sanitized JSON outcome."""
    args = _parser().parse_args(argv)
    _configure_logging(verbose=args.verbose)
    engine = None
    client: NsiClient | None = None
    try:
        engine = get_import_engine()
        client = NsiClient()
        with exclusive_lock(args.lock_file):
            result = (
                preview_release(engine, client) if args.dry_run else refresh_index(engine, client)
            )
    except LockUnavailableError:
        result = _error_result("refresh_lock_held")
    except ReferenceStoreError:
        result = _error_result("database_write_failed")
    except Exception as exc:
        logging.getLogger("penge.api.merchant_reference").error(
            "public_reference_worker_failed code=%s",
            type(exc).__name__,
        )
        result = _error_result("worker_failed")
    finally:
        if client is not None:
            client.close()
        if engine is not None:
            engine.dispose()

    print(result.to_json())
    return 0 if (result.ok or (args.dry_run and result.error_code is None)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
