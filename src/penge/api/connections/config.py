"""Configuration + feature detection for the connections surface.

The in-app consent flow needs the Enable Banking RSA private key in
the API process to sign requests. That key is **not** mounted in every
deployment (the read-only NAS API historically had no key), so the
feature is gated: endpoints return HTTP 503 unless a usable key is
configured. See ADR-0040 for the trust-boundary rationale.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Production callback is served from a dedicated un-gated nginx path
# (docs/runbook/enable-banking-consent.md). The bank redirects the
# browser here with ``?code=...&state=...``.
DEFAULT_REDIRECT_URL = "https://penge.eigmueller.de/eb/callback"

_FALSEY = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class ConnectionsConfig:
    """Resolved runtime configuration for the connections surface."""

    enabled: bool
    redirect_url: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ConnectionsConfig:
        """Resolve the feature flag and redirect URL from the environment.

        The feature is *enabled* when both
        ``ENABLEBANKING_APPLICATION_ID`` and ``ENABLEBANKING_KEY_PATH``
        are set and the key file exists. Setting
        ``PENGE_CONNECTIONS_ENABLED`` to a falsey value force-disables
        it even when a key is present (kill switch for the public NAS
        instance).
        """
        resolved = env if env is not None else dict(os.environ)
        app_id = resolved.get("ENABLEBANKING_APPLICATION_ID")
        key_path = resolved.get("ENABLEBANKING_KEY_PATH")
        key_present = bool(app_id and key_path and Path(key_path).expanduser().is_file())
        override = resolved.get("PENGE_CONNECTIONS_ENABLED", "").strip().lower()
        enabled = key_present and override not in _FALSEY
        redirect_url = resolved.get("PENGE_EB_REDIRECT_URL", DEFAULT_REDIRECT_URL)
        return cls(enabled=enabled, redirect_url=redirect_url)


__all__ = ["DEFAULT_REDIRECT_URL", "ConnectionsConfig"]
