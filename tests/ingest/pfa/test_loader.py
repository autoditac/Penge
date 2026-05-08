"""Integration tests for the PFA → Postgres loader.

These exercise SQLAlchemy + Postgres-specific features (UUID PKs,
``ON CONFLICT``) and need a real Postgres reachable via
``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``). When neither
env var is set the entire module is skipped — local ``pytest``
runs without a database remain green.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from penge.ingest.pfa import (
    ACCOUNT_KIND_ALDERSOPSPARING,
    ACCOUNT_KIND_LIVRENTE,
    ACCOUNT_KIND_RATEPENSION,
    PROVIDER,
    ParsedContribution,
    ParsedHolding,
    ParsedPensionsoversigt,
    ParsedScheme,
    load_records,
)

_DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason="set PENGE_TEST_DATABASE_URL or DATABASE_URL to run loader tests",
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
def engine() -> Iterator[Engine]:
    """Engine pointed at the test DB; runs ``alembic upgrade head`` once."""

    assert _DB_URL is not None
    eng = create_engine(_DB_URL)
    env = {**os.environ, "DATABASE_URL": _DB_URL}
    subprocess.run(  # noqa: S603  - controlled command line below
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]  # pytest decorator is untyped under strict mypy
def _truncate(engine: Engine) -> Iterator[None]:
    """Wipe tables before each test — keeps tests independent."""

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE holding_snapshot, transaction, instrument, "
                "account, entity RESTART IDENTITY CASCADE"
            )
        )
    yield


def _make_statement() -> ParsedPensionsoversigt:
    """Build a small but realistic synthetic Pensionsoversigt record."""

    aldersopsparing = ParsedScheme(
        scheme_kind=ACCOUNT_KIND_ALDERSOPSPARING,
        sub_policy_id="1",
        opening_balance_dkk=Decimal("50000.00"),
        closing_balance_dkk=Decimal("60497.50"),
        contributions=(
            ParsedContribution(source="employer", amount_dkk=Decimal("0.00")),
            ParsedContribution(source="employee", amount_dkk=Decimal("8500.00")),
        ),
        return_dkk=Decimal("2500.00"),
        fees_dkk=Decimal("120.00"),
        pal_skat_dkk=Decimal("382.50"),
        holdings=(
            ParsedHolding(
                fund_name="PFA Plus AA",
                allocation_pct=Decimal("60.00"),
                quantity=Decimal("120.5"),
                market_value_dkk=Decimal("36298.50"),
            ),
            ParsedHolding(
                fund_name="PFA Globale Aktier",
                allocation_pct=Decimal("30.00"),
                quantity=Decimal("60.2"),
                market_value_dkk=Decimal("18149.25"),
            ),
        ),
    )
    ratepension = ParsedScheme(
        scheme_kind=ACCOUNT_KIND_RATEPENSION,
        sub_policy_id="1",
        opening_balance_dkk=Decimal("850000.00"),
        closing_balance_dkk=Decimal("946897.50"),
        contributions=(ParsedContribution(source="employer", amount_dkk=Decimal("63000.00")),),
        return_dkk=Decimal("42500.00"),
        fees_dkk=Decimal("2100.00"),
        pal_skat_dkk=Decimal("6502.50"),
        holdings=(),
    )
    livrente = ParsedScheme(
        scheme_kind=ACCOUNT_KIND_LIVRENTE,
        sub_policy_id="1",
        opening_balance_dkk=Decimal("120000.00"),
        closing_balance_dkk=Decimal("136732.00"),
        contributions=(ParsedContribution(source="employer", amount_dkk=Decimal("12000.00")),),
        return_dkk=Decimal("6000.00"),
        fees_dkk=Decimal("350.00"),
        pal_skat_dkk=Decimal("918.00"),
        holdings=(),
    )
    return ParsedPensionsoversigt(
        policy_number="12-345-678",
        as_of=date(2025, 12, 31),
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        schemes=(aldersopsparing, ratepension, livrente),
        extracted_via="pdfplumber",
    )


def test_load_records_creates_expected_rows(engine: Engine) -> None:
    """Loading a fresh statement creates entity, accounts, instruments,
    holding snapshots and one transaction per non-zero summary line."""

    result = load_records(
        engine,
        statements=[_make_statement()],
        entity_name="Test Person",
    )

    # 1 entity, 3 accounts (1 per scheme), 2 instruments
    # (Aldersopsparing has 2 funds; ratepension/livrente have none),
    # 2 holding snapshots (Aldersopsparing only), and
    # 1 (employer 0,00 dropped) + 1 (employee) + 1 return + 1 fee + 1 pal-skat
    #   + 1 employer + 1 return + 1 fee + 1 pal-skat (ratepension)
    #   + 1 employer + 1 return + 1 fee + 1 pal-skat (livrente)
    # = 4 + 4 + 4 = 12 transactions
    assert result.entities == 1
    assert result.accounts == 3
    assert result.instruments == 2
    assert result.holding_snapshots == 2
    assert result.transactions == 12

    with engine.begin() as conn:
        accounts = conn.execute(
            text(
                "SELECT external_id, kind, currency FROM account "
                "WHERE provider = :p ORDER BY external_id"
            ),
            {"p": PROVIDER},
        ).all()
        assert {a.kind for a in accounts} == {
            ACCOUNT_KIND_ALDERSOPSPARING,
            ACCOUNT_KIND_RATEPENSION,
            ACCOUNT_KIND_LIVRENTE,
        }
        assert all(a.currency == "DKK" for a in accounts)

        # All instrument tickers carry the documented prefix.
        tickers = [
            row.ticker
            for row in conn.execute(text("SELECT ticker FROM instrument ORDER BY ticker")).all()
        ]
        assert all(t.startswith("PFA:") for t in tickers)


def test_load_records_is_idempotent(engine: Engine) -> None:
    """Re-running ``load_records`` on the same statement converges to
    the same database state and posts no duplicate transactions."""

    statement = _make_statement()
    load_records(engine, statements=[statement], entity_name="Test Person")
    load_records(engine, statements=[statement], entity_name="Test Person")

    with engine.begin() as conn:
        n_accounts = conn.execute(
            text("SELECT count(*) FROM account WHERE provider = :p"),
            {"p": PROVIDER},
        ).scalar_one()
        n_transactions = conn.execute(text("SELECT count(*) FROM transaction")).scalar_one()
        n_snapshots = conn.execute(text("SELECT count(*) FROM holding_snapshot")).scalar_one()
    assert n_accounts == 3
    assert n_transactions == 12
    assert n_snapshots == 2
