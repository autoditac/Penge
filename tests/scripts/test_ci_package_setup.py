"""Synthetic shared-runner setup regressions; never invoke real package managers."""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci-package-setup.sh"
COMMAND = [
    "/bin/bash",
    str(SCRIPT),
    "pnpm",
    "--filter",
    "@penge/web",
    "exec",
    "playwright",
    "install-deps",
    "chromium",
]


def _environment(tmp_path: Path, mode: str = "success") -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pnpm = bin_dir / "pnpm"
    pnpm.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        '[[ "$*" == "--filter @penge/web exec playwright install-deps chromium" ]]\n'
        'echo "$*" >> "$HOME/calls"\n'
        'case "$MODE" in\n'
        "  success) ;;\n"
        '  concurrent) mkdir "$HOME/active"; /usr/bin/sleep 0.1; rmdir "$HOME/active" ;;\n'
        '  recover) if [[ "$(wc -l < "$HOME/calls")" -gt 1 ]]; then exit 0; fi ;;&\n'
        "  recover|locked)\n"
        '    echo "E: Could not get lock /var/lib/apt/lists/lock. It is held by process 123"\n'
        "    exit 100 ;;\n"
        '  broken) echo "E: Failed to fetch package"; exit 42 ;;\n'
        "  denied)\n"
        '    echo "E: Could not open lock file /var/lib/apt/lists/lock'
        ' - open (13: Permission denied)"\n'
        '    echo "E: Unable to lock directory /var/lib/apt/lists/"\n'
        "    exit 100 ;;\n"
        "esac\n"
    )
    pnpm.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text('#!/usr/bin/env bash\n[[ "$*" == "10" ]]\necho sleep >> "$HOME/waits"\n')
    sleep.chmod(0o755)
    return dict(os.environ, HOME=str(tmp_path), PATH=f"{bin_dir}:{os.environ['PATH']}", MODE=mode)


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(COMMAND, env=env, text=True, capture_output=True, check=False, timeout=10)


