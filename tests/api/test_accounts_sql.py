"""Query-level tests for ``_ACCOUNTS_SQL`` balance changes and import freshness.

Requires a Postgres at ``PENGE_TEST_DATABASE_URL`` (or ``DATABASE_URL``);
skipped otherwise. ``alembic upgrade head`` provides the raw tables. The
dbt mart is not built in the test DB, so a minimal
``analytics_marts.mart_net_worth_daily`` with the dbt model's columns is
created. Everything runs in one transaction that is rolled back, so the
test never leaves data or schema behind.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, text

from penge.api import data

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

_DB_URL = os.environ.get("PENGE_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason="set PENGE_TEST_DATABASE_URL or DATABASE_URL to run SQL tests",
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    assert _DB_URL is not None
    subprocess.run(  # noqa: S603 — fixed migration command in an isolated test database
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": _DB_URL},
        check=True,
    )
    eng = create_engine(_DB_URL)
    try:
        yield eng
    finally:
        eng.dispose()


def test_balance_changed_on_is_latest_day_balance_differs(engine: Engine) -> None:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            mart_exists = conn.execute(
                text("select to_regclass('analytics_marts.mart_net_worth_daily')")
            ).scalar()
            if mart_exists is not None:
                pytest.skip("test DB already has a real mart_net_worth_daily")

            conn.execute(text("create schema if not exists analytics_marts"))
            conn.execute(
                text(
                    """
                    create table analytics_marts.mart_net_worth_daily (
                        entity_id uuid,
                        account_id uuid,
                        account_currency text,
                        as_of date,
                        balance_acct_ccy numeric,
                        balance_eur numeric,
                        balance_dkk numeric
                    )
                    """
                )
            )
            entity_id = conn.execute(
                text("insert into entity (name, kind) values ('Owner A', 'person') returning id")
            ).scalar_one()
            account_ids = {
                ext: conn.execute(
                    text(
                        "insert into account (entity_id, provider, external_id, name, kind, "
                        "currency) values (:e, 'synthetic', :ext, :ext, 'checking', 'DKK') "
                        "returning id"
                    ),
                    {"e": entity_id, "ext": ext},
                ).scalar_one()
                for ext in ("moving", "flat", "empty")
            }
            balances = {
                # changes on 2 Jan, then unchanged for two days
                "moving": [
                    ("2026-01-01", "100"),
                    ("2026-01-02", "150"),
                    ("2026-01-03", "150"),
                    ("2026-01-04", "150"),
                ],
                # never changes: first observed day counts
                "flat": [("2026-01-01", "70"), ("2026-01-02", "70")],
            }
            for ext, series in balances.items():
                for as_of, balance in series:
                    conn.execute(
                        text(
                            "insert into analytics_marts.mart_net_worth_daily "
                            "(entity_id, account_id, account_currency, as_of, balance_acct_ccy) "
                            "values (:e, :a, 'DKK', :d, :b)"
                        ),
                        {
                            "e": entity_id,
                            "a": account_ids[ext],
                            "d": date.fromisoformat(as_of),
                            "b": Decimal(balance),
                        },
                    )

            rows = conn.execute(text(data._ACCOUNTS_SQL)).mappings().all()
            by_ext = {
                ext: next(r for r in rows if str(r["account_id"]) == str(account_id))
                for ext, account_id in account_ids.items()
            }
            assert by_ext["moving"]["balance_changed_on"] == date(2026, 1, 2)
            assert by_ext["flat"]["balance_changed_on"] == date(2026, 1, 1)
            assert by_ext["empty"]["balance_changed_on"] is None
        finally:
            trans.rollback()


def test_identical_nordnet_reimport_advances_only_its_account_freshness(engine: Engine) -> None:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            if (
                conn.execute(
                    text("select to_regclass('analytics_marts.mart_net_worth_daily')")
                ).scalar()
                is not None
            ):
                pytest.skip("test DB already has a real mart_net_worth_daily")
            conn.execute(text("create schema if not exists analytics_marts"))
            conn.execute(
                text(
                    "create table analytics_marts.mart_net_worth_daily "
                    "(account_id uuid, as_of date, balance_acct_ccy numeric)"
                )
            )
            entity_id = conn.execute(
                text("insert into entity (name, kind) values ('Owner B', 'person') returning id")
            ).scalar_one()
            accounts = {
                number: conn.execute(
                    text(
                        "insert into account (entity_id, provider, external_id, name, kind, "
                        "currency) values (:entity, 'nordnet', :number, :number, "
                        "'aktiedepot', 'DKK') returning id"
                    ),
                    {"entity": entity_id, "number": number},
                ).scalar_one()
                for number in ("88889990", "88889991")
            }
            instrument_id = conn.execute(
                text(
                    "insert into instrument (name, kind, currency, isin) "
                    "values ('Synthetic Fund', 'security', 'EUR', 'IE00B4L5Y983') returning id"
                )
            ).scalar_one()
            snapshot = {
                "account": accounts["88889990"],
                "instrument": instrument_id,
                "created": datetime(2026, 1, 1, tzinfo=UTC),
            }
            conn.execute(
                text(
                    "insert into holding_snapshot "
                    "(account_id, instrument_id, as_of, quantity, created_at) "
                    "values (:account, :instrument, '2026-01-01', 2, :created)"
                ),
                snapshot,
            )

            def freshness(number: str) -> datetime | None:
                rows = conn.execute(text(data._ACCOUNTS_SQL)).mappings().all()
                value = next(
                    row["last_updated_at"]
                    for row in rows
                    if row["account_id"] == str(accounts[number])
                )
                return value if isinstance(value, datetime) else None

            assert freshness("88889990") == snapshot["created"]

            def committed_import(
                number: str,
                when: datetime,
                *,
                source: str,
                excluded: bool = False,
                empty: bool = False,
                status: str = "committed",
            ) -> None:
                session_id = conn.execute(
                    text(
                        "insert into import_session "
                        "(source, original_filename, content_sha256, stored_path, "
                        "status, params, expires_at, committed_at) "
                        "values (:source, 'synthetic.csv', :digest, 'synthetic', "
                        ":status, jsonb_build_object("
                        "'account_number', cast(:number as text), "
                        "'empty_snapshot_confirmed', :empty), "
                        ":expires, :committed) returning id"
                    ),
                    {
                        "source": source,
                        "status": status,
                        "number": number,
                        "empty": empty,
                        "digest": "a" * 64,
                        "expires": datetime(2026, 12, 1, tzinfo=UTC),
                        "committed": when,
                    },
                ).scalar_one()
                if not empty:
                    conn.execute(
                        text(
                            "insert into import_row "
                            "(session_id, row_index, kind, payload, excluded) "
                            "values (:session, 0, :kind, "
                            "jsonb_build_object('account_number', cast(:number as text)), "
                            ":excluded)"
                        ),
                        {
                            "session": session_id,
                            "number": number,
                            "kind": "holding" if source == "nordnet_holdings" else "transaction",
                            "excluded": excluded,
                        },
                    )

            first = datetime(2026, 2, 1, tzinfo=UTC)
            second = datetime(2026, 3, 1, tzinfo=UTC)
            committed_import("88889990", first, source="nordnet_transactions")
            assert freshness("88889990") == first
            assert freshness("88889991") is None

            # Reimport the same snapshot: ON CONFLICT preserves created_at.
            conn.execute(
                text(
                    "insert into holding_snapshot "
                    "(account_id, instrument_id, as_of, quantity, created_at) "
                    "values (:account, :instrument, '2026-01-01', 2, :created) "
                    "on conflict on constraint ux_holding_snapshot__account_instrument_as_of "
                    "do update set quantity = excluded.quantity"
                ),
                snapshot,
            )
            committed_import("88889990", second, source="nordnet_holdings")
            committed_import(
                "88889991",
                second,
                source="nordnet_transactions",
                excluded=True,
            )
            assert freshness("88889990") == second
            assert freshness("88889991") is None
            third = datetime(2026, 4, 1, tzinfo=UTC)
            committed_import(
                "88889990", third, source="nordnet_holdings", empty=True, status="staged"
            )
            assert freshness("88889990") == second
            committed_import("88889990", third, source="nordnet_holdings", empty=True)
            assert freshness("88889990") == third
            assert freshness("88889991") is None
            created = conn.execute(
                text(
                    "select created_at from holding_snapshot "
                    "where account_id = :account and instrument_id = :instrument"
                ),
                snapshot,
            ).scalar_one()
            assert created == snapshot["created"]
        finally:
            trans.rollback()
