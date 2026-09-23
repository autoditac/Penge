"""Unit tests for ``deploy/runner/docker-gc.sh``.

The script is pure bash + GNU coreutils, so these tests run anywhere the rest
of the suite does. A fake ``docker`` on ``PATH`` records every invocation and
serves canned ``docker ps`` output, which lets us assert the two properties
that actually matter for a garbage collector running next to live CI jobs:

* stale BuildKit builders (and their *named* state volumes, which a running
  builder pins against ``docker volume prune``) are removed, and
* nothing younger than the age threshold is touched, so a concurrent job's
  builder, cache or image can never be destroyed.

Guards #287.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GC_SCRIPT = REPO_ROOT / "deploy" / "runner" / "docker-gc.sh"

OLD_BUILDER = "buildx_buildkit_penge-ci-build-1-1-api0"
YOUNG_BUILDER = "buildx_buildkit_penge-ci-build-2-1-web0"
OLD_IMAGE = "penge/api:ci-1-1"
YOUNG_IMAGE = "penge/web:ci-2-1"
OLD_VOLUME = "buildx_buildkit_penge-release-9-1-api0_state"


def _docker_created_at(age: timedelta) -> str:
    """Render a timestamp the way ``docker ps --format '{{.CreatedAt}}'`` does."""
    return (datetime.now(UTC) - age).strftime("%Y-%m-%d %H:%M:%S %z UTC")


@pytest.fixture
def fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    """Install a fake ``docker`` that logs argv and serves canned ``ps`` output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    ps_output = tmp_path / "ps.txt"
    ps_output.write_text(
        f"{OLD_BUILDER}\t{_docker_created_at(timedelta(hours=35))}\n"
        f"{YOUNG_BUILDER}\t{_docker_created_at(timedelta(minutes=20))}\n"
    )
    images_output = tmp_path / "images.txt"
    images_output.write_text(
        f"{OLD_IMAGE}\t{_docker_created_at(timedelta(hours=9))}\n"
        f"{YOUNG_IMAGE}\t{_docker_created_at(timedelta(minutes=5))}\n"
    )

    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {calls}\n'
        'if [[ "$1" == "ps" ]]; then\n'
        f"  cat {ps_output}\n"
        "fi\n"
        'if [[ "$1" == "images" ]]; then\n'
        f"  cat {images_output}\n"
        "fi\n"
        'if [[ "$1" == "volume" && "$2" == "ls" ]]; then\n'
        f'  printf "{OLD_VOLUME}\\n"\n'
        "fi\n"
        'if [[ "$1" == "volume" && "$2" == "inspect" ]]; then\n'
        f'  printf "{_docker_created_at(timedelta(hours=40))}\\n"\n'
        "fi\n"
        "exit 0\n"
    )
    docker.chmod(0o755)
    return bin_dir, calls


