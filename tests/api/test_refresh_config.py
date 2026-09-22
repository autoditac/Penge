"""Tests for the environment-aware dbt directory defaults (issue #285).

`just api-dev` and local pytest runs set neither `PENGE_DBT_PROJECT_DIR`
nor `PENGE_DBT_PROFILES_DIR`, so the default must resolve to the checked-out
repo's `dbt/` directory rather than the container-only `/app/dbt` path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from penge.api import refresh_config
from penge.api.refresh_config import MetaRefreshConfig


def test_defaults_to_repo_dbt_dir_when_container_path_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_container_dir = Path("/definitely/does/not/exist/app/dbt")
    monkeypatch.setattr(refresh_config, "_CONTAINER_DBT_DIR", fake_container_dir)

    config = MetaRefreshConfig.from_env({})

    assert config.dbt_project_dir == refresh_config._LOCAL_DBT_DIR
    assert config.dbt_profiles_dir == refresh_config._LOCAL_DBT_DIR
    assert config.dbt_project_dir != fake_container_dir


def test_prefers_container_dbt_dir_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_dir = tmp_path / "app-dbt"
    container_dir.mkdir()
    monkeypatch.setattr(refresh_config, "_CONTAINER_DBT_DIR", container_dir)

    config = MetaRefreshConfig.from_env({})

    assert config.dbt_project_dir == container_dir
    assert config.dbt_profiles_dir == container_dir


def test_explicit_env_vars_override_the_default() -> None:
    config = MetaRefreshConfig.from_env(
        {
            "PENGE_DBT_PROJECT_DIR": "/custom/project",
            "PENGE_DBT_PROFILES_DIR": "/custom/profiles",
        }
    )

    assert config.dbt_project_dir == Path("/custom/project")
    assert config.dbt_profiles_dir == Path("/custom/profiles")
