"""Unit tests for the pure helpers in ``penge.web.data``.

Network/DB paths (`fetch_net_worth_daily`, `fetch_accounts`) are
exercised indirectly by the smoke test via monkeypatched fakes; here
we cover the pure pandas helpers (`latest_total`, `delta_pct`,
`balance_column`).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from penge.web.data import balance_column, delta_pct, latest_total


def _panel() -> pd.DataFrame:
    """Two accounts crossed with four dates, with EUR and DKK columns populated."""
    today = date(2026, 5, 1)
    rows: list[dict[str, object]] = []
    for offset in (365, 30, 7, 0):
        as_of = today - timedelta(days=offset)
        for acct, eur, dkk in (("a1", 1000.0, 7460.0), ("a2", 500.0, 3730.0)):
            # Make EUR drift +10% YoY, +5% MoM so the assertions below
            # have predictable values.
            scale = {365: 1 / 1.10, 30: 1 / 1.05, 7: 1.0, 0: 1.0}[offset]
            rows.append(
                {
                    "entity_id": "e1",
                    "account_id": acct,
                    "account_currency": "EUR" if acct == "a1" else "DKK",
                    "as_of": as_of,
                    "balance_acct_ccy": eur if acct == "a1" else dkk,
                    "balance_eur": eur * scale,
                    "balance_dkk": dkk * scale,
                }
            )
    return pd.DataFrame(rows)


class TestBalanceColumn:
    def test_eur(self) -> None:
        assert balance_column("EUR") == "balance_eur"
        assert balance_column("eur") == "balance_eur"

    def test_dkk(self) -> None:
        assert balance_column("DKK") == "balance_dkk"

    def test_unsupported_raises(self) -> None:
        with pytest.raises(ValueError, match="unsupported display currency"):
            balance_column("USD")


class TestLatestTotal:
    def test_sums_all_accounts_on_latest_date(self) -> None:
        panel = _panel()
        # Latest is offset=0, scale=1.0 → 1000 + 500 = 1500 EUR.
        assert latest_total(panel, "EUR") == pytest.approx(1500.0)

    def test_empty_panel_returns_none(self) -> None:
        assert latest_total(pd.DataFrame(), "EUR") is None


class TestDeltaPct:
    def test_mom_uses_at_or_before(self) -> None:
        # MoM target is latest - 30d, where balance was scaled to 1/1.05.
        # Pct change = (1500 - 1500/1.05) / (1500/1.05) ≈ +5%.
        assert delta_pct(_panel(), "EUR", days_back=30) == pytest.approx(5.0, abs=0.01)

    def test_yoy(self) -> None:
        assert delta_pct(_panel(), "EUR", days_back=365) == pytest.approx(10.0, abs=0.01)

    def test_no_earlier_endpoint_returns_none(self) -> None:
        # Asking for a 10-year delta against a 1-year panel.
        assert delta_pct(_panel(), "EUR", days_back=365 * 10) is None
