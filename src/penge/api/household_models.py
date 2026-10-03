"""Typed response models for reconciled household income and expense reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from penge.analytics.household import PaymentEventKind, ReconciliationStatus


class HouseholdGranularity(StrEnum):
    """Supported report bucket sizes."""

    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class HouseholdTreatment(StrEnum):
    """Bank-movement treatment used by the household projection."""

    INCOME = "income"
    EXPENSE = "expense"
    REFUND = "refund"
    TRANSFER = "transfer"
    EXCLUDED = "excluded"
    UNCLASSIFIED = "unclassified"


class _FrozenModel(BaseModel):
    """Immutable response model that rejects undeclared fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HouseholdReportFilters(_FrozenModel):
    """Canonical filters echoed by all household report reads."""

    since: date
    until: date
    granularity: HouseholdGranularity
    account_ids: list[str]
    entity_ids: list[str]
    category_id: str | None


class HouseholdCurrencyAmount(_FrozenModel):
    """Known subtotal and conversion completeness for one currency."""

    amount: Decimal | None
    known_subtotal: Decimal
    complete: bool
    missing_count: int


class HouseholdCurrencyPair(_FrozenModel):
    """Amounts in EUR and DKK without a hidden base currency."""

    eur: HouseholdCurrencyAmount
    dkk: HouseholdCurrencyAmount


class HouseholdReportTotals(_FrozenModel):
    """Explicit income, gross, refund, net-expense, and surplus measures."""

    income: HouseholdCurrencyPair
    gross_expenses: HouseholdCurrencyPair
    refunds: HouseholdCurrencyPair
    net_expenses: HouseholdCurrencyPair
    surplus: HouseholdCurrencyPair


class HouseholdReportWindow(_FrozenModel):
    """Totals for a concrete inclusive date window."""

    since: date
    until: date
    totals: HouseholdReportTotals


class HouseholdReportChange(_FrozenModel):
    """Current-window totals minus previous-window totals."""

    income: HouseholdCurrencyPair
    gross_expenses: HouseholdCurrencyPair
    refunds: HouseholdCurrencyPair
    net_expenses: HouseholdCurrencyPair
    surplus: HouseholdCurrencyPair


class HouseholdTrendPoint(_FrozenModel):
    """A clipped trend bucket with household totals."""

    period_start: date
    period_end: date
    totals: HouseholdReportTotals


class HouseholdReportCoverage(_FrozenModel):
    """Coverage, classification, and reconciliation counts for a report."""

    history_start: date | None
    history_completeness: Literal["unknown"]
    bank_transaction_count: int
    included_transaction_count: int
    unclassified_transaction_count: int
    unclassified_expense_count: int
    unclassified_expense_amount: HouseholdCurrencyPair
    transfer_excluded_count: int
    excluded_transaction_count: int
    classification_review_count: int
    source_snapshot_drift_count: int
    allocation_mismatch_count: int
    missing_fx_allocation_count: int
    payment_detail_link_count: int
    payment_detail_reconciled_count: int
    payment_detail_review_count: int
    payment_detail_stale_count: int
    payment_detail_unmatched_count: int


class HouseholdReportFreshness(_FrozenModel):
    """Observation and source freshness metadata for a report response."""

    report_generated_at: datetime
    latest_bank_booking_date: date | None
    latest_bank_import_at: datetime | None
    latest_fx_rate_date: date | None
    latest_payment_detail_sync_at: datetime | None


class HouseholdReportSummaryResponse(_FrozenModel):
    """Selected-window household totals, trend, comparison, and coverage."""

    filters: HouseholdReportFilters
    current: HouseholdReportWindow
    previous: HouseholdReportWindow
    change: HouseholdReportChange
    points: list[HouseholdTrendPoint]
    coverage: HouseholdReportCoverage
    freshness: HouseholdReportFreshness


class HouseholdCategoryNode(_FrozenModel):
    """Category hierarchy node with descendant-inclusive totals."""

    category_id: str
    parent_id: str | None
    name: str
    kind: Literal["expense", "income"]
    sort_order: int
    archived: bool
    revision: int
    transaction_count: int
    totals: HouseholdReportTotals
    children: list[HouseholdCategoryNode]


class HouseholdCategoryReportResponse(_FrozenModel):
    """Category hierarchy and rollups under the common report filters."""

    filters: HouseholdReportFilters
    categories: list[HouseholdCategoryNode]
    coverage: HouseholdReportCoverage
    freshness: HouseholdReportFreshness


class HouseholdReportAllocation(_FrozenModel):
    """One signed category split on a canonical bank transaction."""

    category_id: str | None
    category_name: str | None
    category_path: list[str]
    treatment: HouseholdTreatment
    amount_native: Decimal
    currency: str
    amount_reporting: HouseholdCurrencyPair


class HouseholdPaymentDetailLink(_FrozenModel):
    """Minimal, whitelisted PayPal enrichment attached to a bank movement."""

    detail_id: str
    external_reference: str | None
    reference: str | None
    merchant_name: str | None
    event_kind: PaymentEventKind
    source_amount: Decimal
    source_currency: str
    source_date: date | None
    merchant_category_code: str | None
    bank_code: str | None
    bank_sub_code: str | None
    bank_amount: Decimal
    bank_currency: str
    approved_detail_revision: int
    current_detail_revision: int
    reconciliation_status: ReconciliationStatus


class HouseholdReportTransaction(_FrozenModel):
    """One bank transaction with complete source amount and split drilldown."""

    transaction_id: str
    value_date: date
    account_id: str
    entity_id: str
    description: str | None
    counterparty: str | None
    merchant_name: str | None
    treatment: HouseholdTreatment
    signed_amount_native: Decimal
    currency: str
    amount_reporting: HouseholdCurrencyPair
    matching_split_amount_native: Decimal
    matching_split_amount_reporting: HouseholdCurrencyPair
    allocations: list[HouseholdReportAllocation]
    payment_details: list[HouseholdPaymentDetailLink]
    payment_reconciliation_status: ReconciliationStatus | None


class HouseholdReportTransactionsResponse(_FrozenModel):
    """Stable paginated bank transaction drilldown."""

    filters: HouseholdReportFilters
    search: str | None
    items: list[HouseholdReportTransaction]
    limit: int
    offset: int
    total: int
