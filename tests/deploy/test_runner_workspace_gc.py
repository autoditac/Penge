"""Unit tests for ``deploy/runner/workspace-gc.sh``.

The script only touches the filesystem, so these tests build a fake runner
root in ``tmp_path`` and assert the two properties that matter for a sweep
running next to live CI jobs:

* the leftovers that actually fill the disk -- the ``_work/_update`` payload a
  runner self-upgrade abandons, and aged ``_diag`` logs -- are removed, and
* nothing a running job could own is, in particular the ``_work/<owner>/<repo>``
  checkout and anything younger than the age threshold.

Guards #289 follow-up: Docker was only half of the runner disk exhaustion.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GC_SCRIPT = REPO_ROOT / "deploy" / "runner" / "workspace-gc.sh"

HOUR = 3600


def _age(path: Path, hours: float) -> None:
    """Backdate ``path`` so the script's ``find -mmin``/``-mtime`` sees it as old."""
    when = time.time() - hours * HOUR
    os.utime(path, (when, when))


@pytest.fixture
def runner_root(tmp_path: Path) -> Path:
    """A miniature `/var/lib/ghrunner` with one runner and realistic contents."""
    root = tmp_path / "ghrunner"
    runner = root / "actions-runner"

    update = runner / "_work" / "_update" / "externals"
    update.mkdir(parents=True)
    (update / "node24").write_text("stale self-update payload")

    checkout = runner / "_work" / "Penge" / "Penge"
    checkout.mkdir(parents=True)
    (checkout / "README.md").write_text("live checkout")

    diag = runner / "_diag"
    diag.mkdir(parents=True)
    (diag / "Runner_old.log").write_text("old")
    (diag / "Runner_recent.log").write_text("recent")

    temp = runner / "_work" / "_temp"
    temp.mkdir(parents=True)
    (temp / "stale-job-file").write_text("orphaned")
    (temp / "live-job-file").write_text("in use")

    # A sibling directory that is *not* a runner: no `_work`, so it must be
    # skipped entirely rather than probed.
    (root / "backup").mkdir()
    (root / "backup" / "keep-me").write_text("not a runner")

    _age(runner / "_work" / "_update", 26)
    _age(diag / "Runner_old.log", 30 * 24)
    _age(temp / "stale-job-file", 26)

    return root


def _run_gc(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(GC_SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_removes_stale_self_update_payload(runner_root: Path) -> None:
    """~678 MB per runner, never read again after the upgrade completes."""
    result = _run_gc(runner_root)

    assert result.returncode == 0, result.stderr
    assert not (runner_root / "actions-runner" / "_work" / "_update").exists()


def test_keeps_recent_self_update_payload(tmp_path: Path) -> None:
    """A fresh `_update` may be an upgrade still unpacking."""
    root = tmp_path / "ghrunner"
    update = root / "actions-runner" / "_work" / "_update"
    update.mkdir(parents=True)

    result = _run_gc(root)

    assert result.returncode == 0, result.stderr
    assert update.exists()
    assert "keeping actions-runner/_work/_update" in result.stderr


def test_removes_diag_logs_past_retention(runner_root: Path) -> None:
    diag = runner_root / "actions-runner" / "_diag"

    result = _run_gc(runner_root, "--diag-retention-days", "7")

    assert result.returncode == 0, result.stderr
    assert not (diag / "Runner_old.log").exists()
    assert (diag / "Runner_recent.log").exists()


def test_never_touches_the_job_checkout(runner_root: Path) -> None:
    """Deleting a checkout only forces a re-clone, and age cannot prove it idle."""
    checkout = runner_root / "actions-runner" / "_work" / "Penge" / "Penge"
    _age(checkout, 30 * 24)

    result = _run_gc(runner_root)

    assert result.returncode == 0, result.stderr
    assert (checkout / "README.md").read_text() == "live checkout"


def test_removes_only_stale_temp_entries(runner_root: Path) -> None:
    temp = runner_root / "actions-runner" / "_work" / "_temp"

    result = _run_gc(runner_root)

    assert result.returncode == 0, result.stderr
    assert not (temp / "stale-job-file").exists()
    assert (temp / "live-job-file").exists()


def test_ignores_directories_that_are_not_runners(runner_root: Path) -> None:
    result = _run_gc(runner_root)

    assert result.returncode == 0, result.stderr
    assert (runner_root / "backup" / "keep-me").exists()


def test_dry_run_removes_nothing(runner_root: Path) -> None:
    update = runner_root / "actions-runner" / "_work" / "_update"

    result = _run_gc(runner_root, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert update.exists()
    assert "DRY-RUN would remove" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("--max-age-hours", "0"),
        ("--max-age-hours", "nope"),
        ("--diag-retention-days", "0"),
        ("--root",),
        ("--unknown-flag",),
    ],
)
def test_rejects_invalid_arguments(runner_root: Path, args: tuple[str, ...]) -> None:
    result = _run_gc(runner_root, *args)

    assert result.returncode == 2, result.stderr


def test_missing_root_is_an_error(tmp_path: Path) -> None:
    result = _run_gc(tmp_path / "nope")

    assert result.returncode == 2
    assert "does not exist" in result.stderr