def _run_gc(bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    return subprocess.run(
        [str(GC_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_removes_stale_builder_and_its_named_state_volume(
    fake_docker: tuple[Path, Path],
) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", "2")

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    assert f"rm --force --volumes {OLD_BUILDER}" in calls
    # The state volume is named, not anonymous: `docker rm --volumes` leaves
    # it behind, which is why plain pruning never reclaimed the 3 GB.
    assert f"volume rm --force {OLD_BUILDER}_state" in calls


def test_leaves_builders_younger_than_threshold_alone(
    fake_docker: tuple[Path, Path],
) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", "2")

    assert result.returncode == 0, result.stderr
    assert YOUNG_BUILDER not in log.read_text()
    assert f"keeping builder {YOUNG_BUILDER}" in result.stderr


def test_removes_stale_tagged_ci_images(fake_docker: tuple[Path, Path]) -> None:
    """Run-scoped CI images are tagged, so `image prune` never reclaims them."""
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", "2")

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    assert f"image rm --force {OLD_IMAGE}" in calls
    # A job that was killed 5 minutes ago may still be using its image.
    assert f"image rm --force {YOUNG_IMAGE}" not in calls
    assert (
        "images --filter reference=penge/*:ci-* "
        "--format {{.Repository}}:{{.Tag}}\t{{.CreatedAt}}" in calls
    )


def test_removes_orphaned_buildkit_volumes_by_age(fake_docker: tuple[Path, Path]) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", "2")

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    assert f"volume rm --force {OLD_VOLUME}" in calls
    # `docker volume prune` accepts no `until` filter, so a blanket prune
    # would silently drop the age guarantee.
    assert "volume prune --force" not in calls


def test_prunes_are_age_bounded_and_never_blanket(
    fake_docker: tuple[Path, Path],
) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", "6")

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    assert "image prune --force --filter until=6h" in calls
    assert "builder prune --force --filter until=6h" in calls
    # A blanket sweep would take a concurrent job's build cache with it.
    assert not any(call.startswith("system prune") for call in calls)
    assert not any("--all" in call and "prune" in call for call in calls)


def test_dry_run_removes_nothing(fake_docker: tuple[Path, Path]) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", "2", "--dry-run")

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    # Only read-only inspection reached the daemon.
    read_only = ("system df", "ps ", "images ", "volume ls ", "volume inspect ")
    assert all(call.startswith(read_only) for call in calls), calls
    assert f"DRY-RUN would run: docker rm --force --volumes {OLD_BUILDER}" in result.stdout


@pytest.mark.parametrize("flag", ["--max-age-hours", "--prefix"])
def test_missing_option_value_exits_two(fake_docker: tuple[Path, Path], flag: str) -> None:
    """`set -u` would otherwise abort with status 1 on a missing operand."""
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, flag)

    assert result.returncode == 2
    assert f"{flag} requires a value" in result.stderr
    assert _calls(log) == []


@pytest.mark.parametrize("flag", ["--max-age-hours", "--prefix"])
def test_option_value_that_looks_like_a_flag_is_rejected(
    fake_docker: tuple[Path, Path], flag: str
) -> None:
    """Swallowing `--dry-run` as an operand would turn a rehearsal destructive."""
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, flag, "--dry-run")

    assert result.returncode == 2
    assert f"{flag} requires a value" in result.stderr
    assert _calls(log) == []


@pytest.mark.parametrize("age", ["0", "-1", "two", ""])
def test_rejects_non_positive_age(fake_docker: tuple[Path, Path], age: str) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--max-age-hours", age)

    assert result.returncode == 2
    assert _calls(log) == []


def test_rejects_unknown_arguments(fake_docker: tuple[Path, Path]) -> None:
    bin_dir, log = fake_docker

    result = _run_gc(bin_dir, "--purge-everything")

    assert result.returncode == 2
    assert _calls(log) == []


def test_survives_a_failing_docker_command(tmp_path: Path) -> None:
    """One stubborn resource must not abort the rest of the sweep."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {calls}\n'
        'if [[ "$1" == "ps" ]]; then\n'
        f'  printf "{OLD_BUILDER}\\t{_docker_created_at(timedelta(hours=9))}\\n"\n'
        "fi\n"
        'if [[ "$1" == "rm" ]]; then exit 1; fi\n'
        "exit 0\n"
    )
    docker.chmod(0o755)

    result = _run_gc(bin_dir, "--max-age-hours", "2")

    assert result.returncode == 0, result.stderr
    assert "WARNING: command failed (continuing)" in result.stdout
    assert "image prune --force --filter until=2h" in _calls(calls)


def test_keeps_the_state_volume_when_its_container_survives(tmp_path: Path) -> None:
    """A live BuildKit process would be corrupted by losing its state volume."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {calls}\n'
        'if [[ "$1" == "ps" ]]; then\n'
        f'  printf "{OLD_BUILDER}\\t{_docker_created_at(timedelta(hours=9))}\\n"\n'
        "fi\n"
        'if [[ "$1" == "rm" ]]; then exit 1; fi\n'
        "exit 0\n"
    )
    docker.chmod(0o755)

    result = _run_gc(bin_dir, "--max-age-hours", "2")

    assert result.returncode == 0, result.stderr
    assert f"volume rm --force {OLD_BUILDER}_state" not in _calls(calls)
    assert f"keeping {OLD_BUILDER}_state" in result.stdout
