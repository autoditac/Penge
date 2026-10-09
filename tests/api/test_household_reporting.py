"""Read API tests for the bank-ledger household reporting projection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from penge.api import data
from penge.api.household_models import HouseholdCurrencyAmount

if TYPE_CHECKING:
    import pytest
    from fastapi.testclient import TestClient


def _fact(
    *,
    transaction_id: str,
    booking_date: date,
    amount: str,
    treatment: str,
    category_id: str | None,
    category_name: str | None,
    category_kind: str | None,
    eur: str,
    dkk: str,
) -> dict[str, object]:
    native = Decimal(amount)
    return {
        "transaction_id": transaction_id,
        "account_id": "a1",
        "entity_id": "e1",
        "account_currency": "EUR",
        "as_of": booking_date,
        "transaction_created_at": datetime(
            booking_date.year, booking_date.month, booking_date.day, tzinfo=UTC
        ),
        "source_amount_native": native,
        "allocation_amount_native": native,
        "treatment": treatment,
        "category_id": category_id,
        "category_name": category_name,
        "category_kind": category_kind,
        "category_parent_id": None,
        "counterparty": "Synthetic counterparty",
        "description": "Synthetic bank booking",
        "classification_source_current": True,
        "source_snapshot_drift": False,
        "classification_review_state": "classified",
        "allocation_mismatch": False,
        "allocation_amount_eur": Decimal(eur),
        "allocation_amount_dkk": Decimal(dkk),
        "is_default_scope": True,
    }


def _facts() -> list[dict[str, object]]:
    return [
        _fact(
            transaction_id="t0",
            booking_date=date(2025, 6, 12),
            amount="-20.00",
            treatment="expense",
            category_id="food",
            category_name="Food",
            category_kind="expense",
            eur="-20.00",
            dkk="-149.20",
        ),
        _fact(
            transaction_id="t1",
            booking_date=date(2025, 7, 5),
            amount="-12.50",
            treatment="expense",
            category_id="food",
            category_name="Food",
            category_kind="expense",
            eur="-12.50",
            dkk="-93.25",
        ),
        _fact(
            transaction_id="t2",
            booking_date=date(2025, 7, 10),
            amount="100.00",
            treatment="income",
            category_id="salary",
            category_name="Salary",
            category_kind="income",
            eur="100.00",
            dkk="746.00",
        ),
        _fact(
            transaction_id="t3",
            booking_date=date(2025, 7, 12),
            amount="25.00",
            treatment="unclassified",
            category_id=None,
            category_name=None,
            category_kind=None,
            eur="25.00",
            dkk="186.50",
        ),
    ]


def _categories() -> list[dict[str, object]]:
    return [
        {
            "category_id": "expenses",
            "parent_id": None,
            "name": "Expenses",
            "kind": "expense",
            "sort_order": 1,
            "archived": False,
            "revision": 1,
        },
        {
            "category_id": "food",
            "parent_id": "expenses",
            "name": "Food",
            "kind": "expense",
            "sort_order": 1,
            "archived": False,
            "revision": 1,
        },
        {
            "category_id": "dining",
            "parent_id": "expenses",
            "name": "Dining",
            "kind": "expense",
            "sort_order": 2,
            "archived": False,
            "revision": 1,
        },
        {
            "category_id": "income",
            "parent_id": None,
            "name": "Income",
            "kind": "income",
            "sort_order": 2,
            "archived": False,
            "revision": 1,
        },
        {
            "category_id": "salary",
            "parent_id": "income",
            "name": "Salary",
            "kind": "income",
            "sort_order": 1,
            "archived": False,
            "revision": 1,
        },
    ]


def _payment_detail() -> dict[str, object]:
    return {
        "transaction_id": "t1",
        "detail_id": "paypal-1",
        "external_reference": "source-ref",
        "reference": "purchase-ref",
        "merchant_name": "Synthetic merchant",
        "event_kind": "unknown",
        "source_amount": Decimal("-12.50"),
        "source_currency": "EUR",
        "source_date": date(2025, 7, 4),
        "merchant_category_code": None,
        "bank_code": None,
        "bank_sub_code": None,
        "bank_amount": Decimal("-12.50"),
        "approved_detail_revision": 2,
        "current_detail_revision": 2,
    }


def _mock_household_data(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts()

    def fetch_facts(
        *, since: date, until: date, account_ids: list[str], entity_ids: list[str]
    ) -> list[dict[str, object]]:
        def matches_scope(row: dict[str, object]) -> bool:
            booking_date = row["as_of"]
            return (
                isinstance(booking_date, date)
                and since <= booking_date <= until
                and row["account_id"] in account_ids
                and (not entity_ids or row["entity_id"] in entity_ids)
            )

        return [row for row in facts if matches_scope(row)]

    monkeypatch.setattr(data, "fetch_household_categories", _categories)
    monkeypatch.setattr(data, "fetch_household_default_accounts", lambda *, entity_ids: ["a1"])
    monkeypatch.setattr(
        data,
        "fetch_household_checking_accounts",
        lambda *, account_ids, entity_ids: account_ids,
    )
    monkeypatch.setattr(data, "fetch_household_report_facts", fetch_facts)
    monkeypatch.setattr(
        data,
        "fetch_household_payment_details",
        lambda *, transaction_ids: [_payment_detail()] if "t1" in transaction_ids else [],
    )
    monkeypatch.setattr(
        data,
        "fetch_household_unmatched_payment_detail_count",
        lambda *, since, until, entity_ids: 1,
    )
    monkeypatch.setattr(
        data,
        "fetch_household_report_freshness",
        lambda *, account_ids, entity_ids, until: {
            "history_start": date(2025, 6, 1),
            "latest_bank_booking_date": date(2025, 7, 10),
            "latest_bank_import_at": datetime(2025, 7, 10, tzinfo=UTC),
            "latest_fx_rate_date": date(2025, 7, 9),
            "latest_payment_detail_sync_at": datetime(2025, 7, 11, tzinfo=UTC),
        },
    )


def test_summary_uses_bank_ledger_once_and_returns_equal_previous_window(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_household_data(monkeypatch)

    response = client.get(
        "/household/reports/summary",
        params={
            "since": "2025-07-01",
            "until": "2025-07-31",
            "entity_id": "e1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filters"]["account_ids"] == ["a1"]
    assert body["filters"]["entity_ids"] == ["e1"]
    assert body["current"]["totals"]["gross_expenses"]["eur"]["amount"] == "12.50"
    assert body["current"]["totals"]["income"]["eur"]["amount"] == "125.00"
    assert body["current"]["totals"]["surplus"]["eur"]["amount"] == "112.50"
    assert body["previous"]["since"] == "2025-05-31"
    assert body["previous"]["until"] == "2025-06-30"
    assert body["previous"]["totals"]["gross_expenses"]["eur"]["amount"] == "20.00"
    assert body["coverage"]["payment_detail_link_count"] == 1
    assert body["coverage"]["payment_detail_reconciled_count"] == 1
    assert body["coverage"]["payment_detail_unmatched_count"] == 1
    assert body["coverage"]["unclassified_transaction_count"] == 1


def test_category_report_rolls_descendants_once_and_filters_branch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_household_data(monkeypatch)

    response = client.get(
        "/household/reports/categories",
        params={
            "since": "2025-07-01",
            "until": "2025-07-31",
            "category_id": "expenses",
        },
    )

    assert response.status_code == 200
    categories = response.json()["categories"]
    assert [category["category_id"] for category in categories] == ["expenses"]
    assert categories[0]["transaction_count"] == 1
    assert categories[0]["totals"]["gross_expenses"]["eur"]["amount"] == "12.50"
    assert categories[0]["children"][0]["category_id"] == "food"


def test_transaction_drilldown_keeps_bank_amount_and_detail_as_sidecar(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_household_data(monkeypatch)
    monkeypatch.setattr(
        data,
        "fetch_household_transaction_page",
        lambda **kwargs: ([row for row in _facts() if row["transaction_id"] == "t1"], 1),
    )

    response = client.get(
        "/household/reports/transactions",
        params={
            "since": "2025-07-01",
            "until": "2025-07-31",
            "category_id": "expenses",
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["signed_amount_native"] == "-12.50"
    assert item["amount_reporting"]["eur"]["amount"] == "-12.50"
    assert item["matching_split_amount_native"] == "-12.50"
    assert item["payment_reconciliation_status"] == "reconciled"
    assert item["payment_details"][0]["merchant_name"] == "Synthetic merchant"
    assert item["payment_details"][0]["event_kind"] == "unknown"


def test_transaction_drilldown_keeps_positive_unclassified_credit_reportable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_household_data(monkeypatch)
    credit = next(row for row in _facts() if row["transaction_id"] == "t3")
    monkeypatch.setattr(
        data,
        "fetch_household_transaction_page",
        lambda **kwargs: ([credit], 1),
    )

    response = client.get(
        "/household/reports/transactions",
        params={
            "since": "2025-07-01",
            "until": "2025-07-31",
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["treatment"] == "unclassified"
    assert item["signed_amount_native"] == "25.00"
    assert item["matching_split_amount_native"] == "25.00"
    assert item["matching_split_amount_reporting"]["eur"]["amount"] == "25.00"
    assert item["allocations"][0]["category_id"] is None


def test_category_filtered_transaction_keeps_full_bank_amount_separate_from_split(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_household_data(monkeypatch)
    first = _fact(
        transaction_id="t-split",
        booking_date=date(2025, 7, 15),
        amount="-60.00",
        treatment="expense",
        category_id="food",
        category_name="Food",
        category_kind="expense",
        eur="-60.00",
        dkk="-447.60",
    )
    second = _fact(
        transaction_id="t-split",
        booking_date=date(2025, 7, 15),
        amount="-40.00",
        treatment="expense",
        category_id="dining",
        category_name="Dining",
        category_kind="expense",
        eur="-40.00",
        dkk="-298.40",
    )
    first["source_amount_native"] = Decimal("-100.00")
    second["source_amount_native"] = Decimal("-100.00")
    monkeypatch.setattr(
        data,
        "fetch_household_transaction_page",
        lambda **kwargs: ([first, second], 1),
    )

    response = client.get(
        "/household/reports/transactions",
        params={
            "since": "2025-07-01",
            "until": "2025-07-31",
            "category_id": "food",
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["signed_amount_native"] == "-100.00"
    assert item["amount_reporting"]["eur"]["amount"] == "-100.00"
    assert item["matching_split_amount_native"] == "-60.00"
    assert item["matching_split_amount_reporting"]["eur"]["amount"] == "-60.00"
    assert len(item["allocations"]) == 2


def test_currency_amounts_serialise_zero_with_scale_in_fixed_point() -> None:
    scaled_zero = Decimal("1.000000000000") - Decimal("1.000000000000")
    assert str(scaled_zero) == "0E-12"

    payload = HouseholdCurrencyAmount(
        amount=scaled_zero,
        known_subtotal=scaled_zero,
        complete=True,
        missing_count=0,
    ).model_dump(mode="json")

    assert payload["amount"] == "0.000000000000"
    assert payload["known_subtotal"] == "0.000000000000"
