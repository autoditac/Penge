"""In-app Enable Banking consent + sync surface (issue #230, ADR-0040).

This subpackage lets a household user link an Enable Banking ASPSP,
complete SCA in the browser, and sync transactions from the Penge UI
instead of the per-bank CLI. It reuses the existing connectors
(:mod:`penge.ingest.gls`, ``ebank``, ``lunar``) so accounts upsert on
``(provider, external_id)`` exactly as the CLI does — no duplicate
rows.

The feature only activates where the Enable Banking RSA private key is
configured in the API process (see :class:`ConnectionsConfig`); the
read API stays the safe default everywhere else.
"""

from __future__ import annotations

from penge.api.connections.config import ConnectionsConfig

__all__ = ["ConnectionsConfig"]
