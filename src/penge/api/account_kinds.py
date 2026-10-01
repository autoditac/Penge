"""Reporting categories derived from canonical account kinds."""

from __future__ import annotations

_REPORTING_KIND_BY_ACCOUNT_KIND = {
    "opsparingskonto": "savings",
}


def reporting_kind(account_kind: str) -> str:
    """Return the reporting category while preserving the source account kind."""
    return _REPORTING_KIND_BY_ACCOUNT_KIND.get(account_kind, account_kind)
