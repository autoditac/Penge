"""Scheduled Enable Banking sync and guarded net-worth mart refresh."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, TextIO

from sqlalchemy import text
from sqlalchemy.engine import make_url

from penge.api.connections import service, store

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client

log = logging.getLogger("penge.ops.net_worth_refresh")

REFRESH_SCHEMAS = ("analytics_refresh_staging", "analytics_refresh_marts")
LIVE_SCHEMAS = ("analytics_staging", "analytics_marts")
PREVIOUS_SCHEMAS = ("analytics_previous_staging", "analytics_previous_marts")


class LockUnavailableError(RuntimeError):
    """Raised when another refresh process owns the shared lock."""


class DbtRefreshError(RuntimeError):
    """Raised when validation or live dbt refresh fails."""


class RefreshStateError(RuntimeError):
    """Raised when durable refresh intent cannot be managed safely."""


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


class _ExclusiveLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: TextIO | None = None

    def __enter__(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = self._path.open("a+", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_file.close()
            raise LockUnavailableError(f"refresh lock is already held: {self._path}") from exc
        except OSError as exc:
            raise RefreshStateError(
                f"could not open refresh lock {self._path}: {type(exc).__name__}"
            ) from exc
        self._file = lock_file

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type, exc_value, traceback
        if self._file is not None:
            lock_file = self._file
            self._file = None
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


def exclusive_lock(path: Path) -> _ExclusiveLock:
    """Return a non-blocking advisory lock shared by all sync write paths."""
    return _ExclusiveLock(path)


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
        """Build/test a shadow graph, then atomically promote it."""
        self._drop_shadow_schemas()
        try:
            self._run(
                "build",
                "--target",
                "refresh",
                failure="shadow dbt build/test failed; live marts were not changed",
            )
            self._promote_shadow_schemas()
        finally:
            self._drop_shadow_schemas_best_effort()

    def _drop_shadow_schemas_best_effort(self) -> None:
        """Best-effort post-run cleanup of the now-unused shadow schema names.

        By the time this runs, ``refresh()`` has already determined its
        outcome: either a build/promotion failure already raised above, or
        ``_promote_shadow_schemas`` already committed the rename. A
        transient failure while dropping the leftover shadow schema names
        (which ``_promote_shadow_schemas`` renamed away on success, so
        ``DROP SCHEMA IF EXISTS`` is normally a no-op here) must not
        override that already-determined outcome with a false failure --
        doing so would misreport correctly promoted live marts as failed
        and leave the pending marker set for a redundant rebuild.
        """
        try:
            self._drop_shadow_schemas()
        except Exception as exc:
            log.error(
                "dbt_shadow_schema_cleanup_failed code=%s",
                type(exc).__name__,
            )

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

    def _promote_shadow_schemas(self) -> None:
        with self._engine.begin() as connection:
            available = set(
                connection.execute(
                    text(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name = ANY(:schemas)"
                    ),
                    {"schemas": [*LIVE_SCHEMAS, *REFRESH_SCHEMAS]},
                ).scalars()
            )
            missing_shadow = set(REFRESH_SCHEMAS) - available
            if missing_shadow:
                missing = ", ".join(sorted(missing_shadow))
                raise DbtRefreshError(f"shadow dbt build did not create schemas: {missing}")
            for previous in PREVIOUS_SCHEMAS:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{previous}" CASCADE'))
            for live, previous in zip(LIVE_SCHEMAS, PREVIOUS_SCHEMAS, strict=True):
                if live in available:
                    connection.execute(text(f'ALTER SCHEMA "{live}" RENAME TO "{previous}"'))
            for shadow, live in zip(REFRESH_SCHEMAS, LIVE_SCHEMAS, strict=True):
                connection.execute(text(f'ALTER SCHEMA "{shadow}" RENAME TO "{live}"'))
            for previous in PREVIOUS_SCHEMAS:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{previous}" CASCADE'))


class SyncFunction(Protocol):
    """Connection sync boundary with per-account write notification."""

    def __call__(
        self,
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome: ...


def mark_refresh_pending(path: Path) -> None:
    """Create (or touch) the durable pending-refresh marker at ``path``.

    Any caller that is about to invoke :class:`DbtRunner` and wants the
    scheduled worker to retry automatically on failure must call this
    before running dbt, so the marker survives even if the process is
    killed mid-refresh.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


@dataclass(slots=True)
class _WriteTracker:
    path: Path
    writes: int = 0
    error: str | None = None

    def observe(self, write_count: int) -> None:
        self.writes += write_count

    def prepare(self) -> bool:
        try:
            mark_refresh_pending(self.path)
        except OSError as exc:
            self._record_error("persist", exc)
            return False
        return True

    def is_refresh_pending(self) -> bool:
        if self.writes > 0:
            return True
        try:
            return self.path.exists()
        except OSError as exc:
            self._record_error("inspect", exc)
            return False

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            self._record_error("clear", exc)

    def _record_error(self, action: str, exc: OSError) -> None:
        self.error = f"could not {action} pending refresh marker: {type(exc).__name__}"
        log.error(
            "pending_refresh_marker_%s_failed path=%s code=%s",
            action,
            self.path,
            type(exc).__name__,
        )


