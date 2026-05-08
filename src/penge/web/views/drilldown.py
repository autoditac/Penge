"""Per-account drill-down: balance over time for a chosen account.

Account identifiers (IBAN, last-4 suffix in the display name) are
masked by default; the sidebar "Reveal account identifiers" toggle
gates the unmasked view. This satisfies the issue #25 acceptance
criterion *No raw account numbers shown by default*.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penge.web.data import balance_column
from penge.web.mask import mask_account_name, mask_iban


def render(
    panel: pd.DataFrame,
    accounts: pd.DataFrame,
    *,
    currency: str,
    reveal: bool,
) -> None:
    """Render the account drill-down page."""
    st.header(f"Account drill-down — {currency}")

    if panel.empty or accounts.empty:
        st.info("No data yet.")
        return

    accounts = accounts.copy()
    accounts["display_name"] = accounts.apply(
        lambda row: f"{row['entity_name']} — "
        f"{mask_account_name(row['account_name'], reveal=reveal)}",
        axis=1,
    )
    accounts["display_iban"] = accounts["iban"].apply(lambda v: mask_iban(v, reveal=reveal))

    options = accounts.set_index("account_id")["display_name"].to_dict()
    if not options:
        st.info("No accounts loaded yet.")
        return

    selected_id = st.selectbox(
        "Account",
        options=list(options.keys()),
        format_func=lambda aid: options[aid],
    )

    column = balance_column(currency)
    series = (
        panel.loc[panel["account_id"] == selected_id, ["as_of", column]]
        .dropna()
        .sort_values("as_of")
    )
    if series.empty:
        st.info("No balance history for this account yet.")
        return

    meta_row = accounts.loc[accounts["account_id"] == selected_id].iloc[0]
    st.caption(
        f"**Provider:** {meta_row['provider']} · "
        f"**Kind:** {meta_row['account_kind']} · "
        f"**Currency:** {meta_row['currency']} · "
        f"**IBAN:** {meta_row['display_iban'] or '—'}"
    )

    fig = px.line(
        series,
        x="as_of",
        y=column,
        labels={"as_of": "Date", column: f"Balance ({currency})"},
    )
    fig.update_layout(margin={"l": 0, "r": 0, "t": 10, "b": 0}, height=420)
    st.plotly_chart(fig, use_container_width=True)
