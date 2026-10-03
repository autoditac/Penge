"""Database checks for the synthetic household source fixture."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from tests.dbt.conftest import DBT_AVAILABLE, run_dbt
from tests.household.conftest import DB_URL
from tests.household.fixtures import BANK_ENTRIES, seed_household_source_facts

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="requires an isolated Postgres database in PENGE_TEST_DATABASE_URL",
)


def test_source_fixture_seeds_synthetic_accounts_entries_and_fx(
    postgres_engine: Engine,
    clean_postgres_database: None,
) -> None:
    seeded = seed_household_source_facts(postgres_engine)

    with postgres_engine.begin() as connection:
        account_count: int = connection.execute(text("select count(*) from account")).scalar_one()
        transaction_count: int = connection.execute(
            text('select count(*) from "transaction"')
        ).scalar_one()
        fx_count: int = connection.execute(text("select count(*) from fx_rate")).scalar_one()

    assert account_count == 2
    assert transaction_count == len(BANK_ENTRIES)
    assert fx_count == 3
    assert set(seeded.entity_ids) == {"member-a", "member-b"}
    assert set(seeded.account_ids) == {"eur-checking", "dkk-checking"}
    assert all("Synthetic" in entry.description for entry in BANK_ENTRIES)


@pytest.mark.skipif(
    not DBT_AVAILABLE,
    reason="requires a working dbt installation",
)
def test_existing_cashflow_mart_keeps_raw_bank_transaction_semantics(
    postgres_engine: Engine,
    clean_postgres_database: None,
) -> None:
    seeded = seed_household_source_facts(postgres_engine)
    result = run_dbt("build", "--select", "+mart_cashflow_daily")
    assert result.returncode == 0, result.stdout + result.stderr

    with postgres_engine.begin() as connection:
        row = connection.execute(
            text(
                "select inflow_acct_ccy, outflow_acct_ccy, net_acct_ccy "
                "from analytics_marts.mart_cashflow_daily "
                "where account_id = :account_id and as_of = '2026-06-03'"
            ),
            {"account_id": seeded.account_ids["eur-checking"]},
        ).one()

    assert row.inflow_acct_ccy == 0
    assert row.outflow_acct_ccy == Decimal("41.4500")
    assert row.net_acct_ccy == Decimal("-41.4500")


@pytest.mark.skipif(not DBT_AVAILABLE, reason="requires a working dbt installation")
def test_real_report_api_conserves_splits_and_keeps_paypal_bank_grain(
    postgres_engine: Engine,
    postgres_api_client: TestClient,
) -> None:
    """CI-only: real correction API, materialized dbt facts, and report SQL."""
    seeded = seed_household_source_facts(postgres_engine)
    root_response = postgres_api_client.post(
        "/household/categories",
        json={"expected_revision": 0, "name": "Synthetic food", "kind": "expense"},
    )
    assert root_response.status_code == 201, root_response.text
    root_id = root_response.json()["id"]
    child_response = postgres_api_client.post(
        "/household/categories",
        json={
            "expected_revision": 0,
            "name": "Synthetic groceries",
            "kind": "expense",
            "parent_id": root_id,
        },
    )
    assert child_response.status_code == 201, child_response.text
    child_id = child_response.json()["id"]
    transaction_id = str(seeded.transaction_ids["supermarket-split"])
    corrected = postgres_api_client.patch(
        f"/household/transactions/{transaction_id}/classification",
        json={
            "expected_revision": 0,
            "treatment": "expense",
            "allocations": [
                {"category_id": child_id, "amount": "-80.00"},
                {"category_id": root_id, "amount": "-45.40"},
            ],
            "explanation": "Synthetic exact household split",
        },
    )
    assert corrected.status_code == 200, corrected.text
    built = run_dbt("build", "--select", "+mart_household_report_daily", "+mart_cashflow_daily")
    assert built.returncode == 0, built.stdout + built.stderr

    filters = {
        "since": "2026-06-02",
        "until": "2026-06-02",
        "account_id": str(seeded.account_ids["eur-checking"]),
        "category_id": root_id,
    }
    summary = postgres_api_client.get("/household/reports/summary", params=filters)
    assert summary.status_code == 200, summary.text
    assert Decimal(summary.json()["current"]["totals"]["gross_expenses"]["eur"]["amount"]) == (
        Decimal("125.40")
    )
    assert summary.json()["coverage"]["bank_transaction_count"] == 1
    drilldown = postgres_api_client.get("/household/reports/transactions", params=filters)
    assert drilldown.status_code == 200, drilldown.text
    [purchase] = drilldown.json()["items"]
    assert purchase["transaction_id"] == transaction_id
    assert Decimal(purchase["signed_amount_native"]) == Decimal("-125.40")
    assert Decimal(purchase["matching_split_amount_native"]) == Decimal("-125.40")
    assert len(purchase["allocations"]) == 2

    child_filters = {**filters, "category_id": child_id}
    selected = postgres_api_client.get("/household/reports/summary", params=child_filters)
    assert selected.status_code == 200, selected.text
    assert Decimal(selected.json()["current"]["totals"]["gross_expenses"]["eur"]["amount"]) == (
        Decimal("80.00")
    )
    selected_rows = postgres_api_client.get("/household/reports/transactions", params=child_filters)
    assert selected_rows.status_code == 200, selected_rows.text
    [selected_purchase] = selected_rows.json()["items"]
    assert Decimal(selected_purchase["signed_amount_native"]) == Decimal("-125.40")
    assert Decimal(selected_purchase["matching_split_amount_native"]) == Decimal("-80.00")

    bank_filters = {**filters, "since": "2026-06-03", "until": "2026-06-03"}
    del bank_filters["category_id"]
    bank_report = postgres_api_client.get("/household/reports/transactions", params=bank_filters)
    assert bank_report.status_code == 200, bank_report.text
    assert bank_report.json()["total"] == 2
    assert {row["transaction_id"] for row in bank_report.json()["items"]} == {
        str(seeded.transaction_ids["mixed-merchant-purchase"]),
        str(seeded.transaction_ids["paypal-direct"]),
    }
