"""Scheduled Enable Banking sync and guarded net-worth mart refresh."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import text
from sqlalchemy.engine import make_url

from penge.api.connections import service, store

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client

log = logging.getLogger("penge.ops.net_worth_refresh")

DBT_SELECTION = "+mart_net_worth_daily"
REFRESH_SCHEMAS = ("analytics_refresh_staging", "analytics_refresh_marts")


class LockUnavailableError(RuntimeError):
    """Raised when another refresh process owns the shared lock."""


class DbtRefreshError(RuntimeError):
    """Raised when validation or live dbt refresh fails."""


class CommandRunner(Protocol):
    """Typed subprocess boundary used by :class:`DbtRunner`."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


class RefreshRunner(Protocol):
    """dbt refresh boundary used by the connection orchestrator."""

    def refresh(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ConnectionSummary:
    """Sanitized outcome for one eligible connection."""

    connection_id: str
    provider: str
    status: str
    transactions: int = 0
    holding_snapshots: int = 0
    writes: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshSummary:
    """Machine-readable outcome of one scheduled run."""

    started_at: str
    completed_at: str
    eligible_connections: int
    successful_connections: int
    failed_connections: int
    data_changed: bool
    dbt_status: str
    dry_run: bool
    connections: tuple[ConnectionSummary, ...]
    error: str | None = None

    def to_json(self) -> str:
        """Serialize the concise CLI result."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @property
    def ok(self) -> bool:
        """Return whether every required operation succeeded."""
        return self.failed_connections == 0 and self.error is None


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed executable and arguments
        list(command),
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )


def dbt_environment(
    database_url: str,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build libpq variables for dbt without placing credentials in arguments."""
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise DbtRefreshError("dbt refresh requires a PostgreSQL DATABASE_URL")
    if url.host is None or url.database is None or url.username is None:
        raise DbtRefreshError("DATABASE_URL must include host, database, and username")

    env = dict(base or os.environ)
    env.update(
        {
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username,
            "PGDATABASE": url.database,
        }
    )
    if url.password is not None:
        env["PGPASSWORD"] = url.password
    return env


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Own a non-blocking advisory lock shared by host-mounted workers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockUnavailableError(f"refresh lock is already held: {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class DbtRunner:
    """Validate in shadow schemas before atomically rebuilding live tables."""

    def __init__(
        self,
        engine: Engine,
        *,
        project_dir: Path,
        profiles_dir: Path,
        database_url: str,
        command_runner: CommandRunner = _run_command,
    ) -> None:
        self._engine = engine
        self._project_dir = project_dir
        self._profiles_dir = profiles_dir
        self._env = dbt_environment(database_url)
        self._command_runner = command_runner

    def refresh(self) -> None:
        """Build/test a shadow graph, then refresh the validated live graph."""
        self._drop_shadow_schemas()
        try:
            self._run(
                "build",
                "--target",
                "refresh",
                "--select",
                DBT_SELECTION,
                "--indirect-selection",
                "cautious",
                failure="shadow dbt build/test failed; live marts were not changed",
            )
            self._run(
                "run",
                "--target",
                "dev",
                "--select",
                DBT_SELECTION,
                "--indirect-selection",
                "cautious",
                failure="live dbt refresh failed; dbt retained the prior net-worth table",
            )
        finally:
            self._drop_shadow_schemas()

    def _run(self, *arguments: str, failure: str) -> None:
        command = [
            "dbt",
            *arguments,
            "--project-dir",
            str(self._project_dir),
            "--profiles-dir",
            str(self._profiles_dir),
            "--no-use-colors",
        ]
        completed = self._command_runner(
            command,
            cwd=self._project_dir.parent,
            env=self._env,
        )
        if completed.returncode != 0:
            output = f"{completed.stdout}\n{completed.stderr}"[-2000:].replace("\n", " ")
            log.error(
                "dbt_command_failed command=%s returncode=%d output=%s",
                arguments[0],
                completed.returncode,
                output,
            )
            raise DbtRefreshError(failure)
        log.info("dbt_command_succeeded command=%s", arguments[0])

    def _drop_shadow_schemas(self) -> None:
        with self._engine.begin() as connection:
            for schema in REFRESH_SCHEMAS:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


class SyncFunction(Protocol):
    """Connection sync boundary with per-account write notification."""

    def __call__(
        self,
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[], None] | None = None,
    ) -> service.SyncOutcome: ...


def _mark_refresh_pending(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def run_refresh(
    engine: Engine,
    client: Client,
    *,
    dbt_runner: RefreshRunner,
    pending_refresh_file: Path,
    dry_run: bool = False,
    now: datetime | None = None,
    sync_connection: SyncFunction = service.sync,
) -> RefreshSummary:
    """Sync every eligible connection independently and conditionally run dbt."""
    started = now or datetime.now(UTC)
    eligible = store.list_eligible_connections(engine, as_of=started)
    if dry_run:
        completed = datetime.now(UTC)
        return RefreshSummary(
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            eligible_connections=len(eligible),
            successful_connections=0,
            failed_connections=0,
            data_changed=False,
            dbt_status="skipped_dry_run",
            dry_run=True,
            connections=tuple(
                ConnectionSummary(
                    connection_id=str(record.id),
                    provider=record.provider,
                    status="eligible",
                )
                for record in eligible
            ),
        )

    summaries: list[ConnectionSummary] = []
    writes = 0
    failed = 0
    for record in eligible:
        try:
            outcome = sync_connection(
                engine,
                client,
                connection_id=record.id,
                on_write=lambda: _mark_refresh_pending(pending_refresh_file),
            )
        except service.ConnectionError as exc:
            failed += 1
            summaries.append(
                ConnectionSummary(
                    connection_id=str(record.id),
                    provider=record.provider,
                    status="failed",
                    error=exc.message,
                )
            )
            log.error(
                "connection_sync_failed connection_id=%s provider=%s step=%s code=%s",
                record.id,
                record.provider,
                exc.step,
                exc.code,
            )
        except Exception as exc:
            failed += 1
            error = service.ConnectionError(
                step="sync",
                message="unexpected internal sync failure",
                code=type(exc).__name__,
            )
            try:
                store.record_error(
                    engine,
                    record.id,
                    error=error.as_error_payload(),
                    status=record.status,
                    is_sync=True,
                )
            except Exception as record_exc:
                log.error(
                    "connection_error_record_failed connection_id=%s provider=%s code=%s",
                    record.id,
                    record.provider,
                    type(record_exc).__name__,
                )
            summaries.append(
                ConnectionSummary(
                    connection_id=str(record.id),
                    provider=record.provider,
                    status="failed",
                    error=error.message,
                )
            )
            log.error(
                "connection_sync_failed connection_id=%s provider=%s code=%s",
                record.id,
                record.provider,
                type(exc).__name__,
            )
        else:
            writes += outcome.writes
            if outcome.writes > 0:
                _mark_refresh_pending(pending_refresh_file)
            summaries.append(
                ConnectionSummary(
                    connection_id=str(record.id),
                    provider=record.provider,
                    status="succeeded",
                    transactions=outcome.transactions,
                    holding_snapshots=outcome.holding_snapshots,
                    writes=outcome.writes,
                )
            )
            log.info(
                "connection_sync_succeeded connection_id=%s provider=%s writes=%d",
                record.id,
                record.provider,
                outcome.writes,
            )

    dbt_status = "skipped_no_changes"
    refresh_error: str | None = None
    refresh_required = writes > 0 or pending_refresh_file.exists()
    if refresh_required:
        try:
            dbt_runner.refresh()
        except DbtRefreshError as exc:
            dbt_status = "failed"
            refresh_error = str(exc)
            log.error("net_worth_refresh_failed error=%s", exc)
        except Exception as exc:
            dbt_status = "failed"
            refresh_error = "unexpected dbt refresh failure"
            log.error("net_worth_refresh_failed code=%s", type(exc).__name__)
        else:
            dbt_status = "succeeded"
            pending_refresh_file.unlink(missing_ok=True)
            log.info("net_worth_refresh_succeeded writes=%d", writes)

    completed = datetime.now(UTC)
    return RefreshSummary(
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        eligible_connections=len(eligible),
        successful_connections=len(eligible) - failed,
        failed_connections=failed,
        data_changed=writes > 0,
        dbt_status=dbt_status,
        dry_run=False,
        connections=tuple(summaries),
        error=refresh_error,
    )


__all__ = [
    "DBT_SELECTION",
    "ConnectionSummary",
    "DbtRefreshError",
    "DbtRunner",
    "LockUnavailableError",
    "RefreshSummary",
    "dbt_environment",
    "exclusive_lock",
    "run_refresh",
]
