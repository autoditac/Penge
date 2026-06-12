"""Shared Postgres harness for import-API tests.

Requires ``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``); modules
using these fixtures skip themselves otherwise. CI provides a
disposable Postgres service. All fixture data is synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from penge.api.app import create_app
from penge.api.imports.engine import get_import_engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx import Response
    from sqlalchemy.engine import Engine

DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

REPO_ROOT = Path(__file__).resolve().parents[3]


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
    """Wipe staging and raw tables before each test."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE import_row, import_session, holding_snapshot, "
                '"transaction", instrument, account, entity RESTART IDENTITY CASCADE'
            )
        )
    yield


@pytest.fixture
def client(
    engine: Engine,
    _truncate: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """TestClient with the import dir under tmp_path and a fresh engine."""
    _ = engine  # schema must exist before the app serves requests
    assert DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("PENGE_IMPORT_DIR", str(tmp_path / "imports"))
    get_import_engine.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_import_engine.cache_clear()


def upload(
    client: TestClient,
    path: Path,
    *,
    source: str | None = None,
    entity_name: str | None = None,
) -> Response:
    """POST one statement file to ``/imports``."""
    data: dict[str, str] = {}
    if source is not None:
        data["source"] = source
    if entity_name is not None:
        data["entity_name"] = entity_name
    with path.open("rb") as fh:
        return client.post(
            "/imports",
            files={"file": (path.name, fh, "application/octet-stream")},
            data=data,
        )


def manual_json(tmp_path: Path, balances: list[dict[str, object]]) -> Path:
    """Write a synthetic manual-balances upload file."""
    path = tmp_path / "balances.json"
    path.write_text(json.dumps({"balances": balances}), encoding="utf-8")
    return path
