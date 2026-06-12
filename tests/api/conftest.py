"""Shared fixtures for the read-API tests.

The data-access layer is monkeypatched with synthetic rows so no test
touches a database; route logic, serialisation, masking, and parameter
validation are exercised through the real ASGI stack via TestClient.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from penge.api import data
from penge.api.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator


def synthetic_net_worth_rows() -> list[dict[str, object]]:
    """Two accounts on two days, EUR and DKK populated."""
    return [
        {
            "as_of": date(2026, 6, 1),
            "entity_id": "e1",
            "account_id": "a1",
            "account_currency": "EUR",
            "balance_acct_ccy": Decimal("1000.0000"),
            "balance_eur": Decimal("1000.0000"),
            "balance_dkk": Decimal("7460.0000"),
        },
        {
            "as_of": date(2026, 6, 1),
            "entity_id": "e1",
            "account_id": "a2",
            "account_currency": "DKK",
            "balance_acct_ccy": Decimal("3730.0000"),
            "balance_eur": Decimal("500.0000"),
            "balance_dkk": Decimal("3730.0000"),
        },
        {
            "as_of": date(2026, 6, 2),
            "entity_id": "e1",
            "account_id": "a1",
            "account_currency": "EUR",
            "balance_acct_ccy": Decimal("1010.0000"),
            "balance_eur": Decimal("1010.0000"),
            "balance_dkk": Decimal("7534.6000"),
        },
    ]


def synthetic_allocation_rows() -> list[dict[str, object]]:
    """Latest-day rows with the three grouping dimensions attached."""
    return [
        {
            "as_of": date(2026, 6, 2),
            "balance_eur": Decimal("1010.0000"),
            "balance_dkk": Decimal("7534.6000"),
            "entity_name": "Synthetic A",
            "account_currency": "EUR",
            "account_kind": "frie_midler",
        },
        {
            "as_of": date(2026, 6, 2),
            "balance_eur": Decimal("500.0000"),
            "balance_dkk": Decimal("3730.0000"),
            "entity_name": "Synthetic B",
            "account_currency": "DKK",
            "account_kind": "aktiesparekonto",
        },
        {
            "as_of": date(2026, 6, 2),
            "balance_eur": Decimal("490.0000"),
            "balance_dkk": Decimal("3655.4000"),
            "entity_name": "Synthetic B",
            "account_currency": "DKK",
            "account_kind": "frie_midler",
        },
    ]


def synthetic_account_rows() -> list[dict[str, object]]:
    """Account dimension rows with synthetic (never real) identifiers."""
    return [
        {
            "account_id": "a1",
            "entity_id": "e1",
            "entity_name": "Synthetic A",
            "provider": "nordnet",
            "name": "Depot (1162)",
            "kind": "frie_midler",
            "currency": "EUR",
            "iban": "DK5000400440116243",
        },
        {
            "account_id": "a2",
            "entity_id": "e1",
            "entity_name": "Synthetic A",
            "provider": "lunar",
            "name": "Lønkonto",
            "kind": "cash",
            "currency": "DKK",
            "iban": None,
        },
        {
            "account_id": "a3",
            "entity_id": "e1",
            "entity_name": "Synthetic A",
            "provider": "manual",
            "name": None,
            "kind": "real_estate",
            "currency": "DKK",
            "iban": None,
        },
    ]


def synthetic_returns_rows() -> list[dict[str, object]]:
    """Household scope: +1% day, dormant day, +2% day with a flow."""
    return [
        {
            "as_of": date(2026, 6, 1),
            "scope": "household",
            "scope_key": "household",
            "begin_mv_eur": Decimal("1000.0000"),
            "end_mv_eur": Decimal("1010.0000"),
            "net_flow_eur": Decimal("0.0000"),
            "return_factor_eur": Decimal("1.0100000000"),
            "begin_mv_dkk": Decimal("7460.0000"),
            "end_mv_dkk": Decimal("7534.6000"),
            "net_flow_dkk": Decimal("0.0000"),
            "return_factor_dkk": Decimal("1.0100000000"),
        },
        {
            "as_of": date(2026, 6, 2),
            "scope": "household",
            "scope_key": "household",
            "begin_mv_eur": Decimal("1010.0000"),
            "end_mv_eur": Decimal("1010.0000"),
            "net_flow_eur": Decimal("0.0000"),
            "return_factor_eur": Decimal("1.0000000000"),
            "begin_mv_dkk": Decimal("7534.6000"),
            "end_mv_dkk": Decimal("7534.6000"),
            "net_flow_dkk": Decimal("0.0000"),
            "return_factor_dkk": Decimal("1.0000000000"),
        },
        {
            "as_of": date(2026, 6, 3),
            "scope": "household",
            "scope_key": "household",
            "begin_mv_eur": Decimal("1010.0000"),
            "end_mv_eur": Decimal("1122.0000"),
            "net_flow_eur": Decimal("90.0000"),
            "return_factor_eur": Decimal("1.0200000000"),
            "begin_mv_dkk": Decimal("7534.6000"),
            "end_mv_dkk": Decimal("8370.1200"),
            "net_flow_dkk": Decimal("671.4000"),
            "return_factor_dkk": Decimal("1.0200000000"),
        },
    ]


def synthetic_benchmark_rows() -> list[dict[str, object]]:
    """Three daily closes for the synthetic world ETF."""
    return [
        {"as_of": date(2026, 6, 1), "close": Decimal("100.0000"), "currency": "EUR"},
        {"as_of": date(2026, 6, 2), "close": Decimal("101.0000"), "currency": "EUR"},
        {"as_of": date(2026, 6, 3), "close": Decimal("103.0200"), "currency": "EUR"},
    ]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient over the real app with the data layer faked."""

    def fake_net_worth(
        *,
        since: date,
        until: date,
        account_id: str | None,
        entity_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        rows = [
            row
            for row in synthetic_net_worth_rows()
            if since <= row["as_of"] <= until  # type: ignore[operator]  # as_of is date
            and (account_id is None or row["account_id"] == account_id)
            and (entity_id is None or row["entity_id"] == entity_id)
        ]
        return rows[offset : offset + limit], len(rows)

    def fake_net_worth_total(
        *,
        since: date,
        until: date,
        account_id: str | None,
        entity_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        rows, _ = fake_net_worth(
            since=since,
            until=until,
            account_id=account_id,
            entity_id=entity_id,
            limit=10_000,
            offset=0,
        )
        by_day: dict[date, dict[str, Decimal]] = {}
        for row in rows:
            as_of = row["as_of"]
            assert isinstance(as_of, date)
            bucket = by_day.setdefault(
                as_of, {"balance_eur": Decimal(0), "balance_dkk": Decimal(0)}
            )
            bucket["balance_eur"] += row["balance_eur"]  # type: ignore[operator]  # Decimal rows
            bucket["balance_dkk"] += row["balance_dkk"]  # type: ignore[operator]  # Decimal rows
        totals: list[dict[str, object]] = [
            {"as_of": day, **values} for day, values in sorted(by_day.items())
        ]
        return totals[offset : offset + limit], len(totals)

    def fake_cashflow(
        *,
        since: date,
        until: date,
        account_id: str | None,
        entity_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        rows: list[dict[str, object]] = [
            {
                "as_of": date(2026, 6, 1),
                "entity_id": "e1",
                "account_id": "a1",
                "account_currency": "EUR",
                "inflow_acct_ccy": Decimal("100.0000"),
                "outflow_acct_ccy": Decimal("40.0000"),
                "net_acct_ccy": Decimal("60.0000"),
                "inflow_eur": Decimal("100.0000"),
                "outflow_eur": Decimal("40.0000"),
                "net_eur": Decimal("60.0000"),
                "inflow_dkk": Decimal("746.0000"),
                "outflow_dkk": Decimal("298.4000"),
                "net_dkk": Decimal("447.6000"),
            }
        ]
        kept = [
            row
            for row in rows
            if since <= row["as_of"] <= until  # type: ignore[operator]  # as_of is date
            and (account_id is None or row["account_id"] == account_id)
            and (entity_id is None or row["entity_id"] == entity_id)
        ]
        return kept[offset : offset + limit], len(kept)

    monkeypatch.setattr(data, "fetch_net_worth", fake_net_worth)
    monkeypatch.setattr(data, "fetch_net_worth_total", fake_net_worth_total)
    monkeypatch.setattr(data, "fetch_cashflow", fake_cashflow)
    monkeypatch.setattr(data, "fetch_allocation_rows", synthetic_allocation_rows)
    monkeypatch.setattr(data, "fetch_accounts", synthetic_account_rows)

    def fake_returns(
        *,
        since: date,
        until: date,
        scope: str,
        scope_key: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        rows = [
            row
            for row in synthetic_returns_rows()
            if since <= row["as_of"] <= until  # type: ignore[operator]  # as_of is date
            and row["scope"] == scope
            and (scope_key is None or row["scope_key"] == scope_key)
        ]
        return rows[offset : offset + limit], len(rows)

    def fake_returns_window(*, since: date, until: date, scope: str) -> list[dict[str, object]]:
        rows, _ = fake_returns(
            since=since, until=until, scope=scope, scope_key=None, limit=10_000, offset=0
        )
        return rows

    def fake_benchmark_series(
        *,
        instrument_id: str,
        since: date,
        until: date,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        if instrument_id != "i1":
            return [], 0
        rows = [
            row
            for row in synthetic_benchmark_rows()
            if since <= row["as_of"] <= until  # type: ignore[operator]  # as_of is date
        ]
        return rows[offset : offset + limit], len(rows)

    monkeypatch.setattr(data, "fetch_returns", fake_returns)
    monkeypatch.setattr(data, "fetch_returns_window", fake_returns_window)
    monkeypatch.setattr(
        data,
        "fetch_benchmarks",
        lambda: [
            {
                "instrument_id": "i1",
                "name": "Synthetic World ETF",
                "ticker": "SYNW",
                "currency": "EUR",
                "first_as_of": date(2026, 6, 1),
                "last_as_of": date(2026, 6, 3),
                "points": 3,
            }
        ],
    )
    monkeypatch.setattr(data, "fetch_benchmark_series", fake_benchmark_series)
    monkeypatch.setattr(
        data,
        "fetch_fees",
        lambda *, since, until: [
            {
                "year": 2026,
                "account_id": "a1",
                "fees_eur": Decimal("24.0000"),
                "fees_dkk": Decimal("179.0400"),
            }
        ],
    )
    monkeypatch.setattr(
        data,
        "fetch_freshness",
        lambda: [
            {"mart": "mart_net_worth_daily", "latest_as_of": date(2026, 6, 2), "row_count": 3},
            {"mart": "mart_cashflow_daily", "latest_as_of": None, "row_count": 0},
            {"mart": "mart_returns_daily", "latest_as_of": date(2026, 6, 3), "row_count": 3},
        ],
    )

    with TestClient(create_app()) as test_client:
        yield test_client
