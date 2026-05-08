"""Pure mapping helpers: Enable Banking models → canonical row dicts.

Kept free of SQLAlchemy / DB concerns so they can be unit-tested
without a database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from penge.ingest.enablebanking.models import BalancesResponse, Transaction


# Preference order for picking "the" account balance to record as
# today's snapshot. ISO 20022 codes; CLBD = ClosingBooked,
# ITBD = InterimBooked (in-day booked), CLAV = ClosingAvailable,
# XPCD = Expected.
_BALANCE_PREFERENCE: tuple[str, ...] = ("CLBD", "ITBD", "CLAV", "XPCD")


def signed_amount(t: Transaction) -> Decimal:
    """Return the transaction amount with the correct sign.

    Enable Banking always reports ``transaction_amount.amount`` as a
    positive Decimal; the direction lives in
    ``credit_debit_indicator`` (CRDT = money in, DBIT = money out).
    """
    raw = t.transaction_amount.amount
    if t.credit_debit_indicator == "DBIT":
        return -abs(raw)
    return abs(raw)


def transaction_kind(t: Transaction) -> str:
    """Map Enable Banking semantics to a canonical ``transaction.kind``.

    PSD2 doesn't carry semantic categories, so we stick to the
    lowest-common-denominator: CRDT = ``deposit``, DBIT =
    ``withdrawal``. Downstream rules / dbt models can reclassify based
    on counterparty patterns.
    """
    return "deposit" if t.credit_debit_indicator == "CRDT" else "withdrawal"


def external_id(t: Transaction) -> str | None:
    """Stable per-account dedup key.

    ``entry_reference`` is documented as immutable across PSU
    authentication sessions, so it's the right primary key. We fall
    back to ``transaction_id`` only when ``entry_reference`` is
    missing — which the spec allows but is rare for booked rows.
    """
    return t.entry_reference or t.transaction_id


def _description(t: Transaction) -> str | None:
    if not t.remittance_information:
        return t.note
    joined = " ".join(s.strip() for s in t.remittance_information if s and s.strip())
    return joined or t.note


def _counterparty(t: Transaction) -> str | None:
    if t.credit_debit_indicator == "CRDT" and t.debtor and t.debtor.name:
        return t.debtor.name
    if t.credit_debit_indicator == "DBIT" and t.creditor and t.creditor.name:
        return t.creditor.name
    return None


def transaction_to_row(
    t: Transaction,
    *,
    account_id: str,
    instrument_id: str,
) -> dict[str, object]:
    """Build a row dict ready for ``transaction`` upsert.

    ``ts`` is the booking date promoted to UTC midnight — PSD2
    transactions don't carry intra-day timestamps. ``value_date`` is
    preserved separately when present.
    """
    booking = t.booking_date or t.value_date or t.transaction_date
    if booking is None:
        raise ValueError("transaction has neither booking_date, value_date, nor transaction_date")
    ts = datetime.combine(booking, datetime.min.time(), tzinfo=UTC)
    amount = signed_amount(t)
    return {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "ts": ts,
        "value_date": t.value_date,
        "kind": transaction_kind(t),
        "quantity": Decimal("1"),
        "price": amount,
        "amount": amount,
        "fee": Decimal("0"),
        "tax": Decimal("0"),
        "fx_rate": None,
        "counterparty": _counterparty(t),
        "description": _description(t),
        "external_id": external_id(t),
    }


def balance_to_market_value(
    balances: BalancesResponse,
) -> tuple[Decimal, date] | None:
    """Pick the most authoritative booked balance, if any.

    Returns ``(amount, reference_date)`` or ``None`` when no usable
    booked balance is present.
    """
    by_type: dict[str, tuple[Decimal, date | None]] = {}
    for b in balances.balances:
        if b.balance_type in by_type:
            continue
        by_type[b.balance_type] = (b.balance_amount.amount, b.reference_date)

    for preferred in _BALANCE_PREFERENCE:
        if preferred in by_type:
            amount, ref = by_type[preferred]
            return amount, ref or date.today()
    return None
