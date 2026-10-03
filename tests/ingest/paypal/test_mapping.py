"""Privacy and semantic tests for PayPal detail-only mapping."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from penge.ingest.enablebanking.models import (
    AccountResource,
    Amount,
    BankTransactionCode,
    PartyIdentification,
    Transaction,
)
from penge.ingest.paypal.mapping import PayPalDetailPayload, payment_detail_from_transaction


def _transaction(**overrides: object) -> Transaction:
    payload: dict[str, object] = {
        "entry_reference": "stable-entry-1",
        "transaction_id": "request-transaction-id",
        "merchant_category_code": "5812",
        "transaction_amount": Amount(amount=Decimal("19.95"), currency="EUR"),
        "credit_debit_indicator": "DBIT",
        "status": "BOOK",
        "booking_date": date(2026, 9, 2),
        "value_date": date(2026, 9, 1),
        "transaction_date": date(2026, 8, 31),
        "creditor": PartyIdentification(name="Example Cafe"),
        "bank_transaction_code": BankTransactionCode(
            code="PMNT",
            sub_code="RCDT",
            description="Synthetic payment",
        ),
        "remittance_information": ["Order 1234"],
        "note": "Synthetic note that must not enter the detail payload",
    }
    payload.update(overrides)
    return Transaction.model_validate(payload)


def _map(transaction: Transaction) -> PayPalDetailPayload:
    return payment_detail_from_transaction(
        transaction,
        account=AccountResource(
            uid="synthetic-session-account-uid",
            identification_hash="synthetic-primary-account-hash",
        ),
        connection_id=uuid.UUID("00000000-0000-0000-0000-000000000331"),
    )


def test_payment_detail_keeps_source_amount_currency_and_booking_date() -> None:
    detail = _map(_transaction())

    assert detail["amount"] == Decimal("-19.95")
    assert detail["currency"] == "EUR"
    assert detail["ts"] == datetime(2026, 9, 2, tzinfo=UTC)
    assert detail["external_id"] == "stable-entry-1"
    assert detail["source_account_id"] == "DE:synthetic-primary-account-hash"
    assert detail["merchant_name"] == "Example Cafe"
    assert detail["reference"] == "Order 1234"


def test_payment_direction_does_not_infer_purchase_or_refund() -> None:
    debit = _map(_transaction(credit_debit_indicator="DBIT"))
    credit = _map(
        _transaction(
            credit_debit_indicator="CRDT",
            debtor=PartyIdentification(name="Synthetic payer"),
            remittance_information=["Refund for order 1234"],
        )
    )

    assert debit["event_kind"] == "unknown"
    assert debit["amount"] == Decimal("-19.95")
    assert credit["event_kind"] == "unknown"
    assert credit["amount"] == Decimal("19.95")
    assert credit["merchant_name"] is None


def test_transaction_id_is_not_used_when_stable_entry_reference_is_missing() -> None:
    with pytest.raises(ValueError, match="stable entry_reference"):
        _map(_transaction(entry_reference=None))


def test_source_identity_survives_account_uid_rotation_between_sessions() -> None:
    transaction = _transaction()
    first = payment_detail_from_transaction(
        transaction,
        account=AccountResource(
            uid="session-one-account-uid",
            identification_hash="stable-primary-hash",
        ),
        connection_id=uuid.UUID("00000000-0000-0000-0000-000000000331"),
    )
    renewed = payment_detail_from_transaction(
        transaction,
        account=AccountResource(
            uid="session-two-account-uid",
            identification_hash="stable-primary-hash",
        ),
        connection_id=uuid.UUID("00000000-0000-0000-0000-000000000332"),
    )

    assert first["source_account_id"] == renewed["source_account_id"]
    assert first["external_id"] == renewed["external_id"]


def test_mutable_transaction_id_does_not_change_detail_identity() -> None:
    original = _map(_transaction(transaction_id="mutable-id-1"))
    refreshed = _map(_transaction(transaction_id="mutable-id-2"))

    assert original["external_id"] == refreshed["external_id"]
    assert original["source_account_id"] == refreshed["source_account_id"]
    assert (
        original["source_fields"]["transaction_id"] != refreshed["source_fields"]["transaction_id"]
    )


def test_alternate_hashes_do_not_replace_a_missing_primary_hash() -> None:
    account = AccountResource.model_validate(
        {"uid": "session-account-uid", "identification_hashes": ["alternate-hash"]}
    )

    with pytest.raises(ValueError, match="stable primary identification_hash"):
        payment_detail_from_transaction(
            _transaction(),
            account=account,
            connection_id=None,
        )


def test_date_falls_back_from_booking_to_value_then_transaction_date() -> None:
    value_date = _map(_transaction(booking_date=None))
    transaction_date = _map(
        _transaction(booking_date=None, value_date=None),
    )

    assert value_date["ts"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert transaction_date["ts"] == datetime(2026, 8, 31, tzinfo=UTC)


def test_source_fields_are_a_strict_whitelist() -> None:
    source_fields = _map(_transaction())["source_fields"]
    assert source_fields == {
        "entry_reference": "stable-entry-1",
        "transaction_id": "request-transaction-id",
        "merchant_category_code": "5812",
        "bank_code": "PMNT",
        "bank_sub_code": "RCDT",
        "transaction_date": datetime(2026, 8, 31, tzinfo=UTC),
    }
    assert "description" not in source_fields
    assert "note" not in source_fields
    assert "remittance_information" not in source_fields


def test_processor_label_is_not_reported_as_merchant() -> None:
    detail = _map(
        _transaction(
            creditor=PartyIdentification(name="PayPal *Example Cafe"),
        )
    )

    assert detail["merchant_name"] is None


def test_counterparty_name_without_merchant_category_is_not_guessed_as_merchant() -> None:
    detail = _map(_transaction(merchant_category_code=None))

    assert detail["merchant_name"] is None


def test_personal_email_and_address_like_remittance_are_not_retained() -> None:
    email_detail = _map(
        _transaction(remittance_information=["Buyer person@example.invalid order 1234"])
    )
    address_detail = _map(
        _transaction(remittance_information=["Delivery address: 12 Main Street, Berlin"])
    )

    assert email_detail["reference"] == "Buyer [redacted] order 1234"
    assert address_detail["reference"] is None


def test_reference_before_embedded_email_and_address_is_retained() -> None:
    detail = _map(
        _transaction(
            remittance_information=[
                "Order REF-1234 buyer@example.invalid Delivery address: Example Street 9"
            ]
        )
    )

    assert detail["reference"] == "Order REF-1234 [redacted]"


def test_remittance_without_safe_content_is_omitted() -> None:
    detail = _map(_transaction(remittance_information=["buyer@example.invalid"]))

    assert detail["reference"] is None


def test_foreign_currency_is_preserved_without_conversion() -> None:
    detail = _map(
        _transaction(
            transaction_amount=Amount(amount=Decimal("10.25"), currency="GBP"),
        )
    )

    assert detail["amount"] == Decimal("-10.25")
    assert detail["currency"] == "GBP"
