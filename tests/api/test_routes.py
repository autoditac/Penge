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

    def test_raw_iban_never_in_payload(self, client: TestClient) -> None:
        assert "DK5000400440116243" not in client.get("/accounts").text


class TestFreshness:
    def test_reports_every_served_mart(self, client: TestClient) -> None:
        body = client.get("/meta/freshness").json()
        marts = {entry["mart"]: entry for entry in body["marts"]}
        assert marts["mart_net_worth_daily"]["latest_as_of"] == "2026-06-02"
        assert marts["mart_cashflow_daily"]["latest_as_of"] is None
        assert marts["mart_cashflow_daily"]["row_count"] == 0
