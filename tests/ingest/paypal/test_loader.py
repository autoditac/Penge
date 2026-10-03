"""Synthetic PayPal detail persistence tests using the real household upsert."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import Table, create_engine, inspect, select
from sqlalchemy.orm import Session

from penge.household.models import PaymentDetail
from penge.ingest.enablebanking.client import Client
from penge.ingest.enablebanking.loader import LoadResult
from penge.ingest.enablebanking.models import (
    AccountResource,
    Amount,
    PartyIdentification,
    Transaction,
    TransactionsResponse,
)
from penge.ingest.paypal.loader import PayPalDetailMappingError, load_account

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class _TransactionsClient:
    def __init__(self, transactions: list[Transaction]) -> None:
        self.transactions = transactions

    def get_account_transactions(
        self,
        account_uid: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> TransactionsResponse:
        _ = account_uid, date_from, date_to
        return TransactionsResponse(transactions=self.transactions)


def _transaction(**overrides: object) -> Transaction:
    payload: dict[str, object] = {
        "entry_reference": "stable-entry-1",
        "transaction_id": "mutable-request-id-1",
        "transaction_amount": Amount(amount=Decimal("19.95"), currency="EUR"),
        "credit_debit_indicator": "DBIT",
        "status": "BOOK",
        "booking_date": date(2026, 9, 2),
        "creditor": PartyIdentification(name="Synthetic Cafe"),
        "merchant_category_code": "5812",
        "remittance_information": ["Synthetic order 1234"],
    }
    payload.update(overrides)
    return Transaction.model_validate(payload)


def _account(uid: str, identification_hash: str | None = "stable-primary-hash") -> AccountResource:
    return AccountResource(
        uid=uid,
        name="Synthetic PayPal account",
        currency="EUR",
        identification_hash=identification_hash,
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://")
    payment_detail_table = PaymentDetail.__table__
    if not isinstance(payment_detail_table, Table):
        raise TypeError("PaymentDetail mapping must expose a SQLAlchemy Table")
    payment_detail_table.create(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _load(
    engine: Engine,
    account: AccountResource,
    transactions: list[Transaction],
    connection_id: uuid.UUID,
) -> LoadResult:
    client = _TransactionsClient(transactions)
    return load_account(
        engine,
        client=cast(Client, client),
        account=account,
        connection_id=connection_id,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 10, 3),
    )


def test_repeated_sync_and_reconsent_keep_stable_detail_identity(engine: Engine) -> None:
    first_connection = uuid.UUID("00000000-0000-0000-0000-000000000331")
    renewed_connection = uuid.UUID("00000000-0000-0000-0000-000000000332")
    transaction = _transaction()

    first = _load(engine, _account("session-uid-1"), [transaction], first_connection)
    repeated = _load(engine, _account("session-uid-1"), [transaction], first_connection)
    renewed = _load(engine, _account("session-uid-2"), [transaction], renewed_connection)

    assert first.payment_details == repeated.payment_details == renewed.payment_details == 1
    assert first.writes == 1

    with Session(engine) as session:
        details = session.scalars(select(PaymentDetail)).all()
        detail = details[0] if details else None
        assert detail is not None
        assert len(details) == 1
        assert detail.provider == "paypal"
        assert detail.source_account_id == "DE:stable-primary-hash"
        assert detail.external_id == "stable-entry-1"
        assert detail.connection_id == renewed_connection
    assert inspect(engine).get_table_names() == ["household_payment_detail"]


def test_mutable_transaction_id_updates_facts_not_identity(engine: Engine) -> None:
    connection_id = uuid.UUID("00000000-0000-0000-0000-000000000331")
    first = _transaction(transaction_id="request-id-1")
    refreshed = _transaction(transaction_id="request-id-2")

    _load(engine, _account("session-uid-1"), [first], connection_id)
    result = _load(engine, _account("session-uid-2"), [refreshed], connection_id)

    assert result.payment_details == 1
    assert result.writes == 1
    with Session(engine) as session:
        details = session.scalars(select(PaymentDetail)).all()
    assert len(details) == 1
    assert details[0].revision == 2
    assert details[0].source_fields["transaction_id"] == "request-id-2"


@pytest.mark.parametrize(
    ("account", "transaction", "message"),
    [
        (
            _account("session-uid", identification_hash=None),
            _transaction(),
            "primary identification",
        ),
        (_account("session-uid"), _transaction(entry_reference=None), "stable entry_reference"),
    ],
)
def test_missing_source_identity_fails_without_persisting(
    engine: Engine,
    account: AccountResource,
    transaction: Transaction,
    message: str,
) -> None:
    with pytest.raises(PayPalDetailMappingError, match=message):
        _load(
            engine,
            account,
            [transaction],
            uuid.UUID("00000000-0000-0000-0000-000000000331"),
        )

    with Session(engine) as session:
        assert session.scalar(select(PaymentDetail)) is None
