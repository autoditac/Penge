"""Unit tests for scheduled Enable Banking and dbt orchestration."""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from penge.api.connections import service, store
from penge.ops import net_worth_refresh_cli
from penge.ops.net_worth_refresh import (
    DbtRefreshError,
    DbtRunner,
    LockUnavailableError,
    RefreshStateError,
    dbt_environment,
    exclusive_lock,
    refresh_write_intent,
    run_refresh,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from sqlalchemy.engine import Engine

    from penge.ingest.enablebanking.client import Client


def _record(*, provider: str = "gls") -> store.ConnectionRecord:
    now = datetime.now(UTC)
    return store.ConnectionRecord(
        id=uuid.uuid4(),
        provider=provider,
        aspsp_name="Synthetic Bank",
        aspsp_country="DE",
        entity_name="Synthetic Person",
        status=store.STATUS_AUTHORIZED,
        state=None,
        authorization_id="authorization",
        session_id="session",
        valid_until=now + timedelta(days=30),
        accounts=[],
        last_sync_at=None,
        last_sync_status=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


class _RefreshRecorder:
    def __init__(self, *, error: DbtRefreshError | None = None) -> None:
        self.calls = 0
        self.error = error

    def refresh(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def test_run_refresh_isolates_connection_failures_and_runs_dbt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = _record(provider="gls")
    second = _record(provider="lunar")
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [first, second])
    recorded_error_ids: list[uuid.UUID] = []
    monkeypatch.setattr(
        store,
        "record_error",
        lambda engine, connection_id, **kwargs: recorded_error_ids.append(connection_id),
    )

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, on_write
        if connection_id == first.id:
            raise RuntimeError("synthetic internal failure")
        return service.SyncOutcome(
            record=second,
            transactions=1,
            holding_snapshots=1,
            writes=2,
        )

    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=tmp_path / "pending",
        sync_connection=sync_connection,
    )

    assert summary.failed_connections == 1
    assert summary.successful_connections == 1
    assert summary.data_changed is True
    assert summary.dbt_status == "succeeded"
    assert summary.ok is False
    assert dbt.calls == 1
    assert recorded_error_ids == [first.id]


def test_run_refresh_clears_new_intent_after_prewrite_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, connection_id, on_write
        raise service.ConnectionError(step="sync", message="session unavailable")

    pending = tmp_path / "pending"
    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=pending,
        sync_connection=sync_connection,
    )

    assert summary.failed_connections == 1
    assert summary.data_changed is False
    assert summary.dbt_status == "skipped_no_changes"
    assert dbt.calls == 0
    assert not pending.exists()


def test_run_refresh_skips_dbt_when_upserts_are_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])
    pending = tmp_path / "pending"

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, connection_id, on_write
        assert pending.exists()
        return service.SyncOutcome(
            record=record,
            transactions=0,
            holding_snapshots=0,
            writes=0,
        )

    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=pending,
        sync_connection=sync_connection,
    )

    assert summary.ok is True
    assert summary.data_changed is False
    assert summary.dbt_status == "skipped_no_changes"
    assert dbt.calls == 0
    assert not pending.exists()


def test_run_refresh_reports_dbt_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, connection_id, on_write
        return service.SyncOutcome(
            record=record,
            transactions=1,
            holding_snapshots=0,
            writes=1,
        )

    dbt = _RefreshRecorder(error=DbtRefreshError("synthetic dbt failure"))
    pending = tmp_path / "pending"
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=pending,
        sync_connection=sync_connection,
    )

    assert summary.ok is False
    assert summary.dbt_status == "failed"
    assert summary.error == "synthetic dbt failure"
    assert pending.exists()


def test_run_refresh_retries_pending_dbt_after_idempotent_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, connection_id, on_write
        return service.SyncOutcome(
            record=record,
            transactions=0,
            holding_snapshots=0,
            writes=0,
        )

    pending = tmp_path / "pending"
    pending.touch()
    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=pending,
        sync_connection=sync_connection,
    )

    assert summary.data_changed is False
    assert summary.dbt_status == "succeeded"
    assert summary.ok is True
    assert dbt.calls == 1
    assert not pending.exists()


def test_run_refresh_marks_partial_writes_before_connection_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, connection_id
        assert on_write is not None
        on_write(3)
        raise service.ConnectionError(step="sync", message="second account failed")

    pending = tmp_path / "pending"
    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=pending,
        sync_connection=sync_connection,
    )

    assert summary.failed_connections == 1
    assert summary.data_changed is True
    assert summary.connections[0].writes == 3
    assert summary.dbt_status == "succeeded"
    assert dbt.calls == 1
    assert not pending.exists()


def test_run_refresh_blocks_sync_when_pending_marker_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])
    monkeypatch.setattr(
        "penge.ops.net_worth_refresh.mark_refresh_pending",
        MagicMock(side_effect=OSError("synthetic unwritable state directory")),
    )

    sync_connection = MagicMock()
    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=tmp_path / "pending",
        sync_connection=sync_connection,
    )

    assert summary.failed_connections == 1
    assert summary.data_changed is False
    assert summary.dbt_status == "skipped_no_changes"
    assert summary.error == "could not persist pending refresh marker: OSError"
    assert summary.ok is False
    assert dbt.calls == 0
    sync_connection.assert_not_called()


