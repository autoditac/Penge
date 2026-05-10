"""Operational glue: heartbeats and error reporting.

The :mod:`penge.ops` package owns the integrations that keep the platform
observable from the outside:

* :mod:`penge.ops.heartbeat` — outbound push pings to Uptime Kuma for
  cron / scheduled ingestion jobs that have no long-lived HTTP surface.
* :mod:`penge.ops.sentry` — Sentry SDK initialization with PII scrubbing
  for ingestion entry points.

Both modules are designed to **no-op when their environment variables
are unset** so unit tests, fixtures, and offline development never hit
the network or crash on missing configuration. See
``docs/runbook/healthchecks.md`` for the operator-facing setup guide.
"""

from penge.ops.heartbeat import heartbeat
from penge.ops.sentry import init_sentry

__all__ = ["heartbeat", "init_sentry"]
