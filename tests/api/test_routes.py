"""Route-level tests for the read API (synthetic data, no DB)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestNetWorth:
    def test_account_rows_carry_eur_and_dkk_in_parallel(self, client: TestClient) -> None:
        body = client.get(
            "/net-worth/daily", params={"since": "2026-06-01", "until": "2026-06-02"}
        ).json()
        assert body["total"] == 3
        first = body["points"][0]
        # Decimal amounts serialise as lossless JSON strings.
        assert first["balance_eur"] == "1000.0000"
        assert first["balance_dkk"] == "7460.0000"
        assert first["account_currency"] == "EUR"

    def test_group_total_sums_per_day(self, client: TestClient) -> None:
        body = client.get(
            "/net-worth/daily",
            params={"since": "2026-06-01", "until": "2026-06-02", "group": "total"},
        ).json()
        assert body["total"] == 2
        day_one, day_two = body["points"]
        assert day_one["as_of"] == "2026-06-01"
        assert day_one["balance_eur"] == "1500.0000"
        assert day_one["balance_dkk"] == "11190.0000"
        assert day_two["balance_eur"] == "1010.0000"

    def test_account_filter(self, client: TestClient) -> None:
        body = client.get(
            "/net-worth/daily",
            params={"since": "2026-06-01", "until": "2026-06-02", "account_id": "a2"},
        ).json()
        assert body["total"] == 1
        assert body["points"][0]["account_id"] == "a2"

    def test_pagination(self, client: TestClient) -> None:
        body = client.get(
            "/net-worth/daily",
            params={"since": "2026-06-01", "until": "2026-06-02", "limit": 2, "offset": 2},
        ).json()
        assert body["total"] == 3
        assert len(body["points"]) == 1
        assert body["offset"] == 2

    def test_limit_above_cap_rejected(self, client: TestClient) -> None:
        response = client.get("/net-worth/daily", params={"limit": 10_001})
        assert response.status_code == 422

    def test_invalid_group_rejected(self, client: TestClient) -> None:
        response = client.get("/net-worth/daily", params={"group": "currency"})
        assert response.status_code == 422


class TestCashflow:
    def test_inflow_outflow_net_in_three_currencies(self, client: TestClient) -> None:
        body = client.get(
            "/cashflow/daily", params={"since": "2026-06-01", "until": "2026-06-02"}
        ).json()
        assert body["total"] == 1
        point = body["points"][0]
        assert point["net_acct_ccy"] == "60.0000"
        assert point["net_eur"] == "60.0000"
        assert point["net_dkk"] == "447.6000"

    def test_empty_window_returns_no_points(self, client: TestClient) -> None:
        body = client.get(
            "/cashflow/daily", params={"since": "2030-01-01", "until": "2030-01-31"}
        ).json()
        assert body["points"] == []
        assert body["total"] == 0


class TestAllocation:
    def test_default_groups_by_kind(self, client: TestClient) -> None:
        body = client.get("/allocation/current").json()
        assert body["by"] == "kind"
        assert body["as_of"] == "2026-06-02"
        labels = {entry["label"] for entry in body["slices"]}
        assert labels == {"frie_midler", "aktiesparekonto"}

    def test_kind_slices_sum_balances(self, client: TestClient) -> None:
        body = client.get("/allocation/current").json()
        by_label = {entry["label"]: entry for entry in body["slices"]}
        assert by_label["frie_midler"]["balance_eur"] == "1500.0000"
        assert by_label["aktiesparekonto"]["balance_eur"] == "500.0000"

    def test_weights_sum_to_one(self, client: TestClient) -> None:
        body = client.get("/allocation/current").json()
        total_weight = sum(float(entry["weight_eur"]) for entry in body["slices"])
        assert abs(total_weight - 1.0) < 1e-9

    def test_group_by_entity(self, client: TestClient) -> None:
        body = client.get("/allocation/current", params={"by": "entity"}).json()
        labels = {entry["label"] for entry in body["slices"]}
        assert labels == {"Synthetic A", "Synthetic B"}

    def test_invalid_dimension_rejected(self, client: TestClient) -> None:
        response = client.get("/allocation/current", params={"by": "provider"})
        assert response.status_code == 422


class TestAccounts:
    def test_iban_masked_to_last_four(self, client: TestClient) -> None:
        body = client.get("/accounts").json()
        depot = next(entry for entry in body if entry["account_id"] == "a1")
        assert depot["iban_masked"].endswith("6243")
        assert depot["iban_masked"].count("•") == len("DK5000400440116243") - 4
        assert "DK50" not in depot["iban_masked"]

    def test_name_suffix_masked(self, client: TestClient) -> None:
        body = client.get("/accounts").json()
        depot = next(entry for entry in body if entry["account_id"] == "a1")
        assert depot["name"] == "Depot (••••)"

    def test_missing_iban_serialises_as_empty_string(self, client: TestClient) -> None:
        body = client.get("/accounts").json()
        cash = next(entry for entry in body if entry["account_id"] == "a2")
        assert cash["iban_masked"] == ""

    def test_missing_name_serialises_as_empty_string(self, client: TestClient) -> None:
        body = client.get("/accounts").json()
        manual = next(entry for entry in body if entry["account_id"] == "a3")
        assert manual["name"] == ""

    def test_raw_iban_never_in_payload(self, client: TestClient) -> None:
        assert "DK5000400440116243" not in client.get("/accounts").text


class TestFreshness:
    def test_reports_every_served_mart(self, client: TestClient) -> None:
        body = client.get("/meta/freshness").json()
        marts = {entry["mart"]: entry for entry in body["marts"]}
        assert marts["mart_net_worth_daily"]["latest_as_of"] == "2026-06-02"
        assert marts["mart_cashflow_daily"]["latest_as_of"] is None
        assert marts["mart_cashflow_daily"]["row_count"] == 0


class TestReturnsDaily:
    def test_household_factors_in_both_currencies(self, client: TestClient) -> None:
        body = client.get(
            "/returns/daily", params={"since": "2026-06-01", "until": "2026-06-03"}
        ).json()
        assert body["total"] == 3
        first = body["points"][0]
        assert first["scope"] == "household"
        assert first["return_factor_eur"] == "1.0100000000"
        assert first["return_factor_dkk"] == "1.0100000000"
        assert first["begin_mv_eur"] == "1000.0000"
        assert first["begin_mv_dkk"] == "7460.0000"

    def test_pagination(self, client: TestClient) -> None:
        body = client.get(
            "/returns/daily",
            params={"since": "2026-06-01", "until": "2026-06-03", "limit": 1, "offset": 2},
        ).json()
        assert body["total"] == 3
        assert len(body["points"]) == 1
        assert body["points"][0]["as_of"] == "2026-06-03"

    def test_scope_key_filter(self, client: TestClient) -> None:
        body = client.get(
            "/returns/daily",
            params={"since": "2026-06-01", "until": "2026-06-03", "scope_key": "nope"},
        ).json()
        assert body["total"] == 0

    def test_invalid_scope_rejected(self, client: TestClient) -> None:
        response = client.get("/returns/daily", params={"scope": "portfolio"})
        assert response.status_code == 422


class TestReturnsSummary:
    def test_chain_links_household_window(self, client: TestClient) -> None:
        body = client.get(
            "/returns/summary",
            params={"scope": "household", "since": "2026-06-01", "until": "2026-06-03"},
        ).json()
        assert body["scope"] == "household"
        (entry,) = body["entries"]
        assert entry["scope_key"] == "household"
        assert entry["days"] == 3
        assert entry["start_date"] == "2026-06-01"
        assert entry["end_date"] == "2026-06-03"
        # 1.01 * 1.00 * 1.02 = 1.0302 in both currency legs.
        assert entry["eur"]["cumulative_return"] == "0.0302"
        assert entry["dkk"]["cumulative_return"] == "0.0302"
        assert entry["eur"]["error"] is None
        # 3-day window: below the 30-day annualization threshold.
        assert entry["eur"]["annualized_return"] is None

    def test_empty_window_returns_no_entries(self, client: TestClient) -> None:
        body = client.get(
            "/returns/summary",
            params={"scope": "household", "since": "2030-01-01", "until": "2030-01-31"},
        ).json()
        assert body["entries"] == []


class TestBenchmarks:
    def test_lists_instruments_with_price_history(self, client: TestClient) -> None:
        body = client.get("/benchmarks").json()
        (info,) = body
        assert info["instrument_id"] == "i1"
        assert info["ticker"] == "SYNW"
        assert info["points"] == 3

    def test_daily_series(self, client: TestClient) -> None:
        body = client.get(
            "/benchmarks/daily",
            params={"instrument_id": "i1", "since": "2026-06-01", "until": "2026-06-03"},
        ).json()
        assert body["total"] == 3
        assert body["points"][0]["close"] == "100.0000"
        assert body["points"][0]["currency"] == "EUR"

    def test_unknown_instrument_yields_empty_series(self, client: TestClient) -> None:
        body = client.get(
            "/benchmarks/daily",
            params={"instrument_id": "missing", "since": "2026-06-01", "until": "2026-06-03"},
        ).json()
        assert body["points"] == []
        assert body["total"] == 0

    def test_instrument_id_required(self, client: TestClient) -> None:
        assert client.get("/benchmarks/daily").status_code == 422


class TestFees:
    def test_yearly_totals_in_both_currencies(self, client: TestClient) -> None:
        body = client.get(
            "/returns/fees", params={"since": "2026-01-01", "until": "2026-12-31"}
        ).json()
        (row,) = body["rows"]
        assert row["year"] == 2026
        assert row["account_id"] == "a1"
        assert row["fees_eur"] == "24.0000"
        assert row["fees_dkk"] == "179.0400"
