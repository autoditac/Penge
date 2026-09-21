"""Postgres + dbt harness for mart regression tests.

Requires ``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``) and a ``dbt``
executable on ``PATH`` (i.e. ``uv run --group db --group dbt --group dev
pytest tests/dbt``); the tests skip otherwise. All fixture data is
synthetic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, text

from penge.ops.net_worth_refresh import dbt_environment

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
DBT_AVAILABLE = shutil.which("dbt") is not None

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = REPO_ROOT / "dbt"

pytestmark = pytest.mark.skipif(
    DB_URL is None or not DBT_AVAILABLE,
    reason=(
        "requires a test database (PENGE_TEST_DATABASE_URL/DATABASE_URL) and "
        "a `dbt` executable on PATH -- run via "
        "`uv run --group db --group dbt --group dev pytest tests/dbt`"
    ),
)

_RAW_TABLES = (
    "holding_snapshot",
    '"transaction"',
    "fx_rate",
    "instrument",
    "account",
    "entity",
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""
    assert DB_URL is not None
    eng = create_engine(DB_URL)
    env = {**os.environ, "DATABASE_URL": DB_URL}
    subprocess.run(  # noqa: S603 — fixed argv, test-only helper
        ["alembic", "upgrade", "head"],  # noqa: S607 — fixed argv, test-only helper
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
    """Wipe raw tables before and after each test, leaving the DB clean."""
    statement = text(f"TRUNCATE TABLE {', '.join(_RAW_TABLES)} RESTART IDENTITY CASCADE")
    with engine.begin() as conn:
        conn.execute(statement)
    yield
    with engine.begin() as conn:
        conn.execute(statement)


def run_dbt(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke dbt against the test DB via the repo's committed profile."""
    assert DB_URL is not None
    env = dbt_environment(DB_URL)
    return subprocess.run(  # noqa: S603 — fixed argv, test-only helper
        [  # noqa: S607 — "dbt" resolved via PATH; argv is fixed, test-only
            "dbt",
            *args,
            "--project-dir",
            str(DBT_PROJECT_DIR),
            "--profiles-dir",
            str(DBT_PROJECT_DIR),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
