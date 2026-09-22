"""Route tests for the WebUI-triggered dbt-only refresh (issue #285).

Uses a fake ``RefreshRunner`` (mirroring `tests/ops/test_net_worth_refresh.py`)
injected via FastAPI dependency overrides, so these tests exercise the real
locking/marker/error-mapping logic without a database or a real dbt build.
"""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from penge.api.app import create_app
from penge.api.routes import get_dbt_runner, get_refresh_state_dir
from penge.ops.net_worth_refresh import DbtRefreshError

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeRefreshRunner:
    """Fake `RefreshRunner` recording calls, optionally raising on refresh."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def refresh(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def refresh_state_dir(tmp_path: Path) -> Path:
    return tmp_path / "refresh-state"


@pytest.fixture
def meta_refresh_client(refresh_state_dir: Path) -> Iterator[tuple[TestClient, _FakeRefreshRunner]]:
    app = create_app()
    runner = _FakeRefreshRunner()
    app.dependency_overrides[get_dbt_runner] = lambda: runner
    app.dependency_overrides[get_refresh_state_dir] = lambda: refresh_state_dir
    with TestClient(app) as test_client:
        yield test_client, runner


def test_meta_refresh_succeeds_and_clears_the_pending_marker(
    meta_refresh_client: tuple[TestClient, _FakeRefreshRunner], refresh_state_dir: Path
) -> None:
    client, runner = meta_refresh_client
    refresh_state_dir.mkdir(parents=True)
    pending_file = refresh_state_dir / "pending"
    pending_file.write_text("2026-06-01T09:00:00Z", encoding="utf-8")

    response = client.post("/meta/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert "completed_at" in body
    assert runner.calls == 1
    assert not pending_file.exists()


def test_meta_refresh_succeeds_when_no_pending_marker_exists(
    meta_refresh_client: tuple[TestClient, _FakeRefreshRunner],
) -> None:
    client, runner = meta_refresh_client

    response = client.post("/meta/refresh")

    assert response.status_code == 200
    assert runner.calls == 1


def test_meta_refresh_maps_dbt_failure_to_502_and_preserves_the_marker(
    refresh_state_dir: Path,
) -> None:
    app = create_app()
    runner = _FakeRefreshRunner(error=DbtRefreshError("dbt build failed: model X"))
    app.dependency_overrides[get_dbt_runner] = lambda: runner
    app.dependency_overrides[get_refresh_state_dir] = lambda: refresh_state_dir
    refresh_state_dir.mkdir(parents=True)
    pending_file = refresh_state_dir / "pending"
    pending_file.write_text("2026-06-01T09:00:00Z", encoding="utf-8")

    with TestClient(app) as client:
        response = client.post("/meta/refresh")

    assert response.status_code == 502
    assert "dbt build failed" in response.json()["detail"]
    assert runner.calls == 1
    # Failure must never clear the marker or touch live marts.
    assert pending_file.exists()


def test_meta_refresh_maps_unexpected_runner_failure_to_sanitized_502(
    refresh_state_dir: Path,
) -> None:
    """`DbtRunner.refresh()` can also fail outside `DbtRefreshError`, e.g. a
    raw SQLAlchemy error while promoting shadow schemas, or an `OSError`
    from a missing dbt executable. These must still map to a sanitized 502
    rather than an undocumented 500, and must not leak internal details."""
    app = create_app()
    runner = _FakeRefreshRunner(error=RuntimeError("password=hunter2 connection refused"))
    app.dependency_overrides[get_dbt_runner] = lambda: runner
    app.dependency_overrides[get_refresh_state_dir] = lambda: refresh_state_dir
    refresh_state_dir.mkdir(parents=True)
    pending_file = refresh_state_dir / "pending"
    pending_file.write_text("2026-06-01T09:00:00Z", encoding="utf-8")

    with TestClient(app) as client:
        response = client.post("/meta/refresh")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "unexpected dbt refresh failure"
    assert "hunter2" not in detail
    assert runner.calls == 1
    assert pending_file.exists()


def test_meta_refresh_maps_lock_contention_to_503_without_calling_dbt(
    refresh_state_dir: Path,
) -> None:
    app = create_app()
    runner = _FakeRefreshRunner()
    app.dependency_overrides[get_dbt_runner] = lambda: runner
    app.dependency_overrides[get_refresh_state_dir] = lambda: refresh_state_dir
    refresh_state_dir.mkdir(parents=True)
    pending_file = refresh_state_dir / "pending"
    pending_file.write_text("2026-06-01T09:00:00Z", encoding="utf-8")
    lock_file = refresh_state_dir / "refresh.lock"

    # Hold the same advisory lock the route acquires, simulating a
    # concurrent connection sync or scheduled worker run.
    held = lock_file.open("a+", encoding="utf-8")
    try:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        with TestClient(app) as client:
            response = client.post("/meta/refresh")

        assert response.status_code == 503
        assert runner.calls == 0
        assert pending_file.exists()
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()


def test_meta_refresh_logs_but_does_not_fail_when_marker_cleanup_errors(
    meta_refresh_client: tuple[TestClient, _FakeRefreshRunner],
    refresh_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runner = meta_refresh_client
    refresh_state_dir.mkdir(parents=True)
    pending_file = refresh_state_dir / "pending"
    pending_file.write_text("2026-06-01T09:00:00Z", encoding="utf-8")

    original_unlink = Path.unlink

    def failing_unlink(self: Path, *, missing_ok: bool = False) -> None:
        if self == pending_file:
            raise OSError("simulated filesystem failure")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    response = client.post("/meta/refresh")

    assert response.status_code == 200
    assert runner.calls == 1
    # The marker unlink failed but the promotion already succeeded, so the
    # route must still report success rather than raising.
    assert pending_file.exists()
