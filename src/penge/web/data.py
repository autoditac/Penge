"""Typed read-only data access for the web dashboard.

All queries target the dbt marts in schema ``analytics_marts`` and the
canonical raw tables (``account``, ``entity``). Functions return plain
``pandas.DataFrame`` instances so they compose cleanly with Streamlit's
chart helpers and are trivial to fake in tests.

The engine is created lazily and cached at module level so importing
this module in unit tests never opens a network connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .config import database_url

if TYPE_CHECKING:
    from collections.abc import Mapping


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine.

    Lazily imported so ``import penge.web.data`` works without the
    psycopg driver installed (e.g. on a docs-only build).
    """
    from sqlalchemy import create_engine

    return create_engine(database_url(), pool_pre_ping=True)


def _read_sql(sql: str, params: Mapping[str, object] | None = None) -> pd.DataFrame:
    """Execute ``sql`` against the cached engine and return a DataFrame.

    Uses parameterised queries via SQLAlchemy ``text``; never interpolate
    user input into ``sql`` directly.
    """
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=dict(params or {}))


# ---------------------------------------------------------------------------
# Net-worth time series
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NetWorthRow:
    """A single row of ``mart_net_worth_daily`` (one account, one date)."""

    entity_id: str
    account_id: str
    account_currency: str
    as_of: date
    balance_acct_ccy: float
    balance_eur: float | None
    balance_dkk: float | None


_NET_WORTH_SQL = """
    select
        entity_id::text as entity_id,
        account_id::text as account_id,
        account_currency,
        as_of,
        balance_acct_ccy,
        balance_eur,
        balance_dkk
    from analytics_marts.mart_net_worth_daily
    where as_of >= :since
    order by as_of, account_id
"""


def fetch_net_worth_daily(since: date) -> pd.DataFrame:
    """Return the daily net-worth panel from ``since`` (inclusive) to today.

    Columns: ``entity_id``, ``account_id``, ``account_currency``,
    ``as_of``, ``balance_acct_ccy``, ``balance_eur``, ``balance_dkk``.
    """
    return _read_sql(_NET_WORTH_SQL, {"since": since})


# ---------------------------------------------------------------------------
# Account / entity dimensions
# ---------------------------------------------------------------------------


_ACCOUNTS_SQL = """
    select
        a.id::text as account_id,
        a.entity_id::text as entity_id,
        a.provider,
        a.name as account_name,
        a.kind as account_kind,
        a.currency,
        a.iban,
        a.opened_at,
        a.closed_at,
        e.name as entity_name,
        e.kind as entity_kind
    from account as a
    join entity as e on e.id = a.entity_id
    order by e.name, a.name
"""


def fetch_accounts() -> pd.DataFrame:
    """Return the full account dimension joined with its entity.

    The IBAN column is returned raw — callers are responsible for
    masking via :func:`penge.web.mask.mask_iban` before display.
    """
    return _read_sql(_ACCOUNTS_SQL)


# ---------------------------------------------------------------------------
# KPI helpers (pure functions over the daily panel)
# ---------------------------------------------------------------------------


def latest_total(panel: pd.DataFrame, currency: str) -> float | None:
    """Return the most recent totalled balance in the given display currency.

    ``currency`` must be ``"EUR"`` or ``"DKK"``. Returns ``None`` if the
    panel is empty or the column has no non-null rows.
    """
    column = balance_column(currency)
    if panel.empty or column not in panel.columns:
        return None
    latest_date = panel["as_of"].max()
    snapshot = panel.loc[panel["as_of"] == latest_date, column].dropna()
    if snapshot.empty:
        return None
    return float(snapshot.sum())


def delta_pct(panel: pd.DataFrame, currency: str, *, days_back: int) -> float | None:
    """Return the percent change in the totalled balance vs ``days_back`` ago.

    Picks the closest date at-or-before ``latest - days_back`` so weekend
    snapshots remain comparable. Returns ``None`` if either endpoint is
    missing.
    """
    column = balance_column(currency)
    if panel.empty or column not in panel.columns:
        return None
    latest_date = panel["as_of"].max()
    target = pd.Timestamp(latest_date) - pd.Timedelta(days=days_back)
    earlier = panel.loc[panel["as_of"] <= target.date(), "as_of"]
    if earlier.empty:
        return None
    earlier_date = earlier.max()
    now_total = panel.loc[panel["as_of"] == latest_date, column].dropna().sum()
    then_total = panel.loc[panel["as_of"] == earlier_date, column].dropna().sum()
    if then_total == 0:
        return None
    return float((now_total - then_total) / then_total * 100.0)


def balance_column(currency: str) -> str:
    """Return the panel column name for the given display currency."""
    upper = currency.upper()
    if upper == "EUR":
        return "balance_eur"
    if upper == "DKK":
        return "balance_dkk"
    msg = f"unsupported display currency: {currency!r} (expected EUR or DKK)"
    raise ValueError(msg)
