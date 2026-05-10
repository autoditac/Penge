"""End-to-end tests for ``scripts/backup.sh`` + ``scripts/restore.sh``.

We need the real ``age`` binary plus ``pg_dump``/``psql`` to drive the
round-trip. The tests skip when those are missing locally so a
developer without the toolchain can still run ``pytest``; CI runs the
full path via ``.github/workflows/backup-roundtrip.yml``.

The Postgres URL comes from ``PENGE_TEST_DATABASE_URL`` (same env var
the rest of the integration tests use). When unset we skip rather than
guess, because tearing down the wrong database would be bad.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

DB_URL_ENV = "PENGE_TEST_DATABASE_URL"

requires_age = pytest.mark.skipif(shutil.which("age") is None, reason="age not installed")
requires_pg = pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("psql") is None,
    reason="pg_dump/psql not installed",
)
requires_db = pytest.mark.skipif(
    not os.environ.get(DB_URL_ENV),
    reason=f"{DB_URL_ENV} not set",
)


@pytest.fixture
def keypair(tmp_path: Path) -> tuple[Path, str]:
    if shutil.which("age-keygen") is None:
        pytest.skip("age-keygen not installed")
    identity = tmp_path / "identity.txt"
    proc = subprocess.run(
        ["age-keygen", "-o", str(identity)],
        check=True,
        capture_output=True,
        text=True,
    )
    # `age-keygen` writes the public key to stderr in the form
    # "Public key: age1...".
    pub = ""
    for line in proc.stderr.splitlines():
        if line.startswith("Public key:"):
            pub = line.split(":", 1)[1].strip()
            break
    assert pub, f"failed to parse age public key from: {proc.stderr!r}"
    identity.chmod(0o600)
    return identity, pub


@requires_age
@requires_pg
def test_backup_requires_recipients(tmp_path: Path) -> None:
    env = {**os.environ, "PENGE_BACKUP_ROOT": str(tmp_path)}
    env.pop("PENGE_BACKUP_RECIPIENTS", None)
    env.pop("PENGE_BACKUP_RECIPIENTS_FILE", None)
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "backup.sh"), "--database-url", "postgresql://x/y"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "no age recipients" in proc.stderr


@requires_age
@requires_pg
@requires_db
def test_backup_then_restore_round_trip(
    tmp_path: Path,
    keypair: tuple[Path, str],
) -> None:
    identity, pub = keypair
    db_url = os.environ[DB_URL_ENV]

    # Spin up an isolated schema so we don't trample on other tests.
    schema = "penge_backup_smoke"
    setup = (
        f'DROP SCHEMA IF EXISTS "{schema}" CASCADE; '
        f'CREATE SCHEMA "{schema}"; '
        f'CREATE TABLE "{schema}".widgets (id INT PRIMARY KEY, label TEXT NOT NULL);'
        f"INSERT INTO \"{schema}\".widgets VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma');"
    )
    subprocess.run(
        ["psql", "--dbname", db_url, "-v", "ON_ERROR_STOP=1", "-c", setup],
        check=True,
        capture_output=True,
        text=True,
    )

    env = {
        **os.environ,
        "PENGE_BACKUP_ROOT": str(tmp_path),
        "PENGE_BACKUP_RECIPIENTS": pub,
        "DATABASE_URL": db_url,
    }
    subprocess.run(
        ["bash", str(SCRIPTS / "backup.sh"), "--label", "smoke"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    artefacts = sorted((tmp_path / "postgres").glob("pg-*-smoke.sql.age"))
    assert len(artefacts) == 1, artefacts

    # Restore into the same database; the backup carries DROP TABLE +
    # CREATE TABLE so the second pass is idempotent.
    subprocess.run(
        [
            "bash",
            str(SCRIPTS / "restore.sh"),
            "--input",
            str(artefacts[0]),
            "--database-url",
            db_url,
            "--identity",
            str(identity),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    proc = subprocess.run(
        [
            "psql",
            "--dbname",
            db_url,
            "-At",
            "-c",
            f'SELECT count(*) FROM "{schema}".widgets;',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "3"

    # Cleanup.
    subprocess.run(
        ["psql", "--dbname", db_url, "-c", f'DROP SCHEMA "{schema}" CASCADE;'],
        check=True,
        capture_output=True,
        text=True,
    )
