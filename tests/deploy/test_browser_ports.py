"""Exercise the actual CI port allocation and build recipe without servers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("runner", ["penge-1", "penge-2", "penge-3", "unknown"])
def test_workflow_browser_port_allocation(runner: str, tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/dbt.yml").read_text())
    steps = workflow["jobs"]["build"]["steps"]
    allocation = next(
        step for step in steps if step.get("name") == "Isolate browser ports by runner"
    )
    acceptance = next(step for step in steps if step.get("run") == "just household-browser-test")
    assert steps.index(allocation) < steps.index(acceptance)
    env_file = tmp_path / "github-env"
    result = subprocess.run(  # noqa: S603  # Execute only the repository-owned workflow step.
        ["/bin/bash", "-c", allocation["run"]],
        env={**os.environ, "RUNNER_NAME": runner, "GITHUB_ENV": str(env_file)},
        capture_output=True,
        text=True,
        check=False,
    )
    if runner == "unknown":
        assert result.returncode != 0
        assert "No browser port allocation" in result.stderr
        assert not env_file.exists()
    else:
        assert result.returncode == 0, result.stderr
        slot = int(runner[-1])
        assert env_file.read_text().splitlines() == [
            f"PENGE_E2E_API_PORT={18000 + slot}",
            f"PENGE_E2E_WEB_PORT={15000 + slot}",
        ]


@pytest.mark.parametrize("port", [None, "18002"])
def test_browser_build_uses_selected_api_port(port: str | None, tmp_path: Path) -> None:
    """Vite bakes the origin into dist; preview-time env alone cannot change it."""
    recipe = (ROOT / "Justfile").read_text().split("household-browser-test:\n", 1)[1]
    build = recipe.splitlines()[0].strip()
    pnpm = tmp_path / "pnpm"
    pnpm.write_text('#!/bin/bash\nprintf "%s\\n" "$VITE_PENGE_API_URL" "$VITE_PENGE_DEMO"\n')
    pnpm.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    env.pop("PENGE_E2E_API_PORT", None)
    if port is not None:
        env["PENGE_E2E_API_PORT"] = port
    result = subprocess.run(  # noqa: S603  # Execute only the repository-owned build recipe.
        ["/bin/bash", "-eu", "-c", build],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"http://127.0.0.1:{port or '8000'}", "false"]
