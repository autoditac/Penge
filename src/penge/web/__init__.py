"""Streamlit dashboard for net-worth and allocation views.

This is the v1 skeleton (issue #25). It renders four views against the
loaded data:

- KPI: today's net worth in EUR / DKK with MoM and YoY deltas.
- Time series: stacked area grouped by account currency. Asset-class
  grouping is a follow-up — the v1 mart does not yet expose
  ``instrument.kind``.
- Allocation: pie charts by entity, currency, and account kind.
- Account drill-down: per-account balance over time, with masked
  identifiers by default.

Designed to run **local-only** behind Tailscale or Caddy basic-auth; no
authentication is performed in-process. See
``docs/runbook/web.md`` for deploy notes.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
