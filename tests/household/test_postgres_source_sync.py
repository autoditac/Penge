"""Real migrated Postgres source-sync invariants; synthetic facts only."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from penge.household import models as m
from penge.household import schemas as s
from penge.household import service
from penge.ingest.enablebanking.loader import _persist
from penge.ingest.enablebanking.models import BalancesResponse, Transaction
from tests.household.conftest import DB_URL

pytestmark = pytest.mark.skipif(
    DB_URL is None, reason="isolated household test database not configured"
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_source_sync_database(clean_postgres_database: None) -> None:
    """Keep each source-sync scenario isolated on the guarded Postgres fixture."""
    _ = clean_postgres_database


def booked(key: str, amount: str = "12.34", label: str = "Synthetic Grocer") -> Transaction:
    return Transaction.model_validate(
        {
            "entry_reference": key,
            "transaction_amount": {"amount": amount, "currency": "EUR"},
            "credit_debit_indicator": "DBIT",
            "status": "BOOK",
            "booking_date": "2026-06-01",
            "creditor": {"name": label},
        }
    )


def sync(engine: Engine, account: str, rows: list[Transaction], currency: str = "EUR") -> int:
    result = _persist(
        engine,
        provider="gls",
        transactions=rows,
        balances=BalancesResponse.model_validate({"balances": []}),
        entity_name="Synthetic Household",
        account_external_id=account,
        account_name="Synthetic Bank",
        currency=currency,
        iban=None,
        dk_tax_treatment=None,
    )
    return int(result.writes)


def test_sync_learning_manual_override_source_drift_and_details(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGE_HOUSEHOLD_ENABLED", "true")
    account = str(uuid.uuid4())
    label = f"Synthetic Grocer {account}"
    first, second = f"synthetic-{uuid.uuid4()}", f"synthetic-{uuid.uuid4()}"
    sync(postgres_engine, account, [booked(first, label=label)])
    with Session(postgres_engine) as session, session.begin():
        txn = session.scalar(
            select(m.SourceTransaction)
            .join(m.Account, m.SourceTransaction.account_id == m.Account.id)
            .where(m.Account.external_id == account)
            .limit(1)
        )
        assert txn is not None
        key = txn.id
        category = service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=0,
                name="Synthetic Groceries",
                kind="expense",
            ),
        )
        merchant = service.save_merchant(
            session,
            s.MerchantWrite(
                expected_revision=0,
                name=f"Synthetic Grocer {account}",
                identity_kind="stable",
                confirmed=True,
            ),
        )
        service.save_alias(
            session,
            s.AliasWrite(
                expected_revision=0,
                merchant_id=merchant.id,
                provider="gls",
                label=label,
                confirmed=True,
            ),
        )
        record = service.save_classification(
            session,
            key,
            s.ClassificationWrite(
                expected_revision=0,
                treatment="expense",
                merchant_id=merchant.id,
                identity_confirmed=True,
                explanation="synthetic confirmed purchase",
                allocations=[s.Split(category_id=category.id, amount=Decimal("-12.34"))],
            ),
        )
        revision = record.revision
        merchant_id = merchant.id
        category_id = category.id
        detail = service.upsert_payment_detail(
            session,
            s.PaymentDetailWrite(
                provider="paypal",
                source_account_id=f"DE:synthetic-{account}",
                external_id=first,
                ts=datetime(2026, 6, 1, tzinfo=UTC),
                amount=Decimal("-99.00"),
                currency="DKK",
                event_kind="purchase",
            ),
        )
        count_before = session.scalar(select(func.count()).select_from(m.SourceTransaction))
        record = service.save_classification(
            session,
            key,
            s.ClassificationWrite(
                expected_revision=revision,
                treatment="expense",
                merchant_id=merchant.id,
                identity_confirmed=True,
                explanation="approved original gross enrichment",
                allocations=[s.Split(category_id=category.id, amount=Decimal("-12.34"))],
                detail_links=[
                    s.PaymentDetailLink(
                        detail_id=detail.id,
                        detail_revision=detail.revision,
                        bank_amount=Decimal("-12.34"),
                    )
                ],
            ),
        )
        assert session.scalar(select(func.count()).select_from(m.SourceTransaction)) == count_before
        assert txn.amount == Decimal("-12.34")
        revision = record.revision
    assert sync(postgres_engine, account, [booked(first, label=label)]) == 0
    sync(postgres_engine, account, [booked(first, label=label), booked(second, label=label)])
    with Session(postgres_engine) as session:
        rows: Sequence[m.Classification] = session.scalars(
            select(m.Classification).where(m.Classification.merchant_id == merchant_id)
        ).all()
        assert len(rows) == 2
        assert sorted(row.provenance for row in rows) == ["manual", "rule"]
        assert service.require(session, m.Classification, key).revision == revision
    assert sync(postgres_engine, account, [booked(first, "15.00", label)]) > 0
    with Session(postgres_engine) as session:
        record = service.require(session, m.Classification, key)
        out = service.classification_out(session, record)
        assert out.source_changed and out.review_state == "needs_review"
        assert record.provenance == "manual"
        assert record.revision == revision + 1
        assert out.allocations == [s.Split(category_id=category_id, amount=Decimal("-12.34"))]
        assert len(out.detail_links) == 1
        rule = service.latest_rule(session, service.require(session, m.Merchant, merchant_id))
        assert rule is not None and rule.state == "disabled"
    assert sync(postgres_engine, account, [booked(first, "15.00", label)]) == 0


def test_postgres_category_and_append_only_guards(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as session, session.begin():
        parent = service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=0,
                name="Synthetic Guard Parent",
                kind="expense",
            ),
        )
        child = service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=0,
                name="Synthetic Guard Child",
                kind="expense",
                parent_id=parent.id,
            ),
        )
        parent_id, child_id = parent.id, child.id
        event_id = session.scalar(select(m.Audit.id).where(m.Audit.subject_id == parent_id))
        assert event_id is not None
    with pytest.raises(DBAPIError), Session(postgres_engine) as session, session.begin():
        session.execute(
            update(m.Category).where(m.Category.id == parent_id).values(parent_id=child_id)
        )
    with pytest.raises(DBAPIError), Session(postgres_engine) as session, session.begin():
        session.execute(update(m.Category).where(m.Category.id == child_id).values(kind="income"))
    with pytest.raises(DBAPIError), Session(postgres_engine) as session, session.begin():
        session.execute(delete(m.Audit).where(m.Audit.id == event_id))


def test_concurrent_first_correction_has_one_winner(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGE_HOUSEHOLD_ENABLED", "true")
    account = str(uuid.uuid4())
    sync(postgres_engine, account, [booked(str(uuid.uuid4()), label=f"Synthetic {account}")])
    with Session(postgres_engine) as session, session.begin():
        key = session.scalar(
            select(m.SourceTransaction.id)
            .join(m.Account, m.SourceTransaction.account_id == m.Account.id)
            .where(m.Account.external_id == account)
            .limit(1)
        )
        assert key is not None
        category = service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=0,
                name=f"Synthetic Concurrency {account}",
                kind="expense",
            ),
        )
        category_id = category.id

    def correct() -> int:
        try:
            with Session(postgres_engine) as session, session.begin():
                service.save_classification(
                    session,
                    key,
                    s.ClassificationWrite(
                        expected_revision=0,
                        treatment="expense",
                        explanation="synthetic concurrent edit",
                        allocations=[s.Split(category_id=category_id, amount=Decimal("-12.34"))],
                    ),
                )
            return 200
        except service.HouseholdError as exc:
            return int(exc.status)

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(lambda _: correct(), range(2))) == [200, 409]
    with Session(postgres_engine) as session:
        record = service.require(session, m.Classification, key)
        assert record.revision == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(m.Audit)
                .where(
                    m.Audit.subject_type == "classification",
                    m.Audit.subject_id == key,
                )
            )
            == 1
        )


@pytest.mark.parametrize("changed_field", ["date", "counterparty", "kind", "currency"])
def test_resync_reviews_every_reporting_snapshot_field(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    monkeypatch.setenv("PENGE_HOUSEHOLD_ENABLED", "true")
    account = str(uuid.uuid4())
    entry = str(uuid.uuid4())
    initial = booked(entry, label=f"Synthetic {account}")
    sync(postgres_engine, account, [initial])
    with Session(postgres_engine) as session, session.begin():
        key = session.scalar(
            select(m.SourceTransaction.id)
            .join(m.Account, m.SourceTransaction.account_id == m.Account.id)
            .where(m.Account.external_id == account)
            .limit(1)
        )
        assert key is not None
        category = service.save_category(
            session,
            s.CategoryWrite(
                expected_revision=0,
                name=f"Synthetic Snapshot {account}",
                kind="expense",
            ),
        )
        category_id = category.id
        service.save_classification(
            session,
            key,
            s.ClassificationWrite(
                expected_revision=0,
                treatment="expense",
                explanation="synthetic protected override",
                allocations=[s.Split(category_id=category_id, amount=Decimal("-12.34"))],
            ),
        )
    payload = initial.model_dump(mode="json")
    currency = "EUR"
    if changed_field == "date":
        payload["booking_date"] = "2026-06-02"
    elif changed_field == "counterparty":
        payload["creditor"] = {"name": "Synthetic Corrected Source Merchant"}
    elif changed_field == "kind":
        payload["credit_debit_indicator"] = "CRDT"
    else:
        currency = "DKK"
        payload["transaction_amount"] = {"amount": "12.34", "currency": currency}
    corrected = Transaction.model_validate(payload)
    sync(postgres_engine, account, [corrected], currency=currency)
    with Session(postgres_engine) as session:
        record = service.require(session, m.Classification, key)
        out = service.classification_out(session, record)
        assert record.revision == 2
        assert out.source_changed and out.review_state == "needs_review"
        assert out.provenance == "manual"
        assert out.allocations == [s.Split(category_id=category_id, amount=Decimal("-12.34"))]
    assert sync(postgres_engine, account, [corrected], currency=currency) == 0


def test_migration_downgrade_keeps_raw_facts(postgres_engine: Engine) -> None:
    """Disposable database only; round-trip removes only newly added tables."""
    assert DB_URL is not None
    with postgres_engine.connect() as connection:
        before = connection.scalar(select(func.count()).select_from(m.SourceTransaction))
    env = {**os.environ, "DATABASE_URL": DB_URL}
    for command in (
        ["alembic", "downgrade", "0007_account_metadata_overrides"],
        ["alembic", "upgrade", "head"],
    ):
        subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True)  # noqa: S603
    with postgres_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(m.SourceTransaction)) == before
        assert connection.scalar(text("SELECT count(*) FROM household_category")) == 17
