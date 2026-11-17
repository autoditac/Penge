"""Keep Alembic's process-wide logging configuration out of the pytest process."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.household.db_guard import validate_isolated_test_database_url


def upgrade_isolated_database(database_url: str) -> None:
    """Upgrade only an explicitly opted-in disposable database in a child process."""
    validated_url = validate_isolated_test_database_url(
        database_url,
        allow_destructive_test_db=os.environ.get("PENGE_ALLOW_DESTRUCTIVE_TEST_DB"),
    )
    env = dict(os.environ)
    env["DATABASE_URL"] = validated_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        timeout=120,
    )
