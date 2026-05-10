"""Sentry SDK initialization with PII scrubbing.

Ingestion entry points (the vault watcher CLI and connector ``__main__``
modules) call :func:`init_sentry` near the top of ``main()``. When the
``SENTRY_DSN`` env var is unset, initialization is a no-op so local
development, CI, and offline runs do not crash or phone home.

PII scrubbing
-------------

Personal-finance data must never leak into a third-party error tracker.
The :func:`before_send` hook walks the event payload (``request``,
``extra``, ``tags``, ``contexts``, ``breadcrumbs``, ``exception`` values)
and replaces any value whose **key** matches the same regex used by the
MCP audit logger (`apps/mcp/src/audit.ts`)::

    account | iban | cpr | tax_id | name | email

Mirroring that single regex in two places is deliberate: redaction
rules belong with the data path, not in a config file, so a change has
to be made in both languages and shows up in code review.

Idempotency
-----------

:func:`init_sentry` may be called multiple times in a process — for
example when an ingestion job imports both a CLI entrypoint and a
library that also initialises. The implementation tracks initialization
state via a module-level flag so subsequent calls return early.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping
from typing import Any, cast

try:  # pragma: no cover - exercised in the "no dep" test path
    import sentry_sdk as _sentry_sdk
except ImportError:  # pragma: no cover
    _sentry_sdk = None

log = logging.getLogger("penge.ops.sentry")

ENV_DSN = "SENTRY_DSN"
ENV_ENVIRONMENT = "SENTRY_ENVIRONMENT"
ENV_RELEASE = "SENTRY_RELEASE"

REDACT_KEY_PATTERN = re.compile(r"(account|iban|cpr|tax[_-]?id|name|email)", re.IGNORECASE)
REDACTED = "[REDACTED]"

# Module-level mutable state so :func:`init_sentry` is idempotent. Held in a
# dict so the flag can be mutated without a ``global`` statement (ruff PLW0603).
_state: dict[str, bool] = {"initialized": False}


def _redact(value: Any) -> Any:
    """Recursively redact dict values whose key matches REDACT_KEY_PATTERN."""

    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and REDACT_KEY_PATTERN.search(k):
                out[k] = REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Sentry ``before_send`` hook: redact PII before transmission.

    The hook is also exposed as a top-level function so the unit tests
    can exercise it without spinning up the SDK.
    """

    return cast(dict[str, Any], _redact(event))


def init_sentry(
    *,
    dsn: str | None = None,
    environment: str | None = None,
    release: str | None = None,
    component: str | None = None,
) -> bool:
    """Initialize the Sentry SDK if a DSN is configured.

    Parameters
    ----------
    dsn:
        Override the DSN. When ``None``, ``SENTRY_DSN`` is read.
    environment:
        Override the environment tag. When ``None``,
        ``SENTRY_ENVIRONMENT`` is read; falls back to
        ``PENGE_ENV`` and finally ``"dev"``.
    release:
        Override the release identifier. When ``None``,
        ``SENTRY_RELEASE`` is read.
    component:
        Optional tag identifying the entry point (e.g. ``"vault-watcher"``,
        ``"ingest.gls"``) so events are filterable in the Sentry UI.

    Returns
    -------
    bool
        ``True`` if Sentry was initialised on this call, ``False`` if the
        DSN was unset or initialisation was already done.
    """

    if _state["initialized"]:
        log.debug("sentry init skipped: already initialized")
        return False

    resolved_dsn = (dsn if dsn is not None else os.environ.get(ENV_DSN, "")).strip()
    if not resolved_dsn:
        log.debug("sentry init skipped: %s unset", ENV_DSN)
        return False

    # Resolve the SDK at call time so tests can monkey-patch
    # ``sys.modules["sentry_sdk"]`` to inject a fake.
    sentry_sdk = sys.modules.get("sentry_sdk", _sentry_sdk)
    if sentry_sdk is None:
        log.warning("sentry init skipped: sentry-sdk not installed")
        return False

    resolved_env = (
        environment
        if environment is not None
        else os.environ.get(ENV_ENVIRONMENT) or os.environ.get("PENGE_ENV") or "dev"
    )
    resolved_release = release if release is not None else os.environ.get(ENV_RELEASE)

    sentry_sdk.init(
        dsn=resolved_dsn,
        environment=resolved_env,
        release=resolved_release,
        before_send=before_send,
        send_default_pii=False,
        attach_stacktrace=True,
    )
    if component:
        sentry_sdk.set_tag("component", component)

    _state["initialized"] = True
    log.info("sentry initialized environment=%s component=%s", resolved_env, component or "-")
    return True


def _reset_for_tests() -> None:
    """Reset module state. Test-only helper."""

    _state["initialized"] = False
