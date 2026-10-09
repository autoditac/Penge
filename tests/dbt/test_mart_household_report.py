"""Regression coverage for signed-polarity reporting of unclassified movements."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from tests.dbt.conftest import DB_URL, DBT_AVAILABLE, run_dbt

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.skipif(
    DB_URL is None or not DBT_AVAILABLE,
    reason="requires an isolated PostgreSQL test database and dbt",
)


def test_mart_reports_unclassified_credits_as_income_and_debits_as_expenses(
    engine: Engine,
    _truncate: None,
) -> None:
    entity_id = uuid.uuid4()
    eur_account_id = uuid.uuid4()
    dkk_account_id = uuid.uuid4()
    as_of = date(2026, 6, 7)
    booked_at = datetime(2026, 6, 7, 12, tzinfo=UTC)
    transactions = [
        (uuid.uuid4(), eur_account_id, "EUR", Decimal("25.00")),
        (uuid.uuid4(), eur_account_id, "EUR", Decimal("-7.00")),
        (uuid.uuid4(), dkk_account_id, "DKK", Decimal("746.00")),
        (uuid.uuid4(), dkk_account_id, "DKK", Decimal("-74.60")),
    ]

    with engine.begin() as conn:
        conn.execute(
            text("insert into entity (id, name, kind) values (:id, :name, 'person')"),
            {"id": entity_id, "name": "Synthetic household"},
        )
        conn.execute(
            text(
                "insert into account (id, entity_id, provider, external_id, name, kind, currency) "
                "values (:id, :entity_id, 'synthetic', :external_id, :name, 'checking', :currency)"
            ),
            [
                {
                    "id": eur_account_id,
                    "entity_id": entity_id,
                    "external_id": "household-report-eur",
                    "name": "Synthetic EUR checking",
                    "currency": "EUR",
                },
                {
                    "id": dkk_account_id,
                    "entity_id": entity_id,
                    "external_id": "household-report-dkk",
                    "name": "Synthetic DKK checking",
                    "currency": "DKK",
                },
            ],
        )
        conn.execute(
            text(
                "insert into fx_rate (as_of, base_ccy, quote_ccy, rate, source) "
                "values (:as_of, 'EUR', 'DKK', 7.46, 'synthetic')"
            ),
            {"as_of": as_of},
        )
        conn.execute(
            text(
                'insert into "transaction" '
                "(id, account_id, ts, value_date, kind, amount, counterparty, description) "
                "values (:id, :account_id, :ts, :value_date, 'card_payment', :amount, "
                "'Unknown synthetic vendor', 'Synthetic unclassified movement')"
            ),
            [
                {
                    "id": transaction_id,
                    "account_id": account_id,
                    "ts": booked_at,
                    "value_date": as_of,
                    "amount": amount,
                }
                for transaction_id, account_id, _, amount in transactions
            ],
        )
        conn.execute(
            text(
                "insert into household_classification "
                "(transaction_id, treatment, review_state, identity_confirmed, provenance, "
                "source_amount, source_currency, source_ts, source_counterparty, source_kind, "
                "explanation) "
                "values (:transaction_id, 'unclassified', 'unclassified', false, 'manual', "
                ":source_amount, :source_currency, :source_ts, 'Unknown synthetic vendor', "
                "'card_payment', 'Synthetic unclassified fixture')"
            ),
            [
                {
                    "transaction_id": transaction_id,
                    "source_amount": amount,
                    "source_currency": currency,
                    "source_ts": booked_at,
                }
                for transaction_id, _, currency, amount in transactions
            ],
        )

    build = run_dbt("run", "--select", "+mart_household_report_daily", "stg_raw__entity")
    assert build.returncode == 0, build.stdout + build.stderr
    tests = run_dbt("test", "--select", "mart_household_report_daily")
    assert tests.returncode == 0, tests.stdout + tests.stderr

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "select account_currency, treatment, reporting_treatment, "
                "allocation_amount_native, allocation_known_amount_eur, "
                "allocation_known_amount_dkk, unclassified_transaction_count, "
                "unclassified_expense_count "
                "from analytics_marts.mart_household_report_daily "
                "where entity_id = :entity_id and as_of = :as_of"
            ),
            {"entity_id": entity_id, "as_of": as_of},
        ).all()

    by_native_amount = {row.allocation_amount_native: row for row in rows}
    assert len(rows) == 4
    assert {
        amount: (row.treatment, row.reporting_treatment) for amount, row in by_native_amount.items()
    } == {
        Decimal("25.0000"): ("unclassified", "income"),
        Decimal("-7.0000"): ("unclassified", "expense"),
        Decimal("746.0000"): ("unclassified", "income"),
        Decimal("-74.6000"): ("unclassified", "expense"),
    }
    assert by_native_amount[Decimal("25.0000")].allocation_known_amount_dkk == Decimal(
        "186.50000000"
    )
    assert by_native_amount[Decimal("746.0000")].allocation_known_amount_eur == Decimal(
        "100.00000000"
    )
    assert by_native_amount[Decimal("-7.0000")].unclassified_expense_count == 1
    assert by_native_amount[Decimal("25.0000")].unclassified_transaction_count == 1
