"""CLI entry point for the scheduled net-worth refresh."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from penge.api.connections.config import ConnectionsConfig
from penge.api.imports.engine import get_import_engine
from penge.ingest.enablebanking.client import Client
from penge.ops.net_worth_refresh import (
    DbtRunner,
    LockUnavailableError,
    RefreshSummary,
    exclusive_lock,
    run_refresh,
)
from penge.web.config import database_url


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
        description="Sync eligible Enable Banking connections and refresh household net worth."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible connections without syncing or running dbt.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=state_dir / "refresh.lock",
        help="Shared advisory lock path.",
    )
    parser.add_argument(
        "--pending-refresh-file",
        type=Path,
        default=state_dir / "pending",
        help="Durable marker retained until dbt refresh succeeds.",
    )
    parser.add_argument(
        "--dbt-project-dir",
        type=Path,
        default=Path("/app/dbt"),
        help="dbt project directory.",
    )
    parser.add_argument(
        "--dbt-profiles-dir",
        type=Path,
        default=Path("/app/dbt"),
        help="dbt profiles directory.",
    )
    return parser


def _error_summary(message: str) -> RefreshSummary:
    now = datetime.now(UTC).isoformat()
    return RefreshSummary(
        started_at=now,
        completed_at=now,
        eligible_connections=0,
        successful_connections=0,
        failed_connections=0,
        data_changed=False,
        dbt_status="not_run",
        dry_run=False,
        connections=(),
        error=message,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the scheduled refresh and print one JSON summary."""
    args = _parser().parse_args(argv)
    _configure_logging(verbose=args.verbose)

    config = ConnectionsConfig.from_env()
    if not config.enabled:
        summary = _error_summary("Enable Banking connections are disabled")
        print(summary.to_json())
        return 2

    engine = None
    client = None
    try:
        engine = get_import_engine()
        client = Client.from_env()
        runner = DbtRunner(
            engine,
            project_dir=args.dbt_project_dir,
            profiles_dir=args.dbt_profiles_dir,
            database_url=database_url(),
        )
        with exclusive_lock(args.lock_file):
            summary = run_refresh(
                engine,
                client,
                dbt_runner=runner,
                pending_refresh_file=args.pending_refresh_file,
                dry_run=args.dry_run,
            )
    except LockUnavailableError as exc:
        summary = _error_summary(str(exc))
    except Exception as exc:
        logging.getLogger("penge.ops.net_worth_refresh").error(
            "refresh_failed code=%s",
            type(exc).__name__,
        )
        summary = _error_summary("refresh failed before completion")
    finally:
        if client is not None:
            client.close()
        if engine is not None:
            engine.dispose()

    print(summary.to_json())
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
