"""Conversion and response-building helpers for household report reads."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from penge.analytics.household import (
    AllocationTreatment,
    BankAllocation,
    BankTransaction,
    Category,
    CategoryRollup,
    CurrencyAmount,
    CurrencyPair,
    HouseholdReport,
    HouseholdReportingError,
    PaymentDetail,
    PaymentDetailAllocation,
    PaymentEventKind,
    ReconciliationStatus,
    ReportTotals,
    aggregate_bank_transactions,
    bucket_start,
    category_rollups,
    previous_window,
    reconciliation_status,
    subtract_report_totals,
)
from penge.api.household_models import (
    HouseholdCategoryNode,
    HouseholdCategoryReportResponse,
    HouseholdCurrencyAmount,
    HouseholdCurrencyPair,
    HouseholdGranularity,
    HouseholdPaymentDetailLink,
    HouseholdReportAllocation,
    HouseholdReportChange,
    HouseholdReportCoverage,
    HouseholdReportFilters,
    HouseholdReportFreshness,
    HouseholdReportSummaryResponse,
    HouseholdReportTotals,
    HouseholdReportTransaction,
    HouseholdReportTransactionsResponse,
    HouseholdReportWindow,
    HouseholdTreatment,
    HouseholdTrendPoint,
)

MONTHS_PER_YEAR = 12


@dataclass
class _BankTransactionParts:
    transaction_id: str
    value_date: date
    account_id: str
    entity_id: str
    amount_native: Decimal
    currency: str
    description: str | None
    counterparty: str | None
    created_at: datetime | None
    classification_source_current: bool
    source_snapshot_drift: bool
    classification_review_state: str | None
    allocation_mismatch: bool
    allocations: list[BankAllocation] = field(default_factory=list)
    payment_details: list[PaymentDetailAllocation] = field(default_factory=list)


def categories_from_rows(rows: Iterable[dict[str, object]]) -> tuple[Category, ...]:
    """Validate database category rows and preserve lifecycle metadata."""
    categories: list[Category] = []
    for row in rows:
        category_id = _required_text(row, "category_id")
        parent_id = _optional_text(row, "parent_id")
        kind = _required_text(row, "kind")
        if kind not in ("income", "expense"):
            raise HouseholdReportingError(f"invalid household category kind: {kind}")
        categories.append(
            Category(
                category_id=category_id,
                parent_id=parent_id,
                kind=kind,
                name=_required_text(row, "name"),
                sort_order=_required_int(row, "sort_order"),
                archived=_required_bool(row, "archived"),
                revision=_required_int(row, "revision"),
            )
        )
    return tuple(categories)


def transactions_from_rows(
    rows: Iterable[dict[str, object]],
    detail_rows: Iterable[dict[str, object]] = (),
) -> tuple[BankTransaction, ...]:
    """Group allocation rows into bank-ledger transactions and sidecars."""
    grouped: dict[str, _BankTransactionParts] = {}
    for row in rows:
        transaction_id = _required_text(row, "transaction_id")
        transaction = grouped.get(transaction_id)
        if transaction is None:
            transaction = _BankTransactionParts(
                transaction_id=transaction_id,
                value_date=_required_date(row, "as_of"),
                account_id=_required_text(row, "account_id"),
                entity_id=_required_text(row, "entity_id"),
                amount_native=_required_decimal(row, "source_amount_native"),
                currency=_required_text(row, "account_currency"),
                description=_optional_text(row, "description"),
                counterparty=_optional_text(row, "counterparty"),
                created_at=_optional_datetime(row, "transaction_created_at"),
                classification_source_current=_required_bool(row, "classification_source_current"),
                source_snapshot_drift=_required_bool(row, "source_snapshot_drift"),
                classification_review_state=_optional_text(row, "classification_review_state"),
                allocation_mismatch=_required_bool(row, "allocation_mismatch"),
            )
            grouped[transaction_id] = transaction
        elif (
            transaction.amount_native != _required_decimal(row, "source_amount_native")
            or transaction.account_id != _required_text(row, "account_id")
            or transaction.entity_id != _required_text(row, "entity_id")
            or transaction.value_date != _required_date(row, "as_of")
            or transaction.currency != _required_text(row, "account_currency")
            or transaction.description != _optional_text(row, "description")
            or transaction.counterparty != _optional_text(row, "counterparty")
            or transaction.created_at != _optional_datetime(row, "transaction_created_at")
            or transaction.classification_source_current
            != _required_bool(row, "classification_source_current")
            or transaction.source_snapshot_drift != _required_bool(row, "source_snapshot_drift")
            or transaction.classification_review_state
            != _optional_text(row, "classification_review_state")
            or transaction.allocation_mismatch != _required_bool(row, "allocation_mismatch")
        ):
            raise HouseholdReportingError(
                f"inconsistent household fact rows for transaction {transaction_id}"
            )

        transaction.allocations.append(
            BankAllocation(
                category_id=_optional_text(row, "category_id"),
                treatment=AllocationTreatment(_required_text(row, "treatment")),
                amount_native=_required_decimal(row, "allocation_amount_native"),
                amount_eur=_optional_decimal(row, "allocation_amount_eur"),
                amount_dkk=_optional_decimal(row, "allocation_amount_dkk"),
            )
        )

    for row in detail_rows:
        transaction_id = _required_text(row, "transaction_id")
        transaction = grouped.get(transaction_id)
        if transaction is None:
            raise HouseholdReportingError(
                f"payment detail link has no selected bank transaction: {transaction_id}"
            )
        transaction.payment_details.append(
            PaymentDetailAllocation(
                detail=PaymentDetail(
                    detail_id=_required_text(row, "detail_id"),
                    external_reference=_optional_text(row, "external_reference"),
                    revision=_required_int(row, "current_detail_revision"),
                    amount=_required_decimal(row, "source_amount"),
                    currency=_required_text(row, "source_currency"),
                    event_kind=PaymentEventKind(_required_text(row, "event_kind")),
                    merchant_name=_optional_text(row, "merchant_name"),
                    reference=_optional_text(row, "reference"),
                    source_date=_optional_date(row, "source_date"),
                    merchant_category_code=_optional_text(row, "merchant_category_code"),
                    bank_code=_optional_text(row, "bank_code"),
                    bank_sub_code=_optional_text(row, "bank_sub_code"),
                ),
                bank_amount=_required_decimal(row, "bank_amount"),
                detail_revision=_required_int(row, "approved_detail_revision"),
                approved=True,
            )
        )

    return tuple(
        BankTransaction(
            transaction_id=transaction.transaction_id,
            value_date=transaction.value_date,
            account_id=transaction.account_id,
            entity_id=transaction.entity_id,
            amount_native=transaction.amount_native,
            currency=transaction.currency,
            allocations=tuple(transaction.allocations),
            payment_details=tuple(transaction.payment_details),
            description=transaction.description,
            counterparty=transaction.counterparty,
            created_at=transaction.created_at,
            classification_source_current=transaction.classification_source_current,
            source_snapshot_drift=transaction.source_snapshot_drift,
            classification_review_state=transaction.classification_review_state,
            allocation_mismatch=transaction.allocation_mismatch,
        )
        for transaction in grouped.values()
    )


def build_summary_response(
    *,
    transactions: Sequence[BankTransaction],
    categories: Sequence[Category],
    filters: HouseholdReportFilters,
    coverage: HouseholdReportCoverage,
    freshness: HouseholdReportFreshness,
) -> HouseholdReportSummaryResponse:
    """Build current/prior totals and a zero-filled daily/monthly/yearly trend."""
    previous_since, previous_until = previous_window(filters.since, filters.until)
    account_ids = frozenset(filters.account_ids)
    entity_ids = frozenset(filters.entity_ids) or None
    current = aggregate_bank_transactions(
        transactions,
        categories,
        since=filters.since,
        until=filters.until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=filters.category_id,
    )
    previous = aggregate_bank_transactions(
        transactions,
        categories,
        since=previous_since,
        until=previous_until,
        account_ids=account_ids,
        entity_ids=entity_ids,
        category_id=filters.category_id,
    )
    transactions_by_period: dict[date, list[BankTransaction]] = defaultdict(list)
    for transaction in transactions:
        if (
            filters.since <= transaction.value_date <= filters.until
            and transaction.account_id in account_ids
            and (entity_ids is None or transaction.entity_id in entity_ids)
        ):
            period = bucket_start(transaction.value_date, filters.granularity.value)
            transactions_by_period[period].append(transaction)
    points = [
        HouseholdTrendPoint(
            period_start=period_start,
            period_end=period_end,
            totals=_totals_to_model(
                aggregate_bank_transactions(
                    transactions_by_period.get(
                        bucket_start(period_start, filters.granularity.value),
                        [],
                    ),
                    categories,
                    since=period_start,
                    until=period_end,
                    account_ids=account_ids,
                    entity_ids=entity_ids,
                    category_id=filters.category_id,
                ).totals
            ),
        )
        for period_start, period_end in _periods(
            filters.since,
            filters.until,
            filters.granularity,
        )
    ]
    change = subtract_report_totals(current.totals, previous.totals)
    change_model = _totals_to_model(change)
    return HouseholdReportSummaryResponse(
        filters=filters,
        current=HouseholdReportWindow(
            since=filters.since,
            until=filters.until,
            totals=_totals_to_model(current.totals),
        ),
        previous=HouseholdReportWindow(
            since=previous_since,
            until=previous_until,
            totals=_totals_to_model(previous.totals),
        ),
        change=HouseholdReportChange(
            income=change_model.income,
            gross_expenses=change_model.gross_expenses,
            refunds=change_model.refunds,
            net_expenses=change_model.net_expenses,
            surplus=change_model.surplus,
        ),
        points=points,
        coverage=coverage,
        freshness=freshness,
    )


def build_category_response(
    *,
    transactions: Sequence[BankTransaction],
    categories: Sequence[Category],
    filters: HouseholdReportFilters,
    coverage: HouseholdReportCoverage,
    freshness: HouseholdReportFreshness,
) -> HouseholdCategoryReportResponse:
    """Build parent-category rollups without adding ancestors to household totals."""
    rollups = category_rollups(
        transactions,
        categories,
        since=filters.since,
        until=filters.until,
        account_ids=frozenset(filters.account_ids),
        entity_ids=frozenset(filters.entity_ids) or None,
    )
    nodes = _category_tree(categories, rollups)
    if filters.category_id is not None:
        nodes = [_find_category_node(nodes, filters.category_id)]
    return HouseholdCategoryReportResponse(
        filters=filters,
        categories=nodes,
        coverage=coverage,
        freshness=freshness,
    )


def build_transactions_response(
    *,
    transactions: Sequence[BankTransaction],
    categories: Sequence[Category],
    filters: HouseholdReportFilters,
    search: str | None,
    limit: int,
    offset: int,
    total: int,
) -> HouseholdReportTransactionsResponse:
    """Build transaction-grain rows with exact matching split subtotals."""
    aggregate_bank_transactions(
        transactions,
        categories,
        since=filters.since,
        until=filters.until,
    )
    category_by_id = {category.category_id: category for category in categories}
    selected_categories = (
        _descendants(categories, filters.category_id) if filters.category_id is not None else None
    )
    response_items: list[HouseholdReportTransaction] = []
    for transaction in transactions:
        reportable = [
            allocation for allocation in transaction.allocations if _is_reportable(allocation)
        ]
        matching = [
            allocation
            for allocation in reportable
            if selected_categories is None or allocation.category_id in selected_categories
        ]
        if selected_categories is not None and not matching:
            continue
        bank_amount_pair = _currency_pair(transaction.allocations)
        matching_pair = _currency_pair(matching)
        matching_native = sum(
            (allocation.amount_native for allocation in matching),
            Decimal(0),
        )
        allocation_models = [
            _allocation_to_model(allocation, transaction.currency, category_by_id)
            for allocation in transaction.allocations
        ]
        details = _payment_detail_models(transaction)
        detail_status = (
            reconciliation_status(transaction.amount_native, transaction.payment_details)
            if transaction.payment_details
            else None
        )
        matched_merchants = {
            allocation.detail.merchant_name
            for allocation in transaction.payment_details
            if detail_status is ReconciliationStatus.RECONCILED
            and allocation.detail.merchant_name is not None
        }
        merchant_name = next(iter(matched_merchants)) if len(matched_merchants) == 1 else None
        treatment_allocations = (
            matching if selected_categories is not None else transaction.allocations
        )
        treatments = {allocation.treatment for allocation in treatment_allocations}
        if len(treatments) != 1:
            raise HouseholdReportingError(
                f"bank transaction {transaction.transaction_id} has mixed treatments"
            )
        response_items.append(
            HouseholdReportTransaction(
                transaction_id=transaction.transaction_id,
                value_date=transaction.value_date,
                account_id=transaction.account_id,
                entity_id=transaction.entity_id,
                description=transaction.description,
                counterparty=transaction.counterparty,
                merchant_name=merchant_name,
                treatment=HouseholdTreatment(next(iter(treatments)).value),
                signed_amount_native=transaction.amount_native,
                currency=transaction.currency,
                amount_reporting=_pair_to_model(bank_amount_pair),
                matching_split_amount_native=matching_native,
                matching_split_amount_reporting=_pair_to_model(matching_pair),
                allocations=allocation_models,
                payment_details=details,
                payment_reconciliation_status=detail_status,
            )
        )
    return HouseholdReportTransactionsResponse(
        filters=filters,
        search=search,
        items=response_items,
        limit=limit,
        offset=offset,
        total=total,
    )


def report_coverage(
    *,
    report: HouseholdReport,
    transactions: Sequence[BankTransaction],
    history_start: date | None,
    unmatched_detail_count: int,
) -> HouseholdReportCoverage:
    """Add classification, transfer, FX, and reconciliation counts to a report."""
    transfer_ids: set[str] = set()
    excluded_ids: set[str] = set()
    review_ids: set[str] = set()
    drift_ids: set[str] = set()
    mismatch_ids: set[str] = set()
    link_counts: dict[str, int] = defaultdict(int)
    link_status_by_id: dict[str, ReconciliationStatus] = {}

    for transaction in transactions:
        treatments = {allocation.treatment for allocation in transaction.allocations}
        if treatments == {AllocationTreatment.TRANSFER}:
            transfer_ids.add(transaction.transaction_id)
        if treatments == {AllocationTreatment.EXCLUDED}:
            excluded_ids.add(transaction.transaction_id)
        if transaction.classification_review_state == "needs_review":
            review_ids.add(transaction.transaction_id)
        if transaction.source_snapshot_drift:
            drift_ids.add(transaction.transaction_id)
        if transaction.allocation_mismatch:
            mismatch_ids.add(transaction.transaction_id)
        if transaction.payment_details:
            status = reconciliation_status(transaction.amount_native, transaction.payment_details)
            link_counts[transaction.transaction_id] = len(transaction.payment_details)
            link_status_by_id[transaction.transaction_id] = status

    payment_status_counts = {
        status: sum(value is status for value in link_status_by_id.values())
        for status in (
            ReconciliationStatus.RECONCILED,
            ReconciliationStatus.REVIEW,
            ReconciliationStatus.STALE,
        )
    }
    return HouseholdReportCoverage(
        history_start=history_start,
        history_completeness="unknown",
        bank_transaction_count=len({item.transaction_id for item in transactions}),
        included_transaction_count=report.included_transaction_count,
        unclassified_transaction_count=report.unclassified_transaction_count,
        unclassified_expense_count=report.unclassified_expense_count,
        unclassified_expense_amount=_pair_to_model(report.unclassified_expense_amount),
        transfer_excluded_count=len(transfer_ids),
        excluded_transaction_count=len(excluded_ids),
        classification_review_count=len(review_ids),
        source_snapshot_drift_count=len(drift_ids),
        allocation_mismatch_count=len(mismatch_ids),
        missing_fx_allocation_count=report.missing_fx_allocation_count,
        payment_detail_link_count=sum(link_counts.values()),
        payment_detail_reconciled_count=payment_status_counts[ReconciliationStatus.RECONCILED],
        payment_detail_review_count=payment_status_counts[ReconciliationStatus.REVIEW],
        payment_detail_stale_count=payment_status_counts[ReconciliationStatus.STALE],
        payment_detail_unmatched_count=unmatched_detail_count,
    )


def build_report_coverage(
    *,
    transactions: Sequence[BankTransaction],
    categories: Sequence[Category],
    since: date,
    until: date,
    account_ids: Sequence[str],
    entity_ids: Sequence[str],
    category_id: str | None,
    history_start: date | None,
    unmatched_detail_count: int,
) -> HouseholdReportCoverage:
    """Build coverage counts using the same bank, member, date, and category scope."""
    scoped = tuple(
        transaction
        for transaction in transactions
        if since <= transaction.value_date <= until
        and transaction.account_id in account_ids
        and (not entity_ids or transaction.entity_id in entity_ids)
    )
    coverage_transactions = scoped
    if category_id is not None:
        selected_categories = _descendants(categories, category_id)
        coverage_transactions = tuple(
            transaction
            for transaction in scoped
            if any(
                allocation.category_id in selected_categories
                for allocation in transaction.allocations
            )
        )
    report = aggregate_bank_transactions(
        scoped,
        categories,
        since=since,
        until=until,
        account_ids=frozenset(account_ids),
        entity_ids=frozenset(entity_ids) or None,
        category_id=category_id,
    )
    return report_coverage(
        report=report,
        transactions=coverage_transactions,
        history_start=history_start,
        unmatched_detail_count=unmatched_detail_count,
    )


def _category_tree(
    categories: Sequence[Category],
    rollups: dict[str, CategoryRollup],
) -> list[HouseholdCategoryNode]:
    category_by_id = {category.category_id: category for category in categories}
    children: dict[str | None, list[str]] = defaultdict(list)
    for category in categories:
        if category.parent_id is not None and category.parent_id not in category_by_id:
            raise HouseholdReportingError(f"unknown category parent: {category.parent_id}")
        children[category.parent_id].append(category.category_id)
    for category_ids in children.values():
        category_ids.sort(
            key=lambda category_id: (
                category_by_id[category_id].sort_order,
                category_by_id[category_id].name.casefold(),
                category_id,
            )
        )

    def build(category_id: str) -> HouseholdCategoryNode:
        category = category_by_id[category_id]
        rollup = rollups[category_id]
        category_kind: Literal["expense", "income"]
        if category.kind == "expense":
            category_kind = "expense"
        elif category.kind == "income":
            category_kind = "income"
        else:
            raise HouseholdReportingError(f"invalid category kind: {category.kind}")
        return HouseholdCategoryNode(
            category_id=category.category_id,
            parent_id=category.parent_id,
            name=category.name,
            kind=category_kind,
            sort_order=category.sort_order,
            archived=category.archived,
            revision=category.revision,
            transaction_count=rollup.transaction_count,
            totals=_totals_to_model(rollup.totals),
            children=[build(child_id) for child_id in children.get(category_id, [])],
        )

    return [build(category_id) for category_id in children.get(None, [])]


def _find_category_node(
    nodes: Sequence[HouseholdCategoryNode],
    category_id: str,
) -> HouseholdCategoryNode:
    for node in nodes:
        if node.category_id == category_id:
            return node
        try:
            return _find_category_node(node.children, category_id)
        except KeyError:
            continue
    raise KeyError(category_id)


def _descendants(categories: Sequence[Category], category_id: str) -> frozenset[str]:
    category_ids = {category.category_id for category in categories}
    if category_id not in category_ids:
        raise HouseholdReportingError(f"unknown category id: {category_id}")
    descendants = {category_id}
    while True:
        children = {
            category.category_id for category in categories if category.parent_id in descendants
        }
        new_descendants = children - descendants
        if not new_descendants:
            return frozenset(descendants)
        descendants.update(new_descendants)


def category_descendant_ids(
    categories: Sequence[Category],
    category_id: str,
) -> frozenset[str]:
    """Return a validated category node and all descendants."""
    return _descendants(categories, category_id)


def _periods(
    since: date,
    until: date,
    granularity: HouseholdGranularity,
) -> list[tuple[date, date]]:
    periods: list[tuple[date, date]] = []
    current = bucket_start(since, granularity.value)
    while current <= until:
        if granularity is HouseholdGranularity.DAY:
            next_period = current + timedelta(days=1)
        elif granularity is HouseholdGranularity.MONTH:
            next_period = (
                current.replace(year=current.year + 1, month=1)
                if current.month == MONTHS_PER_YEAR
                else current.replace(month=current.month + 1)
            )
        else:
            next_period = current.replace(year=current.year + 1)
        periods.append((max(current, since), min(next_period - timedelta(days=1), until)))
        current = next_period
    return periods


def _is_reportable(allocation: BankAllocation) -> bool:
    return allocation.treatment in (
        AllocationTreatment.INCOME,
        AllocationTreatment.EXPENSE,
        AllocationTreatment.REFUND,
    ) or (allocation.treatment is AllocationTreatment.UNCLASSIFIED and allocation.amount_native < 0)


def _allocation_to_model(
    allocation: BankAllocation,
    currency: str,
    category_by_id: dict[str, Category],
) -> HouseholdReportAllocation:
    category = category_by_id.get(allocation.category_id or "")
    return HouseholdReportAllocation(
        category_id=allocation.category_id,
        category_name=category.name if category is not None else None,
        category_path=_category_path(category, category_by_id),
        treatment=HouseholdTreatment(allocation.treatment.value),
        amount_native=allocation.amount_native,
        currency=currency,
        amount_reporting=_pair_to_model(_currency_pair((allocation,))),
    )


def _category_path(
    category: Category | None,
    category_by_id: dict[str, Category],
) -> list[str]:
    if category is None:
        return []
    names: list[str] = []
    visited: set[str] = set()
    current: Category | None = category
    while current is not None:
        if current.category_id in visited:
            raise HouseholdReportingError(f"category cycle contains {current.category_id}")
        visited.add(current.category_id)
        names.append(current.name)
        current = category_by_id.get(current.parent_id or "")
    return list(reversed(names))


def _payment_detail_models(
    transaction: BankTransaction,
) -> list[HouseholdPaymentDetailLink]:
    status = reconciliation_status(transaction.amount_native, transaction.payment_details)
    return [
        HouseholdPaymentDetailLink(
            detail_id=allocation.detail.detail_id,
            external_reference=allocation.detail.external_reference,
            reference=allocation.detail.reference,
            merchant_name=allocation.detail.merchant_name,
            event_kind=allocation.detail.event_kind,
            source_amount=allocation.detail.amount,
            source_currency=allocation.detail.currency,
            source_date=allocation.detail.source_date,
            merchant_category_code=allocation.detail.merchant_category_code,
            bank_code=allocation.detail.bank_code,
            bank_sub_code=allocation.detail.bank_sub_code,
            bank_amount=allocation.bank_amount,
            bank_currency=transaction.currency,
            approved_detail_revision=allocation.detail_revision,
            current_detail_revision=allocation.detail.revision,
            reconciliation_status=status,
        )
        for allocation in transaction.payment_details
    ]


def _currency_pair(allocations: Iterable[BankAllocation]) -> CurrencyPair:
    allocation_list = tuple(allocations)
    eur_known = sum(
        (item.amount_eur for item in allocation_list if item.amount_eur is not None),
        Decimal(0),
    )
    dkk_known = sum(
        (item.amount_dkk for item in allocation_list if item.amount_dkk is not None),
        Decimal(0),
    )
    eur_missing = sum(item.amount_eur is None for item in allocation_list)
    dkk_missing = sum(item.amount_dkk is None for item in allocation_list)
    return CurrencyPair(
        eur=CurrencyAmount(
            amount=eur_known if eur_missing == 0 else None,
            known_subtotal=eur_known,
            complete=eur_missing == 0,
            missing_count=eur_missing,
        ),
        dkk=CurrencyAmount(
            amount=dkk_known if dkk_missing == 0 else None,
            known_subtotal=dkk_known,
            complete=dkk_missing == 0,
            missing_count=dkk_missing,
        ),
    )


def _pair_to_model(pair: CurrencyPair) -> HouseholdCurrencyPair:
    return HouseholdCurrencyPair(
        eur=_currency_amount_to_model(pair.eur),
        dkk=_currency_amount_to_model(pair.dkk),
    )


def _currency_amount_to_model(amount: CurrencyAmount) -> HouseholdCurrencyAmount:
    return HouseholdCurrencyAmount(
        amount=amount.amount,
        known_subtotal=amount.known_subtotal,
        complete=amount.complete,
        missing_count=amount.missing_count,
    )


def _totals_to_model(totals: ReportTotals) -> HouseholdReportTotals:
    return HouseholdReportTotals(
        income=_pair_to_model(totals.income),
        gross_expenses=_pair_to_model(totals.gross_expenses),
        refunds=_pair_to_model(totals.refunds),
        net_expenses=_pair_to_model(totals.net_expenses),
        surplus=_pair_to_model(totals.surplus),
    )


def _required_text(row: dict[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise HouseholdReportingError(f"household report field {field} is not text")
    return value


def _optional_text(row: dict[str, object], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HouseholdReportingError(f"household report field {field} is not text")
    return value


def _required_decimal(row: dict[str, object], field: str) -> Decimal:
    value = row.get(field)
    if not isinstance(value, Decimal):
        raise HouseholdReportingError(f"household report field {field} is not Decimal")
    return value


def _optional_decimal(row: dict[str, object], field: str) -> Decimal | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise HouseholdReportingError(f"household report field {field} is not Decimal")
    return value


def _required_date(row: dict[str, object], field: str) -> date:
    value = row.get(field)
    if not isinstance(value, date) or isinstance(value, datetime):
        raise HouseholdReportingError(f"household report field {field} is not a date")
    return value


def _optional_date(row: dict[str, object], field: str) -> date | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise HouseholdReportingError(f"household report field {field} is not a date")
    return value


def _optional_datetime(row: dict[str, object], field: str) -> datetime | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise HouseholdReportingError(f"household report field {field} is not a timestamp")
    return value


def _required_int(row: dict[str, object], field: str) -> int:
    value = row.get(field)
    if not isinstance(value, int):
        raise HouseholdReportingError(f"household report field {field} is not an integer")
    return value


def _required_bool(row: dict[str, object], field: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise HouseholdReportingError(f"household report field {field} is not boolean")
    return value
