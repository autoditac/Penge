"""Time series stacked area by asset class.

The skeleton groups by ``account_currency`` rather than asset class
because the v1 mart does not yet expose ``instrument.kind``. Once the
mart is extended with an asset-class column (issue #25 follow-up),
swap the grouping key — the chart shape remains the same.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penge.web.data import balance_column


def render(panel: pd.DataFrame, *, currency: str) -> None:
    """Render the time-series area chart."""
    st.header(f"Net worth over time — {currency}")

    if panel.empty:
        st.info("No data yet.")
        return

    column = balance_column(currency)
    grouped = (
        panel.dropna(subset=[column])
        .groupby(["as_of", "account_currency"], as_index=False)[column]
        .sum()
    )

    if grouped.empty:
        st.info(f"No {currency}-denominated balances available yet.")
        return

    fig = px.area(
        grouped,
        x="as_of",
        y=column,
        color="account_currency",
        labels={
            "as_of": "Date",
            column: f"Net worth ({currency})",
            "account_currency": "Account currency",
        },
    )
    fig.update_layout(margin={"l": 0, "r": 0, "t": 10, "b": 0}, height=420)
    st.plotly_chart(fig, use_container_width=True)
