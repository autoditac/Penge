"""Synthetic goldens for household cashflow and reconciliation semantics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from penge.analytics.household import (
    AllocationTreatment,
    BankAllocation,
    BankTransaction,
    Category,
    HouseholdReportingError,
    PaymentDetail,
    PaymentDetailAllocation,
    PaymentEventKind,
    ReconciliationStatus,
    aggregate_bank_transactions,
    bucket_start,
    category_rollups,
    previous_window,
    reconciliation_status,
)

_CATEGORIES = (
    Category("expenses", None, "expense"),
    Category("food", "expenses", "expense"),
    Category("groceries", "food", "expense"),
    Category("dining", "food", "expense"),
    Category("income", None, "income"),
    Category("salary", "income", "income"),
)


def _allocation(
    category_id: str | None,
    treatment: AllocationTreatment,
    native: str,
    eur: str | None,
    dkk: str | None,
) -> BankAllocation:
    return BankAllocation(
        category_id=category_id,
        treatment=treatment,
        amount_native=Decimal(native),
        amount_eur=Decimal(eur) if eur is not None else None,
        amount_dkk=Decimal(dkk) if dkk is not None else None,
    )


def _bank_transaction(
    transaction_id: str,
    when: date,
    amount: str,
    allocations: tuple[BankAllocation, ...],
    *,
    payment_details: tuple[PaymentDetailAllocation, ...] = (),
    account_id: str = "checking-1",
    entity_id: str = "member-1",
) -> BankTransaction:
    return BankTransaction(
        transaction_id=transaction_id,
        value_date=when,
        account_id=account_id,
        entity_id=entity_id,
        amount_native=Decimal(amount),
        currency="EUR",
        allocations=allocations,
        payment_details=payment_details,
    )


def _golden_transactions() -> tuple[BankTransaction, ...]:
    """Hand-calculated EUR/DKK examples; all data is synthetic."""
    return (
        _bank_transaction(
            "bank-purchase",
            date(2026, 6, 10),
            "-120.0000",
            (
                _allocation("groceries", AllocationTreatment.EXPENSE, "-80", "-80", "-596.8"),
                _allocation("dining", AllocationTreatment.EXPENSE, "-40", "-40", "-298.4"),
            ),
        ),
        _bank_transaction(
            "bank-refund",
            date(2026, 6, 18),
            "10.0000",
            (_allocation("groceries", AllocationTreatment.REFUND, "10", "10", "74.6"),),
        ),
        _bank_transaction(
            "bank-salary",
            date(2026, 6, 25),
            "1000.0000",
            (_allocation("salary", AllocationTreatment.INCOME, "1000", "1000", "7460"),),
        ),
        _bank_transaction(
            "bank-transfer",
            date(2026, 6, 26),
            "2000.0000",
            (_allocation(None, AllocationTreatment.TRANSFER, "2000", "2000", "14920"),),
        ),
        _bank_transaction(
            "bank-unclassified-credit",
            date(2026, 6, 26),
            "500.0000",
            (_allocation(None, AllocationTreatment.UNCLASSIFIED, "500", "500", "3730"),),
        ),
        _bank_transaction(
            "bank-unclassified",
            date(2026, 6, 27),
            "-5.0000",
            (_allocation(None, AllocationTreatment.UNCLASSIFIED, "-5", "-5", "-37.3"),),
        ),
    )


def test_golden_report_counts_bank_facts_once_and_refunds_on_refund_date() -> None:
    report = aggregate_bank_transactions(
        _golden_transactions(),
        _CATEGORIES,
        since=date(2026, 6, 1),
        until=date(2026, 6, 30),
    )

    assert report.included_transaction_count == 5
    assert report.unclassified_transaction_count == 2
    assert report.unclassified_expense_count == 1
    assert report.transfer_excluded_count == 1
    assert report.missing_fx_allocation_count == 0
    assert report.totals.income.eur.amount == Decimal("1500")
    assert report.totals.gross_expenses.eur.amount == Decimal("125")
    assert report.totals.refunds.eur.amount == Decimal("10")
    assert report.totals.net_expenses.eur.amount == Decimal("115")
    assert report.totals.surplus.eur.amount == Decimal("1385")
    assert report.totals.gross_expenses.dkk.amount == Decimal("932.5")
    assert report.totals.refunds.dkk.amount == Decimal("74.6")
    assert report.totals.net_expenses.dkk.amount == Decimal("857.9")
    assert report.totals.surplus.dkk.amount == Decimal("10332.1")
    assert report.unclassified_expense_amount.eur.amount == Decimal("5")
    assert report.unclassified_expense_amount.dkk.amount == Decimal("37.3")


def test_detail_sidecar_and_reimport_never_change_bank_expense_totals() -> None:
    bank_only = _golden_transactions()[0]
    detail = PaymentDetail(
        detail_id="paypal-detail-1",
        external_reference="stable-entry-reference",
        revision=2,
        amount=Decimal("-120"),
        currency="EUR",
        event_kind=PaymentEventKind.UNKNOWN,
        merchant_name="Synthetic Merchant",
    )
    approved = PaymentDetailAllocation(
        detail=detail,
        bank_amount=Decimal("-120"),
        detail_revision=2,
        approved=True,
    )
    reimported = PaymentDetail(
        detail_id="paypal-detail-1",
        external_reference="stable-entry-reference",
        revision=2,
        amount=Decimal("-120"),
        currency="EUR",
        event_kind=PaymentEventKind.UNKNOWN,
        merchant_name="Synthetic Merchant",
    )

    totals = [
        aggregate_bank_transactions(
            (transaction,),
            _CATEGORIES,
            since=date(2026, 6, 1),
            until=date(2026, 6, 30),
        )
        for transaction in (
            bank_only,
            _bank_transaction(
                "bank-purchase",
                bank_only.value_date,
                "-120",
                bank_only.allocations,
                payment_details=(approved,),
            ),
            _bank_transaction(
                "bank-purchase",
                bank_only.value_date,
                "-120",
                bank_only.allocations,
                payment_details=(
                    PaymentDetailAllocation(
                        detail=reimported,
                        bank_amount=Decimal("-120"),
                        detail_revision=2,
                        approved=True,
                    ),
                ),
            ),
        )
    ]

    assert [item.included_transaction_count for item in totals] == [1, 1, 1]
    assert [item.totals.gross_expenses.eur.amount for item in totals] == [
        Decimal("120"),
        Decimal("120"),
        Decimal("120"),
    ]


def test_category_filter_uses_matching_splits_but_counts_bank_transaction_once() -> None:
    report = aggregate_bank_transactions(
        _golden_transactions(),
        _CATEGORIES,
        since=date(2026, 6, 1),
        until=date(2026, 6, 30),
        category_id="food",
    )

    assert report.included_transaction_count == 2
    assert report.totals.gross_expenses.eur.amount == Decimal("120")
    assert report.totals.refunds.eur.amount == Decimal("10")
    assert report.totals.net_expenses.eur.amount == Decimal("110")
    assert report.unclassified_expense_count == 0
    assert report.transfer_excluded_count == 0


def test_parent_category_rollup_counts_split_transaction_once() -> None:
    rollups = category_rollups(
        _golden_transactions(),
        _CATEGORIES,
        since=date(2026, 6, 1),
        until=date(2026, 6, 30),
    )

    food = rollups["food"]
    groceries = rollups["groceries"]
    dining = rollups["dining"]
    assert food.transaction_count == 2
    assert food.totals.gross_expenses.eur.amount == Decimal("120")
    assert food.totals.refunds.eur.amount == Decimal("10")
    assert groceries.transaction_count == 2
    assert groceries.totals.net_expenses.eur.amount == Decimal("70")
    assert dining.transaction_count == 1
    assert dining.totals.net_expenses.eur.amount == Decimal("40")


def test_missing_fx_is_not_reported_as_zero_or_as_a_complete_total() -> None:
    transaction = _bank_transaction(
        "bank-missing-fx",
        date(2026, 6, 10),
        "-10",
        (_allocation("groceries", AllocationTreatment.EXPENSE, "-10", "-10", None),),
    )

    report = aggregate_bank_transactions(
        (transaction,),
        _CATEGORIES,
        since=date(2026, 6, 1),
        until=date(2026, 6, 30),
    )

    dkk = report.totals.gross_expenses.dkk
    assert dkk.amount is None
    assert dkk.known_subtotal == Decimal(0)
    assert not dkk.complete
    assert dkk.missing_count == 1
    assert report.missing_fx_allocation_count == 1


def test_mismatched_allocation_totals_are_rejected_exactly() -> None:
    transaction = _bank_transaction(
        "bank-invalid-split",
        date(2026, 6, 10),
        "-10",
        (_allocation("groceries", AllocationTreatment.EXPENSE, "-9.9999", "-9.9999", "-74.5993"),),
    )

    with pytest.raises(HouseholdReportingError, match="allocations total"):
        aggregate_bank_transactions(
            (transaction,),
            _CATEGORIES,
            since=date(2026, 6, 1),
            until=date(2026, 6, 30),
        )


def test_duplicate_bank_rows_are_rejected_instead_of_double_counted() -> None:
    transaction = _golden_transactions()[0]

    with pytest.raises(HouseholdReportingError, match="duplicate bank transaction"):
        aggregate_bank_transactions(
            (transaction, transaction),
            _CATEGORIES,
            since=date(2026, 6, 1),
            until=date(2026, 6, 30),
        )


def test_category_cycles_are_rejected() -> None:
    categories = (Category("a", "b"), Category("b", "a"))

    with pytest.raises(HouseholdReportingError, match="category cycle"):
        aggregate_bank_transactions(
            (),
            categories,
            since=date(2026, 6, 1),
            until=date(2026, 6, 30),
        )


def test_reconciliation_requires_explicit_approval_exact_amount_and_current_revision() -> None:
    detail_a = PaymentDetail("detail-a", "ref-a", 3, Decimal("-40"), "EUR")
    detail_b = PaymentDetail("detail-b", "ref-b", 1, Decimal("-60"), "EUR")
    allocations = (
        PaymentDetailAllocation(detail_a, Decimal("-40"), 3, approved=True),
        PaymentDetailAllocation(detail_b, Decimal("-60"), 1, approved=True),
    )

    assert reconciliation_status(Decimal("-100"), allocations) is ReconciliationStatus.RECONCILED
    assert reconciliation_status(Decimal("-100"), ()) is ReconciliationStatus.UNMATCHED
    assert (
        reconciliation_status(
            Decimal("-100"),
            (PaymentDetailAllocation(detail_a, Decimal("-40"), 3, approved=False),),
        )
        is ReconciliationStatus.REVIEW
    )
    assert (
        reconciliation_status(
            Decimal("-100"),
            (PaymentDetailAllocation(detail_a, Decimal("-40"), 2, approved=True),),
        )
        is ReconciliationStatus.STALE
    )
    assert (
        reconciliation_status(
            Decimal("-100"),
            (PaymentDetailAllocation(detail_a, Decimal("-39"), 3, approved=True),),
        )
        is ReconciliationStatus.REVIEW
    )


def test_report_bucket_and_previous_window_boundaries_are_explicit() -> None:
    assert bucket_start(date(2026, 6, 14), "day") == date(2026, 6, 14)
    assert bucket_start(date(2026, 6, 14), "month") == date(2026, 6, 1)
    assert bucket_start(date(2026, 6, 14), "year") == date(2026, 1, 1)
    assert previous_window(date(2026, 6, 10), date(2026, 6, 19)) == (
        date(2026, 5, 31),
        date(2026, 6, 9),
    )
