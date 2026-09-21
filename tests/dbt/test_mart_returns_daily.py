"""Regression test for issue #282: zero/negative ``return_factor`` on
near-zero valuations in ``mart_returns_daily``.

Seeds two synthetic scenarios that reproduce the production repro data
exactly (a spurious ``-0.002``-style negative factor and a spurious
``0.0`` factor), builds the mart's dependency chain for real against a
throwaway Postgres schema, and asserts:

  * ``dbt build``/``dbt test`` succeed (the previously-failing
    ``mart_returns_daily__factor_positive`` data test passes), and
  * the specific days that used to produce 0/negative factors now
    produce NULL, while an adjacent normal day still produces a real
    factor (guarding against a fix that nulls everything out).

All data is synthetic; no real account, security, or balance data.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import text

from tests.dbt.conftest import run_dbt

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

_ENTITY_ID = str(uuid.uuid4())
_ACCOUNT_CASH_ID = str(uuid.uuid4())
_ACCOUNT_FUND_ID = str(uuid.uuid4())
_INSTRUMENT_CASH_ID = str(uuid.uuid4())
_INSTRUMENT_FUND_ID = str(uuid.uuid4())


def _seed(engine: Engine) -> None:
    """Insert two synthetic scenarios that reproduce issue #282.

    Scenario A (account scope, negative factor): a checking account's
    cash balance is snapshotted at -20 on 2026-01-02 with no same-day
    transaction (e.g. a bank-side fee/overdraft the source captured
    only as a revised balance) — begin_mv (30) + net_flow (0) stays
    positive while end_mv goes negative, the exact shape of the
    production ``-0.0020419866``-style violations.

    Scenario B (asset_class scope, zero factor): a fund position is
    bought for 100 and fully sold the next day for only 80 (a
    mark-to-market loss realised on exit) — begin_mv (100) + net_flow
    (-80) stays positive (20) while end_mv drops to exactly 0, the
    exact shape of the production ``0.0`` violations.
    """
    with engine.begin() as conn:
        conn.execute(
            text("insert into entity (id, name, kind) values (:id, 'Test household', 'person')"),
            {"id": _ENTITY_ID},
        )
        conn.execute(
            text(
                "insert into account (id, entity_id, provider, external_id, name, kind, currency) "
                "values (:id, :entity_id, 'synthetic', :ext, :name, :kind, 'EUR')"
            ),
            [
                {
                    "id": _ACCOUNT_CASH_ID,
                    "entity_id": _ENTITY_ID,
                    "ext": "acct-cash",
                    "name": "Test checking",
                    "kind": "checking",
                },
                {
                    "id": _ACCOUNT_FUND_ID,
                    "entity_id": _ENTITY_ID,
                    "ext": "acct-fund",
                    "name": "Test brokerage",
                    "kind": "brokerage",
                },
            ],
        )
        conn.execute(
            text(
                "insert into instrument (id, name, kind, currency) "
                "values (:id, :name, :kind, 'EUR')"
            ),
            [
                {"id": _INSTRUMENT_CASH_ID, "name": "EUR cash", "kind": "cash"},
                {"id": _INSTRUMENT_FUND_ID, "name": "Test fund", "kind": "fund"},
            ],
        )
        conn.execute(
            text(
                "insert into fx_rate (id, as_of, base_ccy, quote_ccy, rate) "
                "values (:id, :d, 'EUR', 'DKK', 7.46)"
            ),
            {"id": str(uuid.uuid4()), "d": date(2025, 12, 1)},
        )

        # Scenario A: cash account, negative revaluation with no flow.
        conn.execute(
            text(
                "insert into holding_snapshot "
                "(id, account_id, instrument_id, as_of, quantity, market_value) "
                "values (:id, :account_id, :instrument_id, :as_of, 1, :mv)"
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_CASH_ID,
                    "instrument_id": _INSTRUMENT_CASH_ID,
                    "as_of": date(2026, 1, 1),
                    "mv": 30,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_CASH_ID,
                    "instrument_id": _INSTRUMENT_CASH_ID,
                    "as_of": date(2026, 1, 2),
                    "mv": -20,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_CASH_ID,
                    "instrument_id": _INSTRUMENT_CASH_ID,
                    "as_of": date(2026, 1, 3),
                    "mv": 50,
                },
            ],
        )
        conn.execute(
            text(
                'insert into "transaction" '
                "(id, account_id, instrument_id, ts, value_date, kind, amount) "
                "values (:id, :account_id, :instrument_id, :ts, :value_date, :kind, :amount)"
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_CASH_ID,
                    "instrument_id": None,
                    "ts": "2026-01-01T10:00:00+00:00",
                    "value_date": date(2026, 1, 1),
                    "kind": "deposit",
                    "amount": 30,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_CASH_ID,
                    "instrument_id": None,
                    "ts": "2026-01-03T10:00:00+00:00",
                    "value_date": date(2026, 1, 3),
                    "kind": "deposit",
                    "amount": 70,
                },
            ],
        )

        # Scenario B: fund account, full liquidation at a loss.
        # A cash snapshot (always 0) makes 'cash' the account's
        # attribution class, so the fund's own buy/sell flows are not
        # double-counted into the 'fund' asset-class scope.
        conn.execute(
            text(
                "insert into holding_snapshot "
                "(id, account_id, instrument_id, as_of, quantity, market_value) "
                "values (:id, :account_id, :instrument_id, :as_of, :qty, :mv)"
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_FUND_ID,
                    "instrument_id": _INSTRUMENT_CASH_ID,
                    "as_of": date(2026, 2, 1),
                    "qty": 0,
                    "mv": 0,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_FUND_ID,
                    "instrument_id": _INSTRUMENT_CASH_ID,
                    "as_of": date(2026, 2, 2),
                    "qty": 0,
                    "mv": 80,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_FUND_ID,
                    "instrument_id": _INSTRUMENT_FUND_ID,
                    "as_of": date(2026, 2, 1),
                    "qty": 10,
                    "mv": 100,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_FUND_ID,
                    "instrument_id": _INSTRUMENT_FUND_ID,
                    "as_of": date(2026, 2, 2),
                    "qty": 0,
                    "mv": 0,
                },
            ],
        )
        conn.execute(
            text(
                'insert into "transaction" '
                "(id, account_id, instrument_id, ts, value_date, kind, amount) "
                "values (:id, :account_id, :instrument_id, :ts, :value_date, :kind, :amount)"
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_FUND_ID,
                    "instrument_id": _INSTRUMENT_FUND_ID,
                    "ts": "2026-02-01T10:00:00+00:00",
                    "value_date": date(2026, 2, 1),
                    "kind": "buy",
                    "amount": -100,
                },
                {
                    "id": str(uuid.uuid4()),
                    "account_id": _ACCOUNT_FUND_ID,
                    "instrument_id": _INSTRUMENT_FUND_ID,
                    "ts": "2026-02-02T10:00:00+00:00",
                    "value_date": date(2026, 2, 2),
                    "kind": "sell",
                    "amount": 80,
                },
            ],
        )


def test_mart_returns_daily_nulls_non_positive_end_mv(engine: Engine, _truncate: None) -> None:
    """Zero/near-zero end-of-day values null the factor instead of tripping the guard test."""
    _seed(engine)

    build = run_dbt("build", "--select", "mart_position_value_daily+", "mart_returns_daily+")
    assert build.returncode == 0, build.stdout + build.stderr

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "select scope, scope_key, as_of, return_factor_eur, return_factor_dkk "
                "from analytics_marts.mart_returns_daily "
                "where (scope = 'account' and scope_key = :acct) "
                "or (scope = 'asset_class' and scope_key = 'fund') "
                "order by scope, as_of"
            ),
            {"acct": _ACCOUNT_CASH_ID},
        ).all()

    by_day = {(r.scope, r.as_of): r for r in rows}

    negative_day = by_day[("account", date(2026, 1, 2))]
    assert negative_day.return_factor_eur is None
    assert negative_day.return_factor_dkk is None

    recovered_day = by_day[("account", date(2026, 1, 3))]
    assert recovered_day.return_factor_eur == 1
    assert recovered_day.return_factor_dkk == 1

    liquidation_day = by_day[("asset_class", date(2026, 2, 2))]
    assert liquidation_day.return_factor_eur is None
    assert liquidation_day.return_factor_dkk is None

    funding_day = by_day[("asset_class", date(2026, 2, 1))]
    assert funding_day.return_factor_eur == 1
    assert funding_day.return_factor_dkk == 1
