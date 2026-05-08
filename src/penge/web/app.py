"""Streamlit entry point for the Penge dashboard.

Run with::

    uv run --group web --group db penge-web

or directly::

    uv run --group web --group db streamlit run src/penge/web/app.py

The four views from issue #25 are rendered as separate sidebar pages.
Data is fetched lazily via the typed helpers in ``penge.web.data`` and
cached for 5 minutes to keep navigation snappy without staling the
KPIs.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from penge.web import data as data_layer
from penge.web.views import allocation, drilldown, kpi, timeseries

# 5-minute TTL: refresh on a sensible cadence without forcing manual
# reloads after every loader run.
CACHE_TTL_SECONDS = 300

# Default lookback for the daily panel: ~3 years covers MoM/YoY plus
# enough history for the time-series view without dragging in everything.
DEFAULT_LOOKBACK_DAYS = 365 * 3


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Loading net-worth panel…")  # type: ignore[untyped-decorator]
def _load_net_worth(since: date) -> pd.DataFrame:
    return data_layer.fetch_net_worth_daily(since)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Loading accounts…")  # type: ignore[untyped-decorator]
def _load_accounts() -> pd.DataFrame:
    return data_layer.fetch_accounts()


def _sidebar() -> tuple[str, str, bool]:
    """Render the sidebar controls and return (view, currency, reveal)."""
    st.sidebar.title("Penge")
    st.sidebar.caption("Local-only — protect with Tailscale or Caddy basic-auth.")
    view = st.sidebar.radio(
        "View",
        options=("KPI", "Time series", "Allocation", "Account drill-down"),
        index=0,
    )
    currency = st.sidebar.selectbox("Display currency", options=("EUR", "DKK"), index=0)
    reveal = st.sidebar.checkbox(
        "Reveal account identifiers",
        value=False,
        help="When off, IBANs and last-4 suffixes are masked.",
    )
    return view, currency, reveal


def main() -> None:
    """Render the Streamlit app. Called both by ``streamlit run`` and tests."""
    st.set_page_config(page_title="Penge", layout="wide")

    view, currency, reveal = _sidebar()

    since = date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    try:
        panel = _load_net_worth(since)
        accounts = _load_accounts()
    except Exception as exc:
        st.error(f"Could not load data from the database: {exc}")
        st.info(
            "Check that Postgres is reachable and the marts have been "
            "built (`uv run --group dbt dbt build`)."
        )
        return

    if view == "KPI":
        kpi.render(panel, currency=currency)
    elif view == "Time series":
        timeseries.render(panel, currency=currency)
    elif view == "Allocation":
        allocation.render(panel, accounts, currency=currency, reveal=reveal)
    else:
        drilldown.render(panel, accounts, currency=currency, reveal=reveal)


# Streamlit imports the script and executes it top-level when run via
# `streamlit run` or via ``streamlit.testing.v1.AppTest.from_file``.
main()