def test_run_refresh_counts_writes_from_failed_fallback_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = _record()
    monkeypatch.setattr(store, "list_eligible_connections", lambda engine, as_of: [record])

    def sync_connection(
        engine: Engine,
        client: Client,
        *,
        connection_id: uuid.UUID,
        on_write: Callable[[int], None] | None = None,
    ) -> service.SyncOutcome:
        _ = engine, client, connection_id
        assert on_write is not None
        on_write(2)
        return service.SyncOutcome(
            record=record,
            transactions=0,
            holding_snapshots=0,
            writes=0,
        )

    dbt = _RefreshRecorder()
    summary = run_refresh(
        MagicMock(),
        MagicMock(),
        dbt_runner=dbt,
        pending_refresh_file=tmp_path / "pending",
        sync_connection=sync_connection,
    )

    assert summary.connections[0].writes == 2
    assert summary.data_changed is True
    assert summary.dbt_status == "succeeded"
    assert summary.ok is True
    assert dbt.calls == 1


def test_refresh_write_intent_tracks_changes_and_clears_zero_write_runs(
    tmp_path: Path,
) -> None:
    lock_file = tmp_path / "refresh.lock"
    pending_file = tmp_path / "pending"

    with refresh_write_intent(
        lock_file=lock_file,
        pending_refresh_file=pending_file,
    ):
        assert pending_file.exists()
    assert not pending_file.exists()

    with refresh_write_intent(
        lock_file=lock_file,
        pending_refresh_file=pending_file,
    ) as observe_write:
        observe_write(2)
    assert pending_file.exists()


def test_exclusive_lock_reports_unwritable_state_path(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("synthetic", encoding="utf-8")

    with (
        pytest.raises(
            RefreshStateError,
            match="could not open refresh lock",
        ),
        exclusive_lock(parent_file / "refresh.lock"),
    ):
        pytest.fail("lock unexpectedly acquired")


def test_dbt_runner_validates_shadow_before_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def command_runner(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        _ = cwd, env
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(DbtRunner, "_drop_shadow_schemas", lambda self: None)
    promote = MagicMock()
    monkeypatch.setattr(DbtRunner, "_promote_shadow_schemas", promote)
    runner = DbtRunner(
        MagicMock(),
        project_dir=tmp_path / "dbt",
        profiles_dir=tmp_path / "dbt",
        database_url="postgresql+psycopg://user:pass@db:5432/penge",
        command_runner=command_runner,
    )

    runner.refresh()

    assert [command[1] for command in commands] == ["build"]
    assert "refresh" in commands[0]
    assert "--select" not in commands[0]
    promote.assert_called_once_with()


def test_dbt_runner_does_not_touch_live_after_shadow_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def command_runner(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        _ = cwd, env
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="synthetic failure")

    monkeypatch.setattr(DbtRunner, "_drop_shadow_schemas", lambda self: None)
    promote = MagicMock()
    monkeypatch.setattr(DbtRunner, "_promote_shadow_schemas", promote)
    runner = DbtRunner(
        MagicMock(),
        project_dir=tmp_path / "dbt",
        profiles_dir=tmp_path / "dbt",
        database_url="postgresql+psycopg://user:pass@db:5432/penge",
        command_runner=command_runner,
    )

    with pytest.raises(DbtRefreshError, match="live marts were not changed"):
        runner.refresh()

    assert len(commands) == 1
    assert commands[0][1] == "build"
    promote.assert_not_called()


def test_dbt_runner_promotes_both_schemas_in_one_transaction(tmp_path: Path) -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    schema_result = MagicMock()
    schema_result.scalars.return_value = [
        "analytics_staging",
        "analytics_marts",
        "analytics_refresh_staging",
        "analytics_refresh_marts",
    ]
    connection.execute.side_effect = [schema_result, *[MagicMock() for _ in range(8)]]
    runner = DbtRunner(
        engine,
        project_dir=tmp_path / "dbt",
        profiles_dir=tmp_path / "dbt",
        database_url="postgresql://worker@db:5432/penge",
    )

    runner._promote_shadow_schemas()

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert 'ALTER SCHEMA "analytics_staging" RENAME TO "analytics_previous_staging"' in statements
    assert 'ALTER SCHEMA "analytics_marts" RENAME TO "analytics_previous_marts"' in statements
    assert 'ALTER SCHEMA "analytics_refresh_staging" RENAME TO "analytics_staging"' in statements
    assert 'ALTER SCHEMA "analytics_refresh_marts" RENAME TO "analytics_marts"' in statements
    engine.begin.assert_called_once_with()


def test_dbt_environment_uses_url_without_leaking_password_to_command() -> None:
    env = dbt_environment(
        "postgresql+psycopg://worker:secret@database:5544/finance",
        base={"PATH": "/bin"},
    )

    assert env == {
        "PATH": "/bin",
        "PGHOST": "database",
        "PGPORT": "5544",
        "PGUSER": "worker",
        "PGPASSWORD": "secret",
        "PGDATABASE": "finance",
    }


def test_exclusive_lock_rejects_concurrent_owner(tmp_path: Path) -> None:
    path = tmp_path / "refresh.lock"

    with exclusive_lock(path), pytest.raises(LockUnavailableError), exclusive_lock(path):
        pytest.fail("second owner unexpectedly acquired the lock")


def test_cli_disabled_summary_is_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ENABLEBANKING_APPLICATION_ID", raising=False)
    monkeypatch.delenv("ENABLEBANKING_KEY_PATH", raising=False)

    exit_code = net_worth_refresh_cli.main(["--dry-run"])
    output = capsys.readouterr()

    assert exit_code == 2
    assert '"error":"Enable Banking connections are disabled"' in output.out
    assert output.err == ""
