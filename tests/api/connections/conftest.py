"""Postgres + fake-client harness for the connections API tests.

Requires ``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``); the tests
skip otherwise. The Enable Banking client is always faked — no signing
key, no network. All fixture data is synthetic.
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

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.engine import Engine

DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(DB_URL is None, reason="no test database configured")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""
    assert DB_URL is not None
    eng = create_engine(DB_URL)
    env = {**os.environ, "DATABASE_URL": DB_URL}
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
                "TRUNCATE TABLE bank_connection, holding_snapshot, "
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
) -> None:
    app = cast("FastAPI", app_client.app)
    app.dependency_overrides[connections_routes.get_config] = lambda: ConnectionsConfig(
        enabled=enabled, redirect_url="https://penge.example/eb/callback"
    )
    app.dependency_overrides[connections_routes.get_engine] = lambda: engine
    app.dependency_overrides[connections_routes.get_client] = lambda: fake


@pytest.fixture
def client(
    engine: Engine,
    _truncate: None,
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """TestClient with the feature enabled and the EB client faked."""
    assert DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_import_engine.cache_clear()
    with TestClient(create_app()) as test_client:
        _apply_overrides(test_client, engine=engine, enabled=True, fake=fake_client)
        yield test_client
    get_import_engine.cache_clear()


@pytest.fixture
def disabled_client(
    engine: Engine,
    _truncate: None,
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """TestClient with the feature force-disabled (no signing key)."""
    assert DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_import_engine.cache_clear()
    with TestClient(create_app()) as test_client:
        _apply_overrides(test_client, engine=engine, enabled=False, fake=fake_client)
        yield test_client
    get_import_engine.cache_clear()
