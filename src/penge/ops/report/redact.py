"""PII redaction for the monthly report.

The same key-name regex used by :mod:`penge.ops.sentry` and the MCP
audit logger is mirrored here so a change has to be made in three
places and shows up in code review. We deliberately do not import the
regex from ``penge.ops.sentry``: importing that module pulls in the
``sentry_sdk`` dependency on environments that only need the report
generator, and we want the redaction rule co-located with each
data path it guards.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACT_KEY_PATTERN = re.compile(r"(account|iban|cpr|tax[_-]?id|name|email)", re.IGNORECASE)
REDACTED = "[REDACTED]"

# Inline patterns covering values that may appear in user-supplied
# strings reaching the report body. We match conservatively — the
# report uses synthetic / aggregated data by construction, so these
# are a belt-and-braces defence against future regressions.
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_CPR_RE = re.compile(r"\b\d{6}-?\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def redact_text(value: str) -> str:
    """Return ``value`` with IBANs, CPRs, and email addresses redacted.

    The replacements are independent so a string mixing all three (an
    address line with an IBAN and an email, say) is fully scrubbed.
    """

    out = _IBAN_RE.sub(REDACTED, value)
    out = _CPR_RE.sub(REDACTED, out)
    out = _EMAIL_RE.sub(REDACTED, out)
    return out


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact a mapping by key name + value patterns.

    Mirrors :func:`penge.ops.sentry._redact` but is exposed publicly
    so the report data loader can scrub raw rows pulled from the
    database before they reach the renderers.
    """

    out: dict[str, Any] = {}
    for k, v in value.items():
        if isinstance(k, str) and REDACT_KEY_PATTERN.search(k):
            out[k] = REDACTED
            continue
        out[k] = _redact_value(v)
    return out


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
