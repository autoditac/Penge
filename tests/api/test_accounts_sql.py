"""Query-level test for ``_ACCOUNTS_SQL`` (``balance_changed_on``).

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
from datetime import date
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
    subprocess.run(  # noqa: S603
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
