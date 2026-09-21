"""Postgres + dbt harness for mart regression tests.

Requires ``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``) and a working
``dbt`` executable on ``PATH`` (i.e. ``uv run --group db --group dbt
--group dev pytest tests/dbt``); the test modules in this package skip
otherwise (see the ``pytestmark`` in each test module -- it must live
there, not here, since a ``pytestmark`` assigned in a conftest.py does
not apply to sibling test modules). All fixture data is synthetic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, make_url, text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine


def _pg_env(database_url: str) -> dict[str, str]:
    """Build libpq ``PG*`` env vars from a ``DATABASE_URL`` for the dbt subprocess.

    Deliberately reimplements (rather than imports)
    ``penge.ops.net_worth_refresh.dbt_environment``: importing that module
    pulls in the ``penge.ops`` package's heartbeat/Sentry integrations,
    which need the ``http``/``vault`` dependency groups that the minimal
    ``db``/``dbt``/``dev`` groups this test suite runs under do not
    install.
    """
    url = make_url(database_url)
    env = dict(os.environ)
    env.update(
        {
            "PGHOST": url.host or "localhost",
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "",
            "PGDATABASE": url.database or "",
        }
    )
    if url.password is not None:
        env["PGPASSWORD"] = url.password
    return env


def _dbt_available() -> bool:
    """Check that ``dbt`` is not just on ``PATH`` but actually runs.

    ``shutil.which`` alone is not reliable on long-lived, shared
    self-hosted runners: a stale entry (e.g. a script with a shebang
    pointing at a since-removed interpreter from an earlier job's venv)
    can satisfy ``which`` while still failing at exec time with
    ``FileNotFoundError``. Actually invoking ``--version`` catches that.
    """
    dbt_path = shutil.which("dbt")
    if dbt_path is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, availability probe only
            [dbt_path, "--version"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except OSError:
        return False
    return result.returncode == 0


# These are also imported by test_mart_returns_daily.py, which applies its
# own ``pytestmark`` skip guard: a marker assigned here would only apply to
# tests defined in this file, not to sibling test modules in the package.
DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
DBT_AVAILABLE = _dbt_available()

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = REPO_ROOT / "dbt"

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
    env = _pg_env(DB_URL)
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
