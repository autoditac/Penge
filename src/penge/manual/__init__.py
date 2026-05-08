"""Manual-entry CLI for cash balances and real-estate valuations.

Wraps SQLAlchemy upserts behind a small Typer-based CLI so the user
can record manually-tracked accounts (cash, property) without writing
SQL. Issue #20.
"""

from __future__ import annotations

from .entries import BalanceEntry, PropertyEntry
from .service import record_cash_balance, record_property_value

__all__ = [
    "BalanceEntry",
    "PropertyEntry",
    "record_cash_balance",
    "record_property_value",
]
