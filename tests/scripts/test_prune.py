"""Unit tests for ``scripts/prune.sh``.

The prune script is pure bash + GNU date, so these tests run in any
environment with a recent coreutils and bash 5+. They build a fake
backup root populated with empty ``*.age`` artefacts whose timestamps
span ~18 months, then assert which files survive each retention
policy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRUNE = REPO_ROOT / "scripts" / "prune.sh"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _seed(root: Path, days: int) -> list[Path]:
    """Create ``days`` consecutive daily artefacts ending today (UTC)."""
    pg_dir = root / "postgres"
    pg_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).replace(hour=3, minute=0, second=0, microsecond=0)
    out: list[Path] = []
    for i in range(days):
        ts = _ts(today - timedelta(days=i))
        f = pg_dir / f"pg-{ts}.sql.age"
        f.write_bytes(b"")
        (pg_dir / f"pg-{ts}.sql.age.sha256").write_text(f"deadbeef  {f.name}\n")
        out.append(f)
    return out


def _run_prune(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PRUNE), "--root", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def backup_root(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def test_prune_keeps_recent_dailies_and_culls_the_rest(backup_root: Path) -> None:
    _seed(backup_root, days=60)

    _run_prune(backup_root, "--daily", "14", "--weekly", "0", "--monthly", "0")

    survivors = sorted(p.name for p in (backup_root / "postgres").glob("*.age"))
    assert len(survivors) == 14, survivors
    sidecars = sorted(p.name for p in (backup_root / "postgres").glob("*.sha256"))
    assert len(sidecars) == 14, sidecars


def test_prune_buckets_weekly_and_monthly(backup_root: Path) -> None:
    seeded = _seed(backup_root, days=400)
    expected_newest = seeded[0].name  # _seed returns newest-first.

    _run_prune(backup_root, "--daily", "14", "--weekly", "8", "--monthly", "12")

    survivors = sorted(p.name for p in (backup_root / "postgres").glob("*.age"))
    # 14 daily + up to 8 distinct weeks (excluding overlap with daily) +
    # up to 12 distinct months (excluding overlap with daily/weekly).
    # Lower bound: at least 14 (the daily quota). Upper bound: 14+8+12.
    assert 14 <= len(survivors) <= 34, survivors

    # The newest artefact must always survive a prune; assert the
    # specific filename rather than tautologically asserting that
    # max(survivors) is in survivors.
    assert expected_newest in survivors, (expected_newest, survivors)


def test_prune_dry_run_keeps_everything(backup_root: Path) -> None:
    files = _seed(backup_root, days=30)

    _run_prune(backup_root, "--daily", "1", "--weekly", "0", "--monthly", "0", "--dry-run")

    # Every artefact still on disk after a dry run.
    for f in files:
        assert f.exists(), f


def test_prune_ignores_files_without_timestamp(backup_root: Path) -> None:
    _seed(backup_root, days=5)
    stray = backup_root / "postgres" / "manual-export.sql.age"
    stray.write_bytes(b"")

    _run_prune(backup_root, "--daily", "0", "--weekly", "0", "--monthly", "0")

    # Stray file lacks the YYYYMMDDTHHMMSSZ token, so prune leaves it
    # alone instead of deleting an artefact whose age it cannot judge.
    assert stray.exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")
def test_prune_handles_empty_root(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    # Use check=False so that a hypothetical non-zero exit (which the
    # script should NOT produce on an empty root) surfaces as an
    # assertion failure instead of a CalledProcessError.
    proc = _run_prune(root, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "no artefacts" in proc.stderr
    # Backup root + subdirs were created on demand.
    assert (root / "postgres").is_dir()
    assert (root / "duckdb").is_dir()


def test_prune_script_is_executable() -> None:
    assert os.access(PRUNE, os.X_OK), f"{PRUNE} must be executable"
