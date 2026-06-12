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


class ReturnsScope(StrEnum):
    """Scope dimension of ``mart_returns_daily`` (ADR-0039)."""

    ACCOUNT = "account"
    ASSET_CLASS = "asset_class"
    HOUSEHOLD = "household"


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


class ReturnsPoint(_FrozenModel):
    """One scope-day row of ``mart_returns_daily``.

    The return factor follows the start-of-day flow convention
    ``end_mv / (begin_mv + net_flow)`` and is ``None`` on days without
    capital at risk (ADR-0039).
    """

    as_of: date
    scope: ReturnsScope
    scope_key: str
    begin_mv_eur: Decimal | None
    end_mv_eur: Decimal | None
    net_flow_eur: Decimal | None
    return_factor_eur: Decimal | None
    begin_mv_dkk: Decimal | None
    end_mv_dkk: Decimal | None
    net_flow_dkk: Decimal | None
    return_factor_dkk: Decimal | None


class ReturnsSeriesResponse(_FrozenModel):
    """Paginated daily return-factor series for one scope."""

    points: list[ReturnsPoint]
    limit: int
    offset: int
    total: int


class CurrencyReturnSummary(_FrozenModel):
    """TWR/MWR figures for one measurement currency.

    ``error`` carries a data-quality note when the series could not be
    chain-linked faithfully; all figures are then ``None`` rather than
    a fabricated number.
    """

    cumulative_return: Decimal | None
    annualized_return: float | None
    mwr_annualized: float | None
    error: str | None


class ReturnsSummaryEntry(_FrozenModel):
    """Chain-linked TWR and MWR for one scope key over the window."""

    scope: ReturnsScope
    scope_key: str
    start_date: date | None
    end_date: date | None
    days: int
    eur: CurrencyReturnSummary
    dkk: CurrencyReturnSummary


class ReturnsSummaryResponse(_FrozenModel):
    """Per-scope-key return summaries over one request window."""

    since: date
    until: date
    scope: ReturnsScope
    entries: list[ReturnsSummaryEntry]


class BenchmarkInfo(_FrozenModel):
    """One instrument with ingested price history, usable as benchmark."""

    instrument_id: str
    name: str
    ticker: str | None
    currency: str
    first_as_of: date | None
    last_as_of: date | None
    points: int


class BenchmarkPoint(_FrozenModel):
    """One daily close of a benchmark instrument (native currency)."""

    as_of: date
    close: Decimal
    currency: str


class BenchmarkSeriesResponse(_FrozenModel):
    """Paginated daily close series for one benchmark instrument."""

    instrument_id: str
    points: list[BenchmarkPoint]
    limit: int
    offset: int
    total: int


class FeeYearRow(_FrozenModel):
    """Fees recorded for one account in one calendar year.

    Sums explicit ``fee``-kind transactions plus the ``fee`` column on
    trades, converted at the forward-filled ECB rate of the fee date.
    """

    year: int
    account_id: str
    fees_eur: Decimal | None
    fees_dkk: Decimal | None


class FeesResponse(_FrozenModel):
    """Yearly fee totals per account over one request window."""

    since: date
    until: date
    rows: list[FeeYearRow]