def test_concurrent_jobs_serialize_system_packages(tmp_path: Path) -> None:
    env = _environment(tmp_path, "concurrent")
    with (
        subprocess.Popen(
            COMMAND,
            env=dict(env, RUNNER_TEMP=str(tmp_path / "runner-1")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as first,
        subprocess.Popen(
            COMMAND,
            env=dict(env, RUNNER_TEMP=str(tmp_path / "runner-2")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as second,
    ):
        _, first_error = first.communicate(timeout=10)
        _, second_error = second.communicate(timeout=10)
        assert first.returncode == 0, first_error
        assert second.returncode == 0, second_error
    assert len((tmp_path / "calls").read_text().splitlines()) == 2
    assert (tmp_path / ".cache/penge-ci/package-setup.lock").exists()


@pytest.mark.parametrize(
    ("mode", "status", "attempts", "waits"),
    [
        ("success", 0, 1, 0),
        ("recover", 0, 2, 1),
        ("locked", 100, 3, 2),
        ("broken", 42, 1, 0),
        ("denied", 100, 1, 0),
    ],
)
def test_retries_only_lock_errors_and_preserves_failures(
    tmp_path: Path, mode: str, status: int, attempts: int, waits: int
) -> None:
    result = _run(_environment(tmp_path, mode))
    assert result.returncode == status, result.stderr
    assert len((tmp_path / "calls").read_text().splitlines()) == attempts
    wait_log = tmp_path / "waits"
    assert (len(wait_log.read_text().splitlines()) if wait_log.exists() else 0) == waits
    if mode == "locked":
        assert "persisted after 3 attempts" in result.stderr
        assert "Could not get lock" in result.stderr
    if mode == "broken":
        assert "Failed to fetch package" in result.stderr
    if mode == "denied":
        assert "Permission denied" in result.stderr


def test_busy_host_lock_fails_without_installing(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    flock = tmp_path / "bin/flock"
    flock.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$*" == "--exclusive --timeout 300 9" ]] || exit 99\n'
        "exec /usr/bin/flock --exclusive --timeout 0 9\n"
    )
    flock.chmod(0o755)
    lock = tmp_path / ".cache/penge-ci/package-setup.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        result = _run(env)
    assert result.returncode == 75
    assert "300s" in result.stderr
    assert not (tmp_path / "calls").exists()


def test_workflow_isolates_caches_before_restore_and_keeps_frozen_installs(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/dbt.yml").read_text())
    job = workflow["jobs"]["build"]
    steps = job["steps"]
    uv = next(step for step in steps if "setup-uv@" in step.get("uses", ""))
    assert uv["with"]["enable-cache"] is True
    assert uv["with"]["cache-local-path"] == "${{ env.UV_CACHE_DIR }}"
    isolate = next(
        step for step in steps if step.get("name") == "Isolate mutable dependency caches"
    )
    assert steps.index(isolate) < steps.index(uv)
    caches = []
    for runner, attempt in (("penge-1", "1"), ("penge-2", "1"), ("penge-1", "2")):
        output = tmp_path / f"{runner}-{attempt}.env"
        result = subprocess.run(
            ["/bin/bash", "-c", isolate["run"]],
            env=dict(
                os.environ,
                RUNNER_TEMP=str(tmp_path / runner),
                GITHUB_JOB="build",
                GITHUB_RUN_ID="123",
                GITHUB_RUN_ATTEMPT=attempt,
                GITHUB_ENV=str(output),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        caches.append(dict(line.split("=", 1) for line in output.read_text().splitlines()))
    assert caches[0]["UV_CACHE_DIR"] != caches[1]["UV_CACHE_DIR"]
    assert caches[0]["UV_CACHE_DIR"] == caches[2]["UV_CACHE_DIR"]
    assert len({cache["PLAYWRIGHT_BROWSERS_PATH"] for cache in caches}) == 3
    installs = next(
        step["run"] for step in steps if step.get("name") == "Install db + dbt + test deps"
    )
    assert "--frozen" in installs
    tooling = next(
        step["run"] for step in steps if step.get("name") == "Install pinned browser test tooling"
    )
    assert "pnpm install --frozen-lockfile" in tooling
    assert tooling.index("just ci-browser-deps") < tooling.index("playwright install chromium")
    assert "--with-deps" not in tooling


def test_ocr_installer_uses_same_lock_and_propagates_apt_errors() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["pytest"]["steps"]
    installer = next(step["run"] for step in steps if "Install OCR" in step.get("name", ""))
    assert "bash scripts/ci-package-setup.sh bash -euo pipefail -c" in installer
    assert "sudo apt-get update" in installer
    assert "tesseract-ocr tesseract-ocr-dan tesseract-ocr-deu poppler-utils" in installer
    justfile = (ROOT / "Justfile").read_text()
    assert (
        "bash scripts/ci-package-setup.sh pnpm --filter @penge/web exec "
        "playwright install-deps chromium" in justfile
    )


def test_all_repository_apt_steps_coordinate_on_the_host_lock() -> None:
    installers = []
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                command = step.get("run", "")
                if "sudo apt-get" in command:
                    installers.append((path.name, step.get("name")))
                    assert "bash scripts/ci-package-setup.sh bash -euo pipefail -c" in command
    assert len(installers) == 3


def test_alembic_cache_restore_stall_cannot_consume_job_budget() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["alembic-roundtrip"]
    steps = job["steps"]
    uv = next(step for step in steps if "setup-uv@" in step.get("uses", ""))
    assert uv["with"]["enable-cache"] is True
    segment_timeout = int(uv["env"]["SEGMENT_DOWNLOAD_TIMEOUT_MINS"])
    assert 0 < segment_timeout < job["timeout-minutes"] // 2
    assert any(step.get("run") == "uv sync --group db --frozen" for step in steps)