class _RefreshWriteIntent:
    def __init__(self, *, lock_file: Path, pending_refresh_file: Path) -> None:
        self._lock = exclusive_lock(lock_file)
        self._tracker = _WriteTracker(pending_refresh_file)
        self._was_pending = False

    def __enter__(self) -> Callable[[int], None]:
        self._lock.__enter__()
        self._was_pending = self._tracker.is_refresh_pending()
        if not self._tracker.prepare():
            self._lock.__exit__(None, None, None)
            raise RefreshStateError(
                self._tracker.error or "could not persist pending refresh marker"
            )
        return self._tracker.observe

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._tracker.writes == 0 and not self._was_pending:
            self._tracker.clear()
        self._lock.__exit__(exc_type, exc_value, traceback)


def refresh_write_intent(
    *,
    lock_file: Path,
    pending_refresh_file: Path,
) -> _RefreshWriteIntent:
    """Serialize raw writes and retain durable intent when any row changes."""
    return _RefreshWriteIntent(
        lock_file=lock_file,
        pending_refresh_file=pending_refresh_file,
    )


def sync_connection_with_intent(
    engine: Engine,
    client: Client,
    *,
    connection_id: uuid.UUID,
    days: int,
    lock_file: Path,
    pending_refresh_file: Path,
) -> service.SyncOutcome:
    """Serialize an API sync and leave durable intent when it commits writes."""
    with refresh_write_intent(
        lock_file=lock_file,
        pending_refresh_file=pending_refresh_file,
    ) as observe_write:
        return service.sync(
            engine,
            client,
            connection_id=connection_id,
            days=days,
            on_write=observe_write,
        )


def _sync_one_connection(
    engine: Engine,
    client: Client,
    *,
    record: store.ConnectionRecord,
    sync_connection: SyncFunction,
    tracker: _WriteTracker,
) -> tuple[ConnectionSummary, bool]:
    writes_before = tracker.writes
    was_pending = tracker.is_refresh_pending()
    if not tracker.prepare():
        return (
            ConnectionSummary(
                connection_id=str(record.id),
                provider=record.provider,
                status="failed",
                error=tracker.error,
            ),
            True,
        )
    try:
        outcome = sync_connection(
            engine,
            client,
            connection_id=record.id,
            on_write=tracker.observe,
        )
    except service.ConnectionError as exc:
        if tracker.writes == writes_before and not was_pending:
            tracker.clear()
        summary = ConnectionSummary(
            connection_id=str(record.id),
            provider=record.provider,
            status="failed",
            writes=tracker.writes - writes_before,
            error=exc.message,
        )
        log.error(
            "connection_sync_failed connection_id=%s provider=%s step=%s code=%s",
            record.id,
            record.provider,
            exc.step,
            exc.code,
        )
        return summary, True
    except Exception as exc:
        if tracker.writes == writes_before and not was_pending:
            tracker.clear()
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
        log.error(
            "connection_sync_failed connection_id=%s provider=%s code=%s",
            record.id,
            record.provider,
            type(exc).__name__,
        )
        summary = ConnectionSummary(
            connection_id=str(record.id),
            provider=record.provider,
            status="failed",
            writes=tracker.writes - writes_before,
            error=error.message,
        )
        return summary, True

    observed_writes = tracker.writes - writes_before
    if outcome.writes > observed_writes:
        tracker.observe(outcome.writes - observed_writes)
    committed_writes = tracker.writes - writes_before
    if committed_writes == 0 and not was_pending:
        tracker.clear()
    log.info(
        "connection_sync_succeeded connection_id=%s provider=%s writes=%d",
        record.id,
        record.provider,
        committed_writes,
    )
    return (
        ConnectionSummary(
            connection_id=str(record.id),
            provider=record.provider,
            status="succeeded",
            transactions=outcome.transactions,
            holding_snapshots=outcome.holding_snapshots,
            writes=committed_writes,
        ),
        False,
    )


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
    failed = 0
    tracker = _WriteTracker(pending_refresh_file)
    for record in eligible:
        summary, did_fail = _sync_one_connection(
            engine,
            client,
            record=record,
            sync_connection=sync_connection,
            tracker=tracker,
        )
        summaries.append(summary)
        failed += int(did_fail)

    dbt_status = "skipped_no_changes"
    refresh_error: str | None = None
    if tracker.is_refresh_pending():
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
            tracker.clear()
            log.info("net_worth_refresh_succeeded writes=%d", tracker.writes)

    completed = datetime.now(UTC)
    return RefreshSummary(
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        eligible_connections=len(eligible),
        successful_connections=len(eligible) - failed,
        failed_connections=failed,
        data_changed=tracker.writes > 0,
        dbt_status=dbt_status,
        dry_run=False,
        connections=tuple(summaries),
        error=refresh_error or tracker.error,
    )


__all__ = [
    "ConnectionSummary",
    "DbtRefreshError",
    "DbtRunner",
    "LockUnavailableError",
    "RefreshStateError",
    "RefreshSummary",
    "dbt_environment",
    "exclusive_lock",
    "mark_refresh_pending",
    "refresh_write_intent",
    "run_refresh",
    "sync_connection_with_intent",
]
