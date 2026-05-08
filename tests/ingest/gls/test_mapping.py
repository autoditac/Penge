"""Unit tests for :mod:`penge.ingest.gls.mapping`."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from penge.ingest.enablebanking.models import (
    Amount,
    Balance,
    BalancesResponse,
    PartyIdentification,
    Transaction,
)
from penge.ingest.gls.mapping import (
    balance_to_market_value,
    external_id,
    signed_amount,
    transaction_kind,
    transaction_to_row,
)


def _txn(**overrides: object) -> Transaction:
    base: dict[str, object] = {
        "entry_reference": "ENT-1",
        "transaction_id": "TX-1",
        "transaction_amount": Amount(amount=Decimal("12.34"), currency="EUR"),
        "credit_debit_indicator": "CRDT",
        "status": "BOOK",
        "booking_date": date(2026, 5, 1),
        "value_date": date(2026, 5, 1),
        "remittance_information": ["Salary May"],
    }
    base.update(overrides)
    return Transaction.model_validate(base)


def test_signed_amount_credit_is_positive() -> None:
    assert signed_amount(_txn()) == Decimal("12.34")


def test_signed_amount_debit_is_negative() -> None:
    t = _txn(credit_debit_indicator="DBIT")
    assert signed_amount(t) == Decimal("-12.34")


def test_transaction_kind_maps_indicator() -> None:
    assert transaction_kind(_txn(credit_debit_indicator="CRDT")) == "deposit"
    assert transaction_kind(_txn(credit_debit_indicator="DBIT")) == "withdrawal"


def test_external_id_prefers_entry_reference() -> None:
    assert external_id(_txn()) == "ENT-1"


def test_external_id_falls_back_to_transaction_id() -> None:
    assert external_id(_txn(entry_reference=None)) == "TX-1"


def test_transaction_to_row_basic_credit() -> None:
    row = transaction_to_row(
        _txn(debtor=PartyIdentification(name="ACME GmbH")),
        account_id="acct-1",
        instrument_id="cash-eur",
    )
    assert row["account_id"] == "acct-1"
    assert row["instrument_id"] == "cash-eur"
    assert row["ts"] == datetime(2026, 5, 1, tzinfo=UTC)
    assert row["value_date"] == date(2026, 5, 1)
    assert row["kind"] == "deposit"
    assert row["quantity"] == Decimal("1")
    assert row["amount"] == Decimal("12.34")
    assert row["price"] == Decimal("12.34")
    assert row["fee"] == Decimal("0")
    assert row["tax"] == Decimal("0")
    assert row["external_id"] == "ENT-1"
    assert row["counterparty"] == "ACME GmbH"
    assert row["description"] == "Salary May"


def test_transaction_to_row_debit_uses_creditor_name() -> None:
    row = transaction_to_row(
        _txn(
            credit_debit_indicator="DBIT",
            creditor=PartyIdentification(name="Bäckerei Müller"),
        ),
        account_id="a",
        instrument_id="i",
    )
    assert row["counterparty"] == "Bäckerei Müller"
    assert row["amount"] == Decimal("-12.34")


def test_transaction_to_row_joins_remittance_lines() -> None:
    row = transaction_to_row(
        _txn(remittance_information=["Invoice 1234", "Thank you"]),
        account_id="a",
        instrument_id="i",
    )
    assert row["description"] == "Invoice 1234 Thank you"


def test_transaction_to_row_falls_back_to_value_date() -> None:
    row = transaction_to_row(
        _txn(booking_date=None, value_date=date(2026, 5, 2), transaction_date=None),
        account_id="a",
        instrument_id="i",
    )
    assert row["ts"] == datetime(2026, 5, 2, tzinfo=UTC)


def test_transaction_to_row_raises_without_any_date() -> None:
    with pytest.raises(ValueError):
        transaction_to_row(
            _txn(booking_date=None, value_date=None, transaction_date=None),
            account_id="a",
            instrument_id="i",
        )


def test_balance_to_market_value_prefers_clbd_over_itbd() -> None:
    resp = BalancesResponse(
        balances=[
            Balance(
                name="Interim",
                balance_amount=Amount(amount=Decimal("10"), currency="EUR"),
                balance_type="ITBD",
                reference_date=date(2026, 5, 1),
            ),
            Balance(
                name="Closing",
                balance_amount=Amount(amount=Decimal("99.99"), currency="EUR"),
                balance_type="CLBD",
                reference_date=date(2026, 5, 1),
            ),
        ]
    )
    picked = balance_to_market_value(resp)
    assert picked is not None
    assert picked == (Decimal("99.99"), date(2026, 5, 1))


def test_balance_to_market_value_returns_none_when_unrecognised() -> None:
    resp = BalancesResponse(
        balances=[
            Balance(
                name="Authorised",
                balance_amount=Amount(amount=Decimal("1"), currency="EUR"),
                balance_type="AUTH",
                reference_date=date(2026, 5, 1),
            ),
        ]
    )
    assert balance_to_market_value(resp) is None
