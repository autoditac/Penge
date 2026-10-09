"""SQLite harness with synthetic read-only source projections."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from penge.household.models import Account, Base, SourceTransaction

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Create all household and minimal source projection tables in SQLite."""
    database = create_engine(f"sqlite:///{tmp_path / 'household.sqlite'}")
    Base.metadata.create_all(database)
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Provide a transaction-scoped SQLAlchemy session for one test."""
    with Session(engine) as database_session:
        yield database_session


@pytest.fixture
def synthetic_sources(session: Session) -> dict[str, uuid.UUID]:
    """Three bank source transactions with deterministic synthetic facts."""
    result: dict[str, uuid.UUID] = {}
    for index, provider in enumerate(("gls", "ebank", "lunar"), start=1):
        account_id = uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-household-account-{provider}")
        transaction_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"synthetic-household-transaction-{provider}"
        )
        session.add(Account(id=account_id, provider=provider, currency="EUR"))
        session.add(
            SourceTransaction(
                id=transaction_id,
                account_id=account_id,
                ts=datetime(2026, 9, index, 12, tzinfo=UTC),
                amount=Decimal("-12.34"),
                kind="card_payment",
                counterparty="Synthetic Market",
                description=f"Synthetic purchase {index}",
            )
        )
        result[provider] = transaction_id
    session.flush()
    return result


@pytest.fixture
def synthetic_account_ids(synthetic_sources: dict[str, uuid.UUID]) -> dict[str, uuid.UUID]:
    """Map each synthetic provider to its deterministic account identifier."""
    return {
        provider: uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-household-account-{provider}")
        for provider in synthetic_sources
    }
