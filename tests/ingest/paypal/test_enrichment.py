"""PayPal sync stays enrichment-only against approved bank-led allocations."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from penge.household import models as m
from penge.household import schemas as s
from penge.household import service
from penge.ingest.enablebanking.client import Client
from penge.ingest.enablebanking.models import (
    AccountResource,
    Amount,
    PartyIdentification,
    Transaction,
    TransactionsResponse,
)
from penge.ingest.paypal.loader import load_account

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

BANK_AMOUNT = Decimal("-12.34")
FIRST_CONNECTION = uuid.UUID("00000000-0000-0000-0000-000000000331")
RENEWED_CONNECTION = uuid.UUID("00000000-0000-0000-0000-000000000332")


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


def _transaction(amount: Decimal = Decimal("12.34")) -> Transaction:
    return Transaction.model_validate(
        {
            "entry_reference": "stable-entry-enrichment",
            "transaction_id": "mutable-request-id",
            "transaction_amount": Amount(amount=amount, currency="EUR"),
            "credit_debit_indicator": "DBIT",
            "status": "BOOK",
            "booking_date": date(2026, 9, 1),
            "creditor": PartyIdentification(name="Synthetic Shop"),
            "merchant_category_code": "5999",
            "remittance_information": ["Synthetic order 42"],
        }
    )


def _sync(engine: Engine, uid: str, connection_id: uuid.UUID, transaction: Transaction) -> None:
    load_account(
        engine,
        client=cast(Client, _TransactionsClient([transaction])),
        account=AccountResource(
            uid=uid,
            name="Synthetic PayPal account",
            currency="EUR",
            identification_hash="synthetic-primary-hash",
        ),
        connection_id=connection_id,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 10, 3),
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    database = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    m.Base.metadata.create_all(database)
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def bank_transaction_id(engine: Engine) -> uuid.UUID:
    account_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-checking-account")
    transaction_id = uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-checking-paypal-debit")
    with Session(engine) as session, session.begin():
        session.add(m.Account(id=account_id, provider="gls", currency="EUR"))
        session.add(
            m.SourceTransaction(
                id=transaction_id,
                account_id=account_id,
                ts=datetime(2026, 9, 2, 12, tzinfo=UTC),
                amount=BANK_AMOUNT,
                kind="direct_debit",
                counterparty="Synthetic payment processor",
                description="Synthetic processor debit",
            )
        )
    return transaction_id


def _approve_bank_link(engine: Engine, bank_transaction_id: uuid.UUID) -> None:
    with Session(engine) as session, session.begin():
        category = service.save_category(
            session,
            s.CategoryWrite(expected_revision=0, name="Online purchases", kind="expense"),
        )
        detail: m.PaymentDetail = session.scalars(select(m.PaymentDetail)).one()
        service.save_classification(
            session,
            bank_transaction_id,
            s.ClassificationWrite(
                expected_revision=0,
                treatment="expense",
                allocations=[s.Split(category_id=category.id, amount=BANK_AMOUNT)],
                detail_links=[
                    s.PaymentDetailLink(
                        detail_id=detail.id,
                        detail_revision=detail.revision,
                        bank_amount=BANK_AMOUNT,
                    )
                ],
                explanation="Synthetic human-approved PayPal enrichment",
            ),
        )


def _ledger_counts(session: Session) -> tuple[int | None, int | None]:
    return (
        session.scalar(select(func.count()).select_from(m.Account)),
        session.scalar(select(func.count()).select_from(m.SourceTransaction)),
    )


def test_unlinked_sync_is_review_only_and_adds_no_ledger_rows(
    engine: Engine, bank_transaction_id: uuid.UUID
) -> None:
    _sync(engine, "session-uid-1", FIRST_CONNECTION, _transaction())

    with Session(engine) as session:
        assert _ledger_counts(session) == (1, 1)
        assert session.scalar(select(func.count()).select_from(m.DetailLink)) == 0
        assert session.get(m.Classification, bank_transaction_id) is None


def test_reconsent_keeps_approved_link_and_changed_detail_marks_it_stale(
    engine: Engine, bank_transaction_id: uuid.UUID
) -> None:
    _sync(engine, "session-uid-1", FIRST_CONNECTION, _transaction())
    _approve_bank_link(engine, bank_transaction_id)

    _sync(engine, "session-uid-1", FIRST_CONNECTION, _transaction())
    _sync(engine, "session-uid-2", RENEWED_CONNECTION, _transaction())
    with Session(engine) as session:
        classification = session.get(m.Classification, bank_transaction_id)
        assert classification is not None
        out = service.classification_out(session, classification)
        assert not out.detail_changed
        assert [link.bank_amount for link in out.detail_links] == [BANK_AMOUNT]
        assert sum(split.amount for split in out.allocations) == BANK_AMOUNT
        assert session.scalar(select(func.count()).select_from(m.PaymentDetail)) == 1
        assert _ledger_counts(session) == (1, 1)

    _sync(engine, "session-uid-2", RENEWED_CONNECTION, _transaction(Decimal("15.00")))
    with Session(engine) as session:
        classification = session.get(m.Classification, bank_transaction_id)
        assert classification is not None
        out = service.classification_out(session, classification)
        assert out.detail_changed
        assert out.revision == 1
        assert [link.bank_amount for link in out.detail_links] == [BANK_AMOUNT]
        bank = session.get(m.SourceTransaction, bank_transaction_id)
        assert bank is not None
        assert bank.amount == BANK_AMOUNT
        assert _ledger_counts(session) == (1, 1)
