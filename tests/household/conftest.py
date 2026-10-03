"""Postgres and real-API fixtures for household integration tests."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from penge.api import data
from penge.api.app import create_app
from penge.api.imports.engine import get_import_engine
from penge.household.models import Account, Base, SourceTransaction
from tests.household.database_setup import upgrade_isolated_database
from tests.household.db_guard import validate_isolated_test_database_url

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL")
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    """Upgrade the explicitly configured disposable Postgres test database."""
    if DB_URL is None:
        pytest.skip("PENGE_TEST_DATABASE_URL is required for household database tests")
    test_database_url = validate_isolated_test_database_url(
        DB_URL,
        allow_destructive_test_db=os.environ.get("PENGE_ALLOW_DESTRUCTIVE_TEST_DB"),
    )
    upgrade_isolated_database(test_database_url)
    eng = create_engine(test_database_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Create household and minimal source-projection tables in SQLite."""
    database = create_engine(f"sqlite:///{tmp_path / 'household.sqlite'}")
    Base.metadata.create_all(database)
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Provide one isolated SQLite ORM session per service/API contract test."""
    with Session(engine) as database_session:
        yield database_session


@pytest.fixture
def synthetic_sources(session: Session) -> dict[str, uuid.UUID]:
    """Seed synthetic bank transactions for SQLite service/API contract tests."""
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
    """Map synthetic providers to their deterministic account identifiers."""
    return {
        provider: uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-household-account-{provider}")
        for provider in synthetic_sources
    }


@pytest.fixture
def clean_postgres_database(postgres_engine: Engine) -> Iterator[None]:
    """Clear synthetic source, household, and dbt rows around each test."""

    def clean() -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE household_rule_preview, household_payment_detail_link, "
                    "household_audit, household_transaction_link, household_allocation, "
                    "household_classification, household_payment_detail, household_rule, "
                    "household_merchant_alias, household_merchant, household_category, "
                    "fx_rate, entity RESTART IDENTITY CASCADE"
                )
            )
            connection.execute(text("DROP SCHEMA IF EXISTS analytics_staging CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS analytics_marts CASCADE"))

    clean()
    yield
    clean()


@pytest.fixture
def postgres_api_client(
    clean_postgres_database: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """Serve the actual API against the test Postgres without route/data mocks."""
    assert DB_URL is not None
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("PENGE_HOUSEHOLD_ENABLED", "true")
    monkeypatch.setenv("PENGE_REFRESH_STATE_DIR", str(tmp_path / "refresh-state"))

    get_import_engine.cache_clear()
    data.get_engine.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_import_engine.cache_clear()
        data.get_engine.cache_clear()
