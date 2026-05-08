"""Headless smoke test for the Streamlit app.

Drives ``app.py`` via ``streamlit.testing.v1.AppTest`` with the data
fetchers monkeypatched to return synthetic frames. Verifies all four
views render without raising, satisfying issue #25's "All 4 views
render against the loaded data" acceptance criterion.

The full Playwright/screenshot regression mentioned in the issue is
deferred to a follow-up — it requires browser automation in CI which
is out of scope for the skeleton.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from penge.web import data as data_layer

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

APP_PATH = Path(__file__).resolve().parents[2] / "src" / "penge" / "web" / "app.py"


def _fake_panel() -> pd.DataFrame:
    today = date(2026, 5, 1)
    rows: list[dict[str, object]] = []
    for offset in range(0, 400, 7):  # weekly snapshots over ~13 months
        as_of = today - timedelta(days=offset)
        for acct, ccy, eur, dkk in (
            ("a-eur", "EUR", 1000.0 + offset, 1000.0 + offset),
            ("a-dkk", "DKK", 7460.0 + offset, None),
        ):
            rows.append(
                {
                    "entity_id": "e-1",
                    "account_id": acct,
                    "account_currency": ccy,
                    "as_of": as_of,
                    "balance_acct_ccy": eur,
                    "balance_eur": eur,
                    "balance_dkk": (eur * 7.46) if dkk is None else dkk * 7.46 / 7460.0,
                }
            )
    return pd.DataFrame(rows)


def _fake_accounts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "account_id": "a-eur",
                "entity_id": "e-1",
                "provider": "test",
                "account_name": "Aktiesparekonto (1162)",
                "account_kind": "aktiesparekonto",
                "currency": "EUR",
                "iban": "DK5000400440116243",
                "opened_at": None,
                "closed_at": None,
                "entity_name": "Test Person",
                "entity_kind": "person",
            },
            {
                "account_id": "a-dkk",
                "entity_id": "e-1",
                "provider": "test",
                "account_name": "Lønkonto (4242)",
                "account_kind": "frie_midler",
                "currency": "DKK",
                "iban": "DK5000400440114242",
                "opened_at": None,
                "closed_at": None,
                "entity_name": "Test Person",
                "entity_kind": "person",
            },
        ]
    )


@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]
def _patch_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace DB fetchers with deterministic in-memory frames.

    Also clears Streamlit's data cache so previously-cached real
    fetches do not leak across tests run in the same process.
    """
    monkeypatch.setattr(data_layer, "fetch_net_worth_daily", lambda _since: _fake_panel())
    monkeypatch.setattr(data_layer, "fetch_accounts", _fake_accounts)

    import streamlit as st

    st.cache_data.clear()


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "view",
    ["KPI", "Time series", "Allocation", "Account drill-down"],
)
def test_all_views_render(view: str) -> None:
    """Each of the four sidebar views runs to completion without exception."""
    app = AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()
    assert not app.exception, [str(e) for e in app.exception]

    # Pick the requested view from the sidebar radio.
    radio = app.sidebar.radio[0]
    radio.set_value(view).run()
    assert not app.exception, [str(e) for e in app.exception]

    # The header is rendered by every view; if the page crashed before
    # it, the markdown collection would be empty.
    assert app.header, f"view {view!r} produced no header"


def test_account_identifiers_masked_by_default() -> None:
    """The drill-down view must not leak full IBANs unless reveal is on."""
    app = AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()
    app.sidebar.radio[0].set_value("Account drill-down").run()
    assert not app.exception, [str(e) for e in app.exception]

    rendered = " ".join(c.value for c in app.caption)
    assert "DK5000400440116243" not in rendered
    assert "DK5000400440114242" not in rendered
    assert "•" in rendered  # masking marker present


def test_reveal_toggle_unmasks_iban() -> None:
    """Flipping the sidebar reveal checkbox shows the full IBAN."""
    app = AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()
    app.sidebar.checkbox[0].set_value(True).run()
    app.sidebar.radio[0].set_value("Account drill-down").run()
    assert not app.exception, [str(e) for e in app.exception]

    rendered = " ".join(c.value for c in app.caption)
    # One of the two fake IBANs must now appear unmasked.
    assert "DK5000400440116243" in rendered or "DK5000400440114242" in rendered
