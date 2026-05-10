"""Outbound push heartbeats for Uptime Kuma "Push" monitors.

Cron jobs and scheduled ingestion scripts have no long-lived HTTP
surface that Uptime Kuma can scrape. The push pattern inverts the
relationship: the job hits a unique URL on success (and optionally on
failure), and Uptime Kuma raises an alert if the heartbeat goes stale.

The push URL prefix is configured once via the
``PENGE_UPTIME_KUMA_PUSH_URL`` env var, e.g.::

    PENGE_UPTIME_KUMA_PUSH_URL=https://uptime.example.invalid/api/push

The per-job *slug* is the random token Uptime Kuma generates when the
push monitor is created. The full request URL becomes
``<prefix>/<slug>?status=...&msg=...&ping=``.

Design notes
------------

* **No-op when unset.** If ``PENGE_UPTIME_KUMA_PUSH_URL`` is missing or
  empty, :func:`heartbeat` returns silently. Local dev and tests do not
  hit the network.
* **Fire-and-forget.** Network or HTTP errors are logged at WARNING and
  swallowed; a failed heartbeat must never break the ingestion job
  itself. Uptime Kuma already alerts on stale heartbeats, so a missed
  ping shows up as the same "monitor down" event the operator already
  watches for.
* **Short timeout.** The default 5-second timeout keeps a misbehaving
  Uptime Kuma instance from stalling cron runs.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx

log = logging.getLogger("penge.ops.heartbeat")

ENV_PUSH_URL = "PENGE_UPTIME_KUMA_PUSH_URL"
DEFAULT_TIMEOUT_S = 5.0


def heartbeat(
    slug: str,
    status: str = "up",
    message: str = "",
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: httpx.Client | None = None,
) -> None:
    """Send a push heartbeat to Uptime Kuma.

    Parameters
    ----------
    slug:
        The push-monitor token from Uptime Kuma. Appended to the URL
        prefix as ``<prefix>/<slug>``.
    status:
        ``"up"`` (default) or ``"down"``. Uptime Kuma also accepts
        ``"ping"`` for latency-only updates.
    message:
        Free-form human-readable message; shown in the Uptime Kuma UI
        next to the heartbeat. Sent as the ``msg`` query parameter.
    timeout_s:
        Per-request timeout. Defaults to 5 seconds.
    client:
        Optional pre-configured :class:`httpx.Client` (used by tests).
        When ``None``, a short-lived client is created and closed here.
    """

    if not slug:
        raise ValueError("heartbeat() requires a non-empty slug")

    prefix = os.environ.get(ENV_PUSH_URL, "").strip()
    if not prefix:
        log.debug("heartbeat skipped: %s unset", ENV_PUSH_URL)
        return

    url = f"{prefix.rstrip('/')}/{quote(slug, safe='')}"
    params = {"status": status, "msg": message, "ping": ""}

    try:
        if client is None:
            with httpx.Client(timeout=timeout_s) as owned:
                response = owned.get(url, params=params)
        else:
            response = client.get(url, params=params, timeout=timeout_s)
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        log.warning("heartbeat failed slug=%s status=%s err=%s", slug, status, exc)
