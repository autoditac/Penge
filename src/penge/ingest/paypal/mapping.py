"""Map Enable Banking PayPal transactions to detail-only payment records.

This adapter deliberately does not create canonical accounts, ledger transactions, or balances.
PayPal details can enrich an approved checking-account movement, but they are never household
cashflow on their own.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, TypedDict

from penge.ingest.enablebanking.mapping import signed_amount

if TYPE_CHECKING:
    from penge.ingest.enablebanking.models import AccountResource, Transaction

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_MAX_REFERENCE_LENGTH = 500
_MAX_SOURCE_ACCOUNT_ID_LENGTH = 200
_ISO_CURRENCY_CODE = re.compile(r"[A-Z]{3}\Z")
_ADDRESS_MARKER = re.compile(
    r"\b(?:shipping|delivery|address|lieferadresse|lieferung|versand|straße|strasse|"
    r"postcode|postal\s+code|plz|zip)\b",
    re.IGNORECASE,
)


class PayPalSourceFields(TypedDict, total=False):
    """Allowed Enable Banking facts on one detail record."""

    entry_reference: str
    transaction_id: str
    merchant_category_code: str
    bank_code: str
    bank_sub_code: str
    transaction_date: datetime | None


class PayPalDetailPayload(TypedDict):
    """Typed values validated into the household detail write contract."""

    provider: Literal["paypal"]
    source_account_id: str
    external_id: str
    connection_id: uuid.UUID | None
    ts: datetime
    amount: Decimal
    currency: str
    merchant_name: str | None
    reference: str | None
    event_kind: Literal["unknown"]
    source_fields: PayPalSourceFields


def _source_date(transaction: Transaction) -> date:
    source_date = transaction.booking_date or transaction.value_date or transaction.transaction_date
    if source_date is None:
        raise ValueError("PayPal detail has no booking, value, or transaction date")
    return source_date


def _source_account_id(account: AccountResource) -> str:
    identification_hash = account.identification_hash
    if identification_hash is None or not identification_hash.strip():
        raise ValueError("PayPal account has no stable primary identification_hash")
    source_account_id = f"DE:{identification_hash}"
    if len(source_account_id) > _MAX_SOURCE_ACCOUNT_ID_LENGTH:
        raise ValueError("PayPal account identification_hash exceeds the supported length")
    return source_account_id


def _counterparty_name(transaction: Transaction) -> str | None:
    if transaction.credit_debit_indicator != "DBIT" or transaction.merchant_category_code is None:
        return None
    party = transaction.creditor
    name = party.name.strip() if party is not None and party.name is not None else ""
    if not name or _EMAIL.search(name) or name.casefold().startswith("paypal"):
        return None
    return name


def _reference(transaction: Transaction) -> str | None:
    lines = [line.strip() for line in transaction.remittance_information if line.strip()]
    if not lines:
        return None
    reference = " ".join(lines)
    reference = _EMAIL.sub("[redacted]", reference)
    address_marker = _ADDRESS_MARKER.search(reference)
    if address_marker is not None:
        reference = reference[: address_marker.start()].rstrip(" ,;:-|")
    reference = reference[:_MAX_REFERENCE_LENGTH]
    if not reference.replace("[redacted]", "").strip():
        return None
    return reference


def _source_fields(transaction: Transaction) -> PayPalSourceFields:
    fields: PayPalSourceFields = {"entry_reference": transaction.entry_reference or ""}
    if transaction.transaction_id is not None:
        fields["transaction_id"] = transaction.transaction_id
    if transaction.merchant_category_code is not None:
        fields["merchant_category_code"] = transaction.merchant_category_code
    if transaction.bank_transaction_code is not None:
        if transaction.bank_transaction_code.code is not None:
            fields["bank_code"] = transaction.bank_transaction_code.code
        if transaction.bank_transaction_code.sub_code is not None:
            fields["bank_sub_code"] = transaction.bank_transaction_code.sub_code
    if transaction.transaction_date is not None:
        fields["transaction_date"] = datetime.combine(
            transaction.transaction_date,
            datetime.min.time(),
            tzinfo=UTC,
        )
    return fields


def payment_detail_from_transaction(
    transaction: Transaction,
    *,
    account: AccountResource,
    connection_id: uuid.UUID | None,
) -> PayPalDetailPayload:
    """Create one privacy-minimized detail record with a stable source identity.

    `entry_reference` is the only accepted identity. Enable Banking documents
    `transaction_id` as potentially mutable across requests, so it is retained only
    as a source fact and never used as a deduplication key.
    """
    entry_reference = transaction.entry_reference
    if entry_reference is None or not entry_reference.strip():
        raise ValueError("PayPal detail has no stable entry_reference")
    currency = transaction.transaction_amount.currency.upper()
    if _ISO_CURRENCY_CODE.fullmatch(currency) is None:
        raise ValueError("PayPal detail has an invalid source currency")

    booked = _source_date(transaction)
    return {
        "provider": "paypal",
        "source_account_id": _source_account_id(account),
        "external_id": entry_reference,
        "connection_id": connection_id,
        "ts": datetime.combine(booked, datetime.min.time(), tzinfo=UTC),
        "amount": signed_amount(transaction),
        "currency": currency,
        "merchant_name": _counterparty_name(transaction),
        "reference": _reference(transaction),
        "event_kind": "unknown",
        "source_fields": _source_fields(transaction),
    }


__all__ = ["PayPalDetailPayload", "PayPalSourceFields", "payment_detail_from_transaction"]
