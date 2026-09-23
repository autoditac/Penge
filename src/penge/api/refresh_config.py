"""Configuration for the WebUI-triggered dbt-only refresh (issue #285, ADR-0046).

Resolves the dbt project/profiles directories the ``/meta/refresh`` route
passes to :class:`penge.ops.net_worth_refresh.DbtRunner`. The advisory
lock and pending-marker paths are *not* duplicated here: the route reuses
:class:`penge.api.connections.config.ConnectionsConfig.refresh_state_dir`
so every writer (scheduled worker, manual connection sync, WebUI refresh)
resolves the same state directory from the same ``PENGE_REFRESH_STATE_DIR``
variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Matches the API container's committed dbt project layout
# (deploy/nas/penge-net-worth-refresh.service, ADR-0046).
_CONTAINER_DBT_DIR = Path("/app/dbt")
# Repo checkout layout used by `just api-dev` and local pytest runs.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_DBT_DIR = _REPO_ROOT / "dbt"


def _default_dbt_dir() -> str:
    """Pick the dbt project layout matching how the process is running.

    ``just api-dev`` sets neither ``PENGE_DBT_*`` variable, so without this
    the API would resolve to the container-only ``/app/dbt`` path even on a
    developer machine. Prefer the container path when it actually exists
    (i.e. this process is the published image); otherwise fall back to the
    checked-out repo's ``dbt/`` directory.
    """
    if _CONTAINER_DBT_DIR.is_dir():
        return str(_CONTAINER_DBT_DIR)
    return str(_LOCAL_DBT_DIR)


@dataclass(frozen=True, slots=True)
class MetaRefreshConfig:
    """Resolved dbt project/profiles directories for the refresh route."""

    dbt_project_dir: Path
    dbt_profiles_dir: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MetaRefreshConfig:
        """Resolve dbt directories from the environment.

        ``PENGE_DBT_PROJECT_DIR`` / ``PENGE_DBT_PROFILES_DIR`` default to
        ``/app/dbt`` when that path exists (the published API container
        image), and to the repo's checked-out ``dbt/`` directory otherwise
        (e.g. under ``just api-dev`` or pytest, where nothing sets either
        variable).
        """
        resolved = env if env is not None else dict(os.environ)
        default_dir = _default_dbt_dir()
        return cls(
            dbt_project_dir=Path(resolved.get("PENGE_DBT_PROJECT_DIR", default_dir)),
            dbt_profiles_dir=Path(resolved.get("PENGE_DBT_PROFILES_DIR", default_dir)),
        )


__all__ = ["MetaRefreshConfig"]
