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
_DEFAULT_DBT_DIR = "/app/dbt"


@dataclass(frozen=True, slots=True)
class MetaRefreshConfig:
    """Resolved dbt project/profiles directories for the refresh route."""

    dbt_project_dir: Path
    dbt_profiles_dir: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MetaRefreshConfig:
        """Resolve dbt directories from the environment.

        ``PENGE_DBT_PROJECT_DIR`` / ``PENGE_DBT_PROFILES_DIR`` default to
        ``/app/dbt``, the path baked into the API container image; local
        development overrides both to the repo's ``dbt/`` directory (see
        ``just api-dev``).
        """
        resolved = env if env is not None else dict(os.environ)
        return cls(
            dbt_project_dir=Path(resolved.get("PENGE_DBT_PROJECT_DIR", _DEFAULT_DBT_DIR)),
            dbt_profiles_dir=Path(resolved.get("PENGE_DBT_PROFILES_DIR", _DEFAULT_DBT_DIR)),
        )


__all__ = ["MetaRefreshConfig"]
