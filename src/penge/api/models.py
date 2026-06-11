"""Pydantic response models for the read API.

Every money-bearing model carries the account-currency amount plus the
EUR and DKK conversions in parallel (ADR-0004: no silent base
currency). Amounts are ``Decimal`` end-to-end — the marts persist
``numeric(20, 4)`` and psycopg returns ``Decimal``, so no float ever
enters the pipeline. On the wire, Pydantic serialises ``Decimal`` as
JSON **strings** (e.g. ``"1000.0000"``): lossless by construction, and
the generated TypeScript client converts explicitly at the edge.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class GroupBy(StrEnum):
    """Aggregation level for the net-worth series."""

    ACCOUNT = "account"
    TOTAL = "total"


class AllocationDimension(StrEnum):
    """Grouping dimension for the current-allocation endpoint."""

    ENTITY = "entity"
    CURRENCY = "currency"
    KIND = "kind"


class _FrozenModel(BaseModel):
    """Base for all response models: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NetWorthPoint(_FrozenModel):
    """One account-day row of ``mart_net_worth_daily``."""

    as_of: date
    entity_id: str
    account_id: str
    account_currency: str
    balance_acct_ccy: Decimal
    balance_eur: Decimal | None
    balance_dkk: Decimal | None


class NetWorthTotalPoint(_FrozenModel):
    """One day of the net-worth series summed across all accounts."""

    as_of: date
    balance_eur: Decimal | None
    balance_dkk: Decimal | None


class NetWorthSeriesResponse(_FrozenModel):
    """Paginated net-worth series at account granularity."""

    points: list[NetWorthPoint]
    limit: int
    offset: int
    total: int


class NetWorthTotalSeriesResponse(_FrozenModel):
    """Net-worth series aggregated to one row per day."""

    points: list[NetWorthTotalPoint]
    limit: int
    offset: int
    total: int


class CashflowPoint(_FrozenModel):
    """One account-day row of ``mart_cashflow_daily``.

    Days without transactions produce no row; consumers treat absent
    days as zero (same contract as the MCP ``query_cashflow`` tool).
    """

    as_of: date
    entity_id: str
    account_id: str
    account_currency: str
    inflow_acct_ccy: Decimal
    outflow_acct_ccy: Decimal
    net_acct_ccy: Decimal
    inflow_eur: Decimal | None
    outflow_eur: Decimal | None
    net_eur: Decimal | None
    inflow_dkk: Decimal | None
    outflow_dkk: Decimal | None
    net_dkk: Decimal | None


class CashflowSeriesResponse(_FrozenModel):
    """Paginated cashflow series at account granularity."""

    points: list[CashflowPoint]
    limit: int
    offset: int
    total: int


class AllocationSlice(_FrozenModel):
    """One slice of the latest-day allocation, grouped by a dimension.

    ``weight_eur`` is this slice's share of the EUR total (0..1);
    ``None`` when the EUR total is zero or missing.
    """

    label: str
    balance_eur: Decimal | None
    balance_dkk: Decimal | None
    weight_eur: Decimal | None


class AllocationResponse(_FrozenModel):
    """Current allocation snapshot grouped by one dimension."""

    as_of: date | None
    by: AllocationDimension
    slices: list[AllocationSlice]


class AccountSummary(_FrozenModel):
    """Account dimension row with identifiers masked server-side.

    ``iban_masked`` keeps only the last four characters
    (``penge.web.mask.mask_iban``); the raw IBAN never leaves the API.
    """

    account_id: str
    entity_id: str
    entity_name: str
    provider: str
    name: str
    kind: str
    currency: str
    iban_masked: str


class MartFreshness(_FrozenModel):
    """Latest data date and row count for one mart."""

    mart: str
    latest_as_of: date | None
    row_count: int


class FreshnessResponse(_FrozenModel):
    """Freshness metadata for every mart the API serves."""

    marts: list[MartFreshness]
