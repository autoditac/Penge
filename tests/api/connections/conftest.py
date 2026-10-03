"""Guarded Postgres + fake-client harness for connections API tests.

Requires an explicitly opted-in, loopback, test-named
``PENGE_TEST_DATABASE_URL``. The Enable Banking client is always faked; all
fixture data is synthetic.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from penge.api.app import create_app
from penge.api.connections import routes as connections_routes
from penge.api.connections.config import ConnectionsConfig
from penge.api.imports.engine import get_import_engine
from tests.api.connections.fakes import FakeClient
from tests.household.db_guard import validate_isolated_test_database_url

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.engine import Engine

DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL")

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(DB_URL is None, reason="no test database configured")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""
    if DB_URL is None:
        pytest.skip("PENGE_TEST_DATABASE_URL is required for connections database tests")
    test_database_url = validate_isolated_test_database_url(
        DB_URL,
        allow_destructive_test_db=os.environ.get("PENGE_ALLOW_DESTRUCTIVE_TEST_DB"),
    )
    eng = create_engine(test_database_url)
    env = {**os.environ, "DATABASE_URL": test_database_url}
    subprocess.run(  # noqa: S603 — fixed argv, test-only helper
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def _truncate(engine: Engine) -> Iterator[None]:
    """Wipe connection and raw tables before each test."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE household_rule_preview, household_payment_detail_link, "
                "household_audit, household_transaction_link, household_allocation, "
                "household_classification, household_payment_detail, household_rule, "
                "household_merchant_alias, household_merchant, household_category, "
                "bank_connection, holding_snapshot, "
                '"transaction", instrument, account, entity RESTART IDENTITY CASCADE'
            )
        )
    yield


@pytest.fixture
def fake_client() -> FakeClient:
    """A primeable fake Enable Banking client shared with the TestClient."""
    return FakeClient()


def _apply_overrides(
    app_client: TestClient,
    *,
    engine: Engine,
    enabled: bool,
    fake: FakeClient,
    refresh_state_dir: Path,
) -> None:
    app = cast("FastAPI", app_client.app)
    app.dependency_overrides[connections_routes.get_config] = lambda: ConnectionsConfig(
        enabled=enabled,
        redirect_url="https://penge.example/eb/callback",
        refresh_state_dir=refresh_state_dir,
    )
    app.dependency_overrides[connections_routes.get_engine] = lambda: engine
    app.dependency_overrides[connections_routes.get_client] = lambda: fake


@pytest.fixture
def client(
    engine: Engine,
    _truncate: None,
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """TestClient with the feature enabled and the EB client faked."""
    assert DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_import_engine.cache_clear()
    with TestClient(create_app()) as test_client:
        _apply_overrides(
            test_client,
            engine=engine,
            enabled=True,
            fake=fake_client,
            refresh_state_dir=tmp_path / "refresh-state",
        )
        yield test_client
    get_import_engine.cache_clear()


@pytest.fixture
def disabled_client(
    engine: Engine,
    _truncate: None,
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """TestClient with the feature force-disabled (no signing key)."""
    assert DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_import_engine.cache_clear()
    with TestClient(create_app()) as test_client:
        _apply_overrides(
            test_client,
            engine=engine,
            enabled=False,
            fake=fake_client,
            refresh_state_dir=tmp_path / "refresh-state",
        )
        yield test_client
    get_import_engine.cache_clear()
