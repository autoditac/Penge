"""Pure aggregation and reconciliation rules for household reporting.

Financial totals are derived exclusively from signed bank-ledger
allocations. Payment-provider detail is attached only as enrichment and
never contributes a second amount to household totals.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class HouseholdReportingError(ValueError):
    """Raised when household reporting facts violate their invariants."""


class AllocationTreatment(StrEnum):
    """Economic treatment assigned to a signed bank allocation."""

    INCOME = "income"
    EXPENSE = "expense"
    REFUND = "refund"
    TRANSFER = "transfer"
    EXCLUDED = "excluded"
    UNCLASSIFIED = "unclassified"


class PaymentEventKind(StrEnum):
    """Conservative PayPal source-event semantics."""

    PURCHASE = "purchase"
    REFUND = "refund"
    FUNDING = "funding"
    UNKNOWN = "unknown"


class ReconciliationStatus(StrEnum):
    """Status of explicit bank-to-payment-detail allocations."""

    UNMATCHED = "unmatched"
    REVIEW = "review"
    RECONCILED = "reconciled"
    STALE = "stale"


@dataclass(frozen=True)
class Category:
    """Category node used to scope and roll up allocation facts."""

    category_id: str
    parent_id: str | None
    kind: str | None = None
    name: str = ""
    sort_order: int = 0
    archived: bool = False
    revision: int = 1


@dataclass(frozen=True)
class CurrencyAmount:
    """Known subtotal and completeness for one reporting currency."""

    amount: Decimal | None
    known_subtotal: Decimal
    complete: bool
    missing_count: int


@dataclass(frozen=True)
class CurrencyPair:
    """EUR and DKK values kept side by side."""

    eur: CurrencyAmount
    dkk: CurrencyAmount


@dataclass(frozen=True)
class ReportTotals:
    """Household report totals with explicit gross/refund/net semantics."""

    income: CurrencyPair
    gross_expenses: CurrencyPair
    refunds: CurrencyPair
    net_expenses: CurrencyPair
    surplus: CurrencyPair


@dataclass(frozen=True)
class PaymentDetail:
    """Whitelisted payment detail; never an independent cashflow fact."""

    detail_id: str
    external_reference: str | None
    revision: int
    amount: Decimal
    currency: str
    event_kind: PaymentEventKind = PaymentEventKind.UNKNOWN
    merchant_name: str | None = None
    reference: str | None = None
    source_date: date | None = None
    merchant_category_code: str | None = None
    bank_code: str | None = None
    bank_sub_code: str | None = None


@dataclass(frozen=True)
class PaymentDetailAllocation:
    """Explicit allocation from one provider detail to a bank movement."""

    detail: PaymentDetail
    bank_amount: Decimal
    detail_revision: int
    approved: bool


@dataclass(frozen=True)
class BankAllocation:
    """A signed category/treatment split of one bank transaction."""

    category_id: str | None
    treatment: AllocationTreatment
    amount_native: Decimal
    amount_eur: Decimal | None
    amount_dkk: Decimal | None


@dataclass(frozen=True)
class BankTransaction:
    """Canonical bank movement and optional detail-only enrichment."""

    transaction_id: str
    value_date: date
    account_id: str
    entity_id: str
    amount_native: Decimal
    currency: str
    allocations: tuple[BankAllocation, ...]
    payment_details: tuple[PaymentDetailAllocation, ...] = field(default_factory=tuple)
    description: str | None = None
    counterparty: str | None = None
    created_at: datetime | None = None
    classification_source_current: bool = False
    source_snapshot_drift: bool = False
    classification_review_state: str | None = None
    allocation_mismatch: bool = False


@dataclass
class _CurrencyAccumulator:
    known_subtotal: Decimal = Decimal(0)
    missing_count: int = 0

    def add(self, amount: Decimal | None) -> None:
        if amount is None:
            self.missing_count += 1
        else:
            self.known_subtotal += amount

    def finish(self) -> CurrencyAmount:
        complete = self.missing_count == 0
        return CurrencyAmount(
            amount=self.known_subtotal if complete else None,
            known_subtotal=self.known_subtotal,
            complete=complete,
            missing_count=self.missing_count,
        )


@dataclass
class _MetricAccumulator:
    eur: _CurrencyAccumulator = field(default_factory=_CurrencyAccumulator)
    dkk: _CurrencyAccumulator = field(default_factory=_CurrencyAccumulator)

    def add(self, eur: Decimal | None, dkk: Decimal | None) -> None:
        self.eur.add(eur)
        self.dkk.add(dkk)

    def finish(self) -> CurrencyPair:
        return CurrencyPair(eur=self.eur.finish(), dkk=self.dkk.finish())


class _TotalsAccumulator:
    def __init__(self) -> None:
        self.income = _MetricAccumulator()
        self.gross_expenses = _MetricAccumulator()
        self.refunds = _MetricAccumulator()

    def finish(self) -> ReportTotals:
        income = self.income.finish()
        gross_expenses = self.gross_expenses.finish()
        refunds = self.refunds.finish()
        net_expenses = _subtract_pairs(gross_expenses, refunds)
        surplus = _subtract_pairs(income, net_expenses)
        return ReportTotals(
            income=income,
            gross_expenses=gross_expenses,
            refunds=refunds,
            net_expenses=net_expenses,
            surplus=surplus,
        )


@dataclass(frozen=True)
class HouseholdReport:
    """Aggregated report values and bank-ledger coverage counts."""

    totals: ReportTotals
    included_transaction_count: int
    unclassified_transaction_count: int
    unclassified_expense_count: int
    unclassified_expense_amount: CurrencyPair
    transfer_excluded_count: int
    missing_fx_allocation_count: int


@dataclass(frozen=True)
class CategoryRollup:
    """Descendant-inclusive aggregate for one category node."""

    totals: ReportTotals
    transaction_count: int


def previous_window(since: date, until: date) -> tuple[date, date]:
    """Return the contiguous previous window with the same inclusive length."""
    _validate_window(since, until)
    duration = until - since + timedelta(days=1)
    return since - duration, since - timedelta(days=1)


def subtract_report_totals(left: ReportTotals, right: ReportTotals) -> ReportTotals:
    """Subtract a previous report window from a current report window."""
    return ReportTotals(
        income=_subtract_pairs(left.income, right.income),
        gross_expenses=_subtract_pairs(left.gross_expenses, right.gross_expenses),
        refunds=_subtract_pairs(left.refunds, right.refunds),
        net_expenses=_subtract_pairs(left.net_expenses, right.net_expenses),
        surplus=_subtract_pairs(left.surplus, right.surplus),
    )


def bucket_start(value_date: date, granularity: str) -> date:
    """Return the UTC calendar bucket start for a supported report grain."""
    if granularity == "day":
        return value_date
    if granularity == "month":
        return value_date.replace(day=1)
    if granularity == "year":
        return value_date.replace(month=1, day=1)
    raise HouseholdReportingError(f"unsupported household report granularity: {granularity}")


def aggregate_bank_transactions(
    transactions: Iterable[BankTransaction],
    categories: Iterable[Category],
    *,
    since: date,
    until: date,
    account_ids: frozenset[str] | None = None,
    entity_ids: frozenset[str] | None = None,
    category_id: str | None = None,
) -> HouseholdReport:
    """Aggregate selected bank allocations once, ignoring sidecar amounts.

    A category filter includes the selected category and its descendants.
    Each transaction is counted once even when multiple of its split lines
    match the filter.
    """
    _validate_window(since, until)
    category_list = tuple(categories)
    ancestors = _category_ancestors(category_list)
    category_kinds = {category.category_id: category.kind for category in category_list}
    if category_id is not None and category_id not in ancestors:
        raise HouseholdReportingError(f"unknown category id: {category_id}")
    selected_categories = _descendants(ancestors, category_id) if category_id is not None else None

    totals = _TotalsAccumulator()
    unclassified_expenses = _MetricAccumulator()
    transaction_ids: set[str] = set()
    included_ids: set[str] = set()
    unclassified_transaction_ids: set[str] = set()
    unclassified_ids: set[str] = set()
    transfer_only_ids: set[str] = set()
    missing_fx_allocations = 0

    for transaction in transactions:
        _validate_transaction(transaction, ancestors, category_kinds)
        if transaction.transaction_id in transaction_ids:
            raise HouseholdReportingError(
                f"duplicate bank transaction id: {transaction.transaction_id}"
            )
        transaction_ids.add(transaction.transaction_id)

        if not _matches_scope(
            transaction,
            since=since,
            until=until,
            account_ids=account_ids,
            entity_ids=entity_ids,
        ):
            continue

        matched_allocations = _matching_allocations(
            transaction.allocations,
            selected_categories=selected_categories,
        )
        if not matched_allocations:
            continue

        counted_allocations = _counted_allocations(matched_allocations)
        transfer_allocations = _transfer_allocations(matched_allocations)
        if transfer_allocations and not counted_allocations:
            transfer_only_ids.add(transaction.transaction_id)
        if not counted_allocations:
            if _has_unclassified(matched_allocations):
                unclassified_transaction_ids.add(transaction.transaction_id)
            continue

        reported_allocations = _reportable_allocations(counted_allocations)
        if reported_allocations:
            included_ids.add(transaction.transaction_id)
        if _has_unclassified(counted_allocations):
            unclassified_transaction_ids.add(transaction.transaction_id)
        missing, unclassified_expense = _accumulate_allocations(
            reported_allocations,
            totals=totals,
            unclassified_expenses=unclassified_expenses,
        )
        missing_fx_allocations += missing
        if unclassified_expense:
            unclassified_ids.add(transaction.transaction_id)

    return HouseholdReport(
        totals=totals.finish(),
        included_transaction_count=len(included_ids),
        unclassified_transaction_count=len(unclassified_transaction_ids),
        unclassified_expense_count=len(unclassified_ids),
        unclassified_expense_amount=unclassified_expenses.finish(),
        transfer_excluded_count=len(transfer_only_ids),
        missing_fx_allocation_count=missing_fx_allocations,
    )


def category_rollups(
    transactions: Iterable[BankTransaction],
    categories: Iterable[Category],
    *,
    since: date,
    until: date,
    account_ids: frozenset[str] | None = None,
    entity_ids: frozenset[str] | None = None,
) -> dict[str, CategoryRollup]:
    """Aggregate leaf allocations once at each category and its ancestors."""
    _validate_window(since, until)
    category_list = tuple(categories)
    ancestors = _category_ancestors(category_list)
    category_kinds = {category.category_id: category.kind for category in category_list}
    accumulators = {category.category_id: _TotalsAccumulator() for category in category_list}
    transaction_ids: dict[str, set[str]] = {
        category.category_id: set() for category in category_list
    }
    seen_transactions: set[str] = set()
    for transaction in transactions:
        _validate_transaction(transaction, ancestors, category_kinds)
        if transaction.transaction_id in seen_transactions:
            raise HouseholdReportingError(
                f"duplicate bank transaction id: {transaction.transaction_id}"
            )
        seen_transactions.add(transaction.transaction_id)
        if not since <= transaction.value_date <= until:
            continue
        if account_ids is not None and transaction.account_id not in account_ids:
            continue
        if entity_ids is not None and transaction.entity_id not in entity_ids:
            continue
        for allocation in transaction.allocations:
            if allocation.category_id is not None and allocation.treatment in (
                AllocationTreatment.INCOME,
                AllocationTreatment.EXPENSE,
                AllocationTreatment.REFUND,
            ):
                for category_id in ancestors[allocation.category_id]:
                    if allocation.treatment is AllocationTreatment.INCOME:
                        accumulators[category_id].income.add(
                            allocation.amount_eur, allocation.amount_dkk
                        )
                    elif allocation.treatment is AllocationTreatment.EXPENSE:
                        accumulators[category_id].gross_expenses.add(
                            _absolute_or_none(allocation.amount_eur),
                            _absolute_or_none(allocation.amount_dkk),
                        )
                    elif allocation.treatment is AllocationTreatment.REFUND:
                        accumulators[category_id].refunds.add(
                            allocation.amount_eur, allocation.amount_dkk
                        )
                    transaction_ids[category_id].add(transaction.transaction_id)

    return {
        category_id: CategoryRollup(
            totals=accumulator.finish(),
            transaction_count=len(transaction_ids[category_id]),
        )
        for category_id, accumulator in accumulators.items()
    }


def reconciliation_status(
    bank_amount: Decimal,
    allocations: Iterable[PaymentDetailAllocation],
) -> ReconciliationStatus:
    """Assess explicit detail allocations without changing bank totals."""
    allocation_list = tuple(allocations)
    if not allocation_list:
        return ReconciliationStatus.UNMATCHED

    detail_ids: set[str] = set()
    approved_amount = Decimal(0)
    stale = False
    review = False
    for allocation in allocation_list:
        if allocation.detail.detail_id in detail_ids:
            raise HouseholdReportingError(
                f"duplicate payment detail allocation: {allocation.detail.detail_id}"
            )
        detail_ids.add(allocation.detail.detail_id)
        if allocation.approved and allocation.detail_revision != allocation.detail.revision:
            stale = True
        elif allocation.approved:
            approved_amount += allocation.bank_amount
        else:
            review = True

    if stale:
        return ReconciliationStatus.STALE
    if review or approved_amount != bank_amount:
        return ReconciliationStatus.REVIEW
    return ReconciliationStatus.RECONCILED


def _category_ancestors(categories: Iterable[Category]) -> dict[str, tuple[str, ...]]:
    """Validate the tree and map every node to its root-to-node lineage."""
    parents: dict[str, str | None] = {}
    for category in categories:
        if category.category_id in parents:
            raise HouseholdReportingError(f"duplicate category id: {category.category_id}")
        parents[category.category_id] = category.parent_id

    ancestors: dict[str, tuple[str, ...]] = {}
    for category_id in parents:
        lineage: list[str] = []
        current: str | None = category_id
        while current is not None:
            if current in lineage:
                raise HouseholdReportingError(f"category cycle contains {current}")
            if current not in parents:
                raise HouseholdReportingError(f"unknown category parent: {current}")
            lineage.append(current)
            current = parents[current]
        ancestors[category_id] = tuple(reversed(lineage))
    return ancestors


def _descendants(
    ancestors: dict[str, tuple[str, ...]],
    category_id: str,
) -> frozenset[str]:
    return frozenset(
        candidate for candidate, lineage in ancestors.items() if category_id in lineage
    )


def _matches_scope(
    transaction: BankTransaction,
    *,
    since: date,
    until: date,
    account_ids: frozenset[str] | None,
    entity_ids: frozenset[str] | None,
) -> bool:
    return (
        since <= transaction.value_date <= until
        and (account_ids is None or transaction.account_id in account_ids)
        and (entity_ids is None or transaction.entity_id in entity_ids)
    )


def _matching_allocations(
    allocations: tuple[BankAllocation, ...],
    *,
    selected_categories: frozenset[str] | None,
) -> list[BankAllocation]:
    return [
        allocation
        for allocation in allocations
        if selected_categories is None or allocation.category_id in selected_categories
    ]


def _counted_allocations(allocations: list[BankAllocation]) -> list[BankAllocation]:
    return [
        allocation
        for allocation in allocations
        if allocation.treatment not in (AllocationTreatment.TRANSFER, AllocationTreatment.EXCLUDED)
    ]


def _transfer_allocations(allocations: list[BankAllocation]) -> list[BankAllocation]:
    return [
        allocation
        for allocation in allocations
        if allocation.treatment is AllocationTreatment.TRANSFER
    ]


def _has_unclassified(allocations: list[BankAllocation]) -> bool:
    return any(
        allocation.treatment is AllocationTreatment.UNCLASSIFIED for allocation in allocations
    )


def _reportable_allocations(allocations: list[BankAllocation]) -> list[BankAllocation]:
    return [
        allocation
        for allocation in allocations
        if allocation.treatment is not AllocationTreatment.UNCLASSIFIED
        or allocation.amount_native != 0
    ]


def _accumulate_allocations(
    allocations: list[BankAllocation],
    *,
    totals: _TotalsAccumulator,
    unclassified_expenses: _MetricAccumulator,
) -> tuple[int, bool]:
    missing_fx = 0
    has_unclassified_expense = False
    for allocation in allocations:
        missing_fx += int(allocation.amount_eur is None or allocation.amount_dkk is None)
        if allocation.treatment is AllocationTreatment.INCOME:
            totals.income.add(allocation.amount_eur, allocation.amount_dkk)
        elif allocation.treatment is AllocationTreatment.EXPENSE:
            expense_eur = _absolute_or_none(allocation.amount_eur)
            expense_dkk = _absolute_or_none(allocation.amount_dkk)
            totals.gross_expenses.add(expense_eur, expense_dkk)
            if allocation.category_id is None:
                has_unclassified_expense = True
                unclassified_expenses.add(expense_eur, expense_dkk)
        elif allocation.treatment is AllocationTreatment.REFUND:
            totals.refunds.add(allocation.amount_eur, allocation.amount_dkk)
        elif allocation.treatment is AllocationTreatment.UNCLASSIFIED:
            if allocation.amount_native > 0:
                totals.income.add(allocation.amount_eur, allocation.amount_dkk)
            else:
                expense_eur = _absolute_or_none(allocation.amount_eur)
                expense_dkk = _absolute_or_none(allocation.amount_dkk)
                totals.gross_expenses.add(expense_eur, expense_dkk)
                has_unclassified_expense = True
                unclassified_expenses.add(expense_eur, expense_dkk)
    return missing_fx, has_unclassified_expense


def _validate_transaction(
    transaction: BankTransaction,
    categories: dict[str, tuple[str, ...]],
    category_kinds: dict[str, str | None],
) -> None:
    if not transaction.allocations:
        raise HouseholdReportingError(
            f"bank transaction {transaction.transaction_id} has no allocations"
        )
    native_total = Decimal(0)
    for allocation in transaction.allocations:
        if allocation.category_id is not None and allocation.category_id not in categories:
            raise HouseholdReportingError(
                f"unknown category id on transaction {transaction.transaction_id}: "
                f"{allocation.category_id}"
            )
        if allocation.category_id is not None:
            category_kind = category_kinds[allocation.category_id]
            if (
                category_kind is not None
                and allocation.treatment is AllocationTreatment.INCOME
                and category_kind != "income"
            ):
                raise HouseholdReportingError("income allocations require income categories")
            if (
                category_kind is not None
                and allocation.treatment
                in (AllocationTreatment.EXPENSE, AllocationTreatment.REFUND)
                and category_kind != "expense"
            ):
                raise HouseholdReportingError(
                    "expense and refund allocations require expense categories"
                )
        if allocation.treatment is AllocationTreatment.INCOME and allocation.amount_native < 0:
            raise HouseholdReportingError("income allocations must be non-negative")
        if allocation.treatment is AllocationTreatment.EXPENSE and allocation.amount_native > 0:
            raise HouseholdReportingError("expense allocations must be non-positive")
        if allocation.treatment is AllocationTreatment.REFUND and allocation.amount_native < 0:
            raise HouseholdReportingError("refund allocations must be non-negative")
        native_total += allocation.amount_native
    if native_total != transaction.amount_native:
        raise HouseholdReportingError(
            f"transaction {transaction.transaction_id} allocations total {native_total} "
            f"but bank amount is {transaction.amount_native}"
        )


def _absolute_or_none(amount: Decimal | None) -> Decimal | None:
    return abs(amount) if amount is not None else None


def _subtract_currency_amounts(left: CurrencyAmount, right: CurrencyAmount) -> CurrencyAmount:
    known_subtotal = left.known_subtotal - right.known_subtotal
    missing_count = left.missing_count + right.missing_count
    complete = missing_count == 0
    return CurrencyAmount(
        amount=known_subtotal if complete else None,
        known_subtotal=known_subtotal,
        complete=complete,
        missing_count=missing_count,
    )


def _subtract_pairs(left: CurrencyPair, right: CurrencyPair) -> CurrencyPair:
    return CurrencyPair(
        eur=_subtract_currency_amounts(left.eur, right.eur),
        dkk=_subtract_currency_amounts(left.dkk, right.dkk),
    )


def _validate_window(since: date, until: date) -> None:
    if since > until:
        raise HouseholdReportingError("since must be on or before until")
